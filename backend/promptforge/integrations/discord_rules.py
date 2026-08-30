"""Discord "What gets posted" rules engine (9.6, wired from Phase 4).

Pure-function evaluation (`post_matches`, `route_channel`) + stateful
throttle/digest driven from the ingest hook and the scheduler tick. Stored in
settings key `discord_rules` (D32)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..logbus import bus
from ..models import CollectionPost, Post

DEFAULT_RULES: dict = {
    # mode: manual | all | favorites | collections | families | platforms
    "mode": "manual",
    "collections": [],          # collection ids (mode=collections)
    "families": [],             # model family slugs (mode=families)
    "platforms": [],            # platform slugs (mode=platforms)
    # AND filters on top of mode
    "media": "both",            # images | videos | both
    "require_prompt": True,
    "sfw_only": True,
    # delivery
    "delivery": "individual",   # individual | digest
    "digest_hours": 6,
    "digest_count": 8,
    # routing: [{"match": "collection"|"family", "value": id-or-slug, "channel_id": "..."}]
    "routes": [],
    # safety rail
    "throttle_per_hour": 12,
}


def get_rules(s: Session) -> dict:
    stored = settings_store.get(s, "discord_rules")
    rules = dict(DEFAULT_RULES)
    if isinstance(stored, dict):
        rules.update({k: v for k, v in stored.items() if k in DEFAULT_RULES})
    return rules


def _post_collection_ids(s: Session, post_id: int) -> list[int]:
    return [r[0] for r in s.execute(select(CollectionPost.collection_id).where(
        CollectionPost.post_id == post_id))]


def post_matches(rules: dict, post: Post, collection_ids: list[int]) -> bool:
    """Does this post pass the mode + AND-filters?"""
    mode = rules.get("mode", "manual")
    if mode == "manual":
        return False
    if mode == "favorites" and not post.favorite:
        return False
    if mode == "collections" and not (set(collection_ids) &
                                      set(rules.get("collections") or [])):
        return False
    if mode == "families" and post.model_family not in (rules.get("families") or []):
        return False
    if mode == "platforms" and post.platform not in (rules.get("platforms") or []):
        return False
    media = rules.get("media", "both")
    if media == "images" and post.media_type != "image":
        return False
    if media == "videos" and post.media_type != "video":
        return False
    if rules.get("require_prompt", True) and not (post.prompt or "").strip():
        return False
    if rules.get("sfw_only", True) and post.nsfw:
        return False
    return True


def route_channel(rules: dict, post: Post, collection_ids: list[int],
                  default_channel: str | None) -> str | None:
    """Channel routing: first matching rule wins; else the default channel."""
    for route in rules.get("routes") or []:
        match, value = route.get("match"), route.get("value")
        if match == "family" and post.model_family == value:
            return str(route.get("channel_id") or default_channel or "") or None
        if match == "collection" and value in collection_ids:
            return str(route.get("channel_id") or default_channel or "") or None
        if match == "platform" and post.platform == value:
            return str(route.get("channel_id") or default_channel or "") or None
    return str(default_channel) if default_channel else None


class Throttle:
    """Sliding-window per-channel rate limit."""

    def __init__(self):
        self._sent: dict[str, list[float]] = {}

    def allow(self, channel_id: str, per_hour: int, now: float | None = None) -> bool:
        now = now or time.time()
        window = [t for t in self._sent.get(channel_id, []) if now - t < 3600]
        self._sent[channel_id] = window
        if per_hour <= 0 or len(window) >= per_hour:
            return False
        window.append(now)
        return True


throttle = Throttle()
_digest_queue: list[int] = []
_last_digest_at: float = 0.0


def evaluate_new_post(post_id: int) -> None:
    """Ingest hook: post immediately (individual) or queue (digest)."""
    from ..db import session_scope
    from . import discord_bot
    with session_scope() as s:
        token = settings_store.get(s, "discord_bot_token")
        if not token:
            return
        post = s.get(Post, post_id)
        if post is None:
            return
        rules = get_rules(s)
        coll_ids = _post_collection_ids(s, post_id)
        if not post_matches(rules, post, coll_ids):
            return
        if rules.get("delivery") == "digest":
            _digest_queue.append(post_id)
            return
        channel = route_channel(rules, post, coll_ids,
                                settings_store.get(s, "discord_channel_id"))
    if not channel:
        return
    if not throttle.allow(channel, rules.get("throttle_per_hour", 12)):
        bus.warn("discord", f"throttled — skipped auto-post of {post_id}")
        return
    discord_bot.post_by_id(post_id, channel)


def digest_tick(force: bool = False) -> None:
    """Scheduler tick: flush the digest queue every `digest_hours`."""
    global _last_digest_at
    from ..db import session_scope
    from . import discord_bot
    with session_scope() as s:
        token = settings_store.get(s, "discord_bot_token")
        if not token:
            return
        rules = get_rules(s)
        if rules.get("delivery") != "digest":
            return
        interval_s = max(1, int(rules.get("digest_hours", 6))) * 3600
        if not force and time.time() - _last_digest_at < interval_s:
            return
        if not _digest_queue:
            _last_digest_at = time.time()
            return
        count = max(1, int(rules.get("digest_count", 8)))
        batch = list(dict.fromkeys(_digest_queue))[-count:]
        _digest_queue.clear()
        channel = settings_store.get(s, "discord_channel_id")
    _last_digest_at = time.time()
    if not channel:
        return
    if throttle.allow(str(channel), rules.get("throttle_per_hour", 12)):
        discord_bot.post_digest(batch, str(channel))


def preview_last_24h(s: Session) -> dict:
    """Live preview: 'would have posted N items in the last 24h with these rules'."""
    rules = get_rules(s)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    posts = s.execute(select(Post).where(Post.scraped_at >= cutoff)).scalars().all()
    matched = [p.id for p in posts
               if post_matches(rules, p, _post_collection_ids(s, p.id))]
    n = len(matched)
    throttle_cap = int(rules.get("throttle_per_hour", 12)) * 24
    if rules.get("delivery") == "digest":
        per_day = 24 / max(1, int(rules.get("digest_hours", 6)))
        capped = min(n, int(per_day) * int(rules.get("digest_count", 8)))
        return {"scanned": len(posts), "matched": n, "would_post": min(capped, throttle_cap),
                "delivery": "digest"}
    return {"scanned": len(posts), "matched": n,
            "would_post": min(n, throttle_cap), "delivery": "individual"}
