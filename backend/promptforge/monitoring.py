"""Follow-list monitoring (Phase X2, D52; source-neutral since I10).

Walk active monitored creators on their intervals, pull each timeline through
THAT CREATOR'S OWN adapter (X, Reddit, Bluesky, YouTube, … — anything whose
adapter declares the `author` capability), push finds through the normal
pipeline, apply per-account auto-tag / auto-collection, advance the cursor.
One failing account never blocks the rest, and a platform whose adapter is
missing or unconfigured is reported on the row rather than crashing the tick.

Nothing here needs Grok or X: `added_by="grok"` is only an evidence label
(D71) and creator discovery has a provider-neutral path (intel/discovery.py).
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from . import fts, settings_store
from .aliases import display_family
from .db import session_scope
from .logbus import bus
from .models import (Collection, CollectionPost, MonitoredAccount, Post,
                     PostTag, Tag)
from .intel import handles
from .pipeline.ingest import IngestStats, ingest_batch
from .scrapers import get_adapter

# kept for backwards compatibility with existing callers/tests: both default
# to X but now delegate to the per-platform rules (I10).
HANDLE_RE = handles.rule("x")["re"]


def normalize_handle(raw: str, platform: str = "x") -> str | None:
    return handles.normalize(raw, platform)


def parse_bulk(text: str, platform: str = "x") -> tuple[list[str], list[str]]:
    return handles.parse_bulk(text, platform)


# ------------------------------------------------------------- polling ------
def _apply_auto_actions(account: MonitoredAccount, new_ids: list[int]) -> None:
    if not new_ids:
        return
    with session_scope() as s:
        tag = None
        if account.auto_tag:
            name = account.auto_tag.strip()
            if name:
                tag = s.execute(select(Tag).where(
                    func.lower(Tag.name) == name.lower())).scalar_one_or_none()
                if tag is None:
                    tag = Tag(name=name)
                    s.add(tag)
                    s.flush()
        collection = (s.get(Collection, account.auto_collection_id)
                      if account.auto_collection_id else None)
        for pid in new_ids:
            post = s.get(Post, pid)
            if post is None:
                continue
            if tag is not None:
                exists = s.execute(select(PostTag).where(
                    PostTag.post_id == pid, PostTag.tag_id == tag.id)).first()
                if not exists:
                    s.add(PostTag(post_id=pid, tag_id=tag.id))
                    s.flush()
                names = [t.name for t in s.execute(
                    select(Tag).join(PostTag, PostTag.tag_id == Tag.id)
                    .where(PostTag.post_id == pid)).scalars()]
                fts.index_post(s, pid, post.prompt, post.model_name, names)
            if collection is not None:
                # respect model-family scoping exactly like the API (3.1)
                if (post.model_family and collection.model_family
                        and post.model_family != collection.model_family
                        and not collection.allow_mixed_models):
                    bus.warn("monitoring",
                             f"@{account.handle}: post {pid} is "
                             f"{display_family(post.model_family)} — collection "
                             f"“{collection.name}” holds "
                             f"{display_family(collection.model_family)}, skipped")
                    continue
                if collection.model_family is None and post.model_family:
                    members = s.execute(select(func.count(CollectionPost.post_id))
                                        .where(CollectionPost.collection_id ==
                                               collection.id)).scalar_one()
                    if members == 0:
                        collection.model_family = post.model_family
                exists = s.execute(select(CollectionPost).where(
                    CollectionPost.collection_id == collection.id,
                    CollectionPost.post_id == pid)).first()
                if not exists:
                    s.add(CollectionPost(collection_id=collection.id, post_id=pid))
                if collection.cover_post_id is None:
                    collection.cover_post_id = pid


def _fetch_author_posts(adapter, s, client, handle: str, *, since_id, media_only: bool):
    """Call whichever author API this adapter offers (X keeps its richer
    signature; the social adapters take a simple limit)."""
    try:
        return adapter.fetch_account(s, client, handle, since_id=since_id,
                                     media_only=media_only)
    except AttributeError:
        return adapter.fetch_author(s, client, handle, limit=60)


def run_account(account_id: int, manual: bool = False) -> IngestStats | None:
    """Poll one monitored creator on its own platform. Never raises; the
    outcome always lands on the row."""
    src = "monitoring"
    with session_scope() as s:
        account = s.get(MonitoredAccount, account_id)
        if account is None:
            return None
        if not account.active and not manual:
            return None
        handle = account.handle
        platform = account.platform or "x"
        adapter = get_adapter(platform)
        since_id = None
        if account.last_post_id and str(account.last_post_id).isdigit():
            since_id = int(account.last_post_id)
        media_only = account.media_only
        if adapter is None:
            account.status = "error"
            account.last_error = (f"No adapter for platform '{platform}' — it may have "
                                  "been removed or renamed.")
            account.last_checked = datetime.now(timezone.utc)
            bus.warn(src, f"{platform}/@{handle}: skipped — no adapter")
            return None
        can_author = (hasattr(adapter, "fetch_account") or hasattr(adapter, "fetch_author")
                      or "author" in (getattr(adapter, "capabilities", None) or frozenset()))
        if not can_author:
            account.status = "unsupported"
            account.last_error = (f"{adapter.label} doesn't expose creator timelines, so "
                                  "this creator can't be polled. Their posts still arrive "
                                  "through search/discovery.")
            account.last_checked = datetime.now(timezone.utc)
            return None
        if not adapter.is_configured(s):
            account.status = "needs_setup"
            reason = None
            if hasattr(adapter, "needs_setup_reason"):
                reason = adapter.needs_setup_reason(s)
            account.last_error = reason or (
                f"{getattr(adapter, 'label', platform)} is not connected yet — open "
                "Inspiration → Sources to set it up.")
            account.last_checked = datetime.now(timezone.utc)
            bus.warn(src, f"{platform}/@{handle}: skipped — {account.last_error}")
            return None

    stats: IngestStats | None = None
    client = None
    try:
        bus.info(src, f"{platform}/@{handle}: polling (cursor {since_id or 'none'})")
        with session_scope() as s:
            client = adapter.make_client(s)
            posts = _fetch_author_posts(adapter, s, client, handle,
                                        since_id=since_id, media_only=media_only)
        stats = ingest_batch(platform, posts, client, gate=False)  # followed creators skip the score gate (D64)
        numeric_ids = [int(str(p.platform_post_id).split("-")[0]) for p in posts
                       if str(p.platform_post_id).split("-")[0].isdigit()]
        max_id = max(numeric_ids, default=None)
        with session_scope() as s:
            account = s.get(MonitoredAccount, account_id)
            if account is None:
                return stats
            account.last_checked = datetime.now(timezone.utc)
            account.last_new = stats.new
            account.status = "ok"
            account.last_error = None
            ev = dict(account.evidence or {})
            # a discovery CLAIM (from Grok or from PF2's own source search)
            # only becomes verified when PF2 itself sees real posts (D71)
            if ev.get("source") and not ev.get("verified") and stats.found:
                # PF2 itself reached the account and saw real posts: the claim
                # is now backed by source evidence (never by the LLM alone)
                ev.update({"verified": True,
                           "verified_at": datetime.now(timezone.utc).isoformat(),
                           "verified_by": "first successful poll",
                           "posts_seen": stats.found})
                account.evidence = ev
            if max_id is not None and (not account.last_post_id
                                       or max_id > int(account.last_post_id)):
                account.last_post_id = str(max_id)
            acct_snapshot = account
        _apply_auto_actions(acct_snapshot, stats.new_ids)
        bus.info(src, f"{platform}/@{handle}: {stats.new} new, {stats.duplicates} dupes")
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        not_found = "404" in message or "NotFound" in message
        with session_scope() as s:
            account = s.get(MonitoredAccount, account_id)
            if account is not None:
                account.last_checked = datetime.now(timezone.utc)
                account.status = "not_found" if not_found else "error"
                account.last_error = message[:500]
        bus.error(src, f"{platform}/@{handle}: poll failed — {message}")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return stats


def due_account_ids(now: datetime | None = None) -> list[int]:
    now = now or datetime.now(timezone.utc)
    with session_scope() as s:
        rows = s.execute(select(MonitoredAccount).where(
            MonitoredAccount.active.is_(True))).scalars().all()
        due = []
        for a in rows:
            if a.last_checked is None:
                due.append(a.id)
                continue
            last = a.last_checked
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last + timedelta(minutes=max(5, a.check_interval)) <= now:
                due.append(a.id)
        return due


def monitor_tick() -> int:
    """Scheduler entry: poll every due account, serialized with all other
    browser runs via the scheduler's global lock (D22)."""
    ids = due_account_ids()
    if not ids:
        return 0
    from . import scheduler
    ran = 0
    for account_id in ids:
        with session_scope() as s:
            acct = s.get(MonitoredAccount, account_id)
            platform = (acct.platform if acct else "x") or "x"
        adapter = get_adapter(platform)
        # only browser runs contend for Chromium (D22); HTTP sources (Reddit,
        # Bluesky, YouTube…) poll without taking the global scraper lock
        if int(getattr(adapter, "tier", 2) or 2) >= 2:
            with scheduler._run_lock:
                run_account(account_id)
        else:
            run_account(account_id)
        ran += 1
    return ran


def set_all_active(active: bool) -> int:
    with session_scope() as s:
        rows = s.execute(select(MonitoredAccount)).scalars().all()
        for a in rows:
            a.active = active
        return len(rows)


_manual_threads: list[threading.Thread] = []


def run_account_async(account_id: int) -> None:
    from . import scheduler
    def _run():
        with scheduler._run_lock:
            run_account(account_id, manual=True)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _manual_threads.append(t)
