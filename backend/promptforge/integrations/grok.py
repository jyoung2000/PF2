"""Grok / xAI integration (Phase X3, D53/D54): an optional intelligence layer
on top of X.

- chat(): xAI's OpenAI-compatible endpoint, with optional LIVE X SEARCH via
  `search_parameters` — used by discover.
- discover_creators(): interest → reviewable candidate accounts (never
  auto-followed), de-duped against the follow list.
- curate: batched, budgeted pass over fresh X posts — confirms AI media,
  infers the model when unstated (inferred vs stated, only fills blanks),
  suggests tags + whitelisted technique labels.
- digest: periodic "what's new from your monitored accounts" summary,
  in-app + optional Discord.

Every feature no-ops cleanly to "Needs setup" when no key is present. The
knowledge engine can ALSO use Grok — the LLM factory gains provider "grok"
(see llm/client.py); this module is only the X-specific layer."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import fts, settings_store
from ..aliases import normalize_model
from ..db import session_scope
from ..knowledge import techniques
from ..logbus import bus
from ..models import MonitoredAccount, Post, PostTag, Tag

CURATE_BATCH = 15
MAX_TAGS_PER_POST = 4


class GrokError(Exception):
    def __init__(self, message: str, step: str = "unknown"):
        super().__init__(message)
        self.step = step


class GrokBudgetExceeded(GrokError):
    def __init__(self, message: str):
        super().__init__(message, "budget")


# ------------------------------------------------------------- http layer ---
def _base(s: Session) -> str:
    return (settings_store.get(s, "grok_base_url") or "https://api.x.ai/v1").rstrip("/")


def is_configured(s: Session) -> bool:
    return bool(settings_store.get(s, "grok_api_key"))


def _client(key: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    kw: dict = {"timeout": 120, "headers": {"Authorization": f"Bearer {key}"}}
    if transport is not None:
        kw["transport"] = transport
    return httpx.Client(**kw)


def chat(key: str, base: str, model: str, messages: list[dict],
         search: bool = False, max_tokens: int = 1200,
         transport: httpx.BaseTransport | None = None) -> str:
    payload: dict = {"model": model, "messages": messages,
                     "max_tokens": max_tokens}
    if search:
        payload["search_parameters"] = {"mode": "on",
                                        "sources": [{"type": "x"}],
                                        "return_citations": False}
    with _client(key, transport) as c:
        try:
            resp = c.post(f"{base}/chat/completions", json=payload)
        except httpx.HTTPError as e:
            raise GrokError(f"Can't reach xAI at {base} ({type(e).__name__}).",
                            "network") from e
    if resp.status_code in (401, 403):
        raise GrokError("xAI rejected the API key (401) — regenerate it at "
                        "console.x.ai and paste it in Settings → Grok.", "auth")
    if resp.status_code == 404:
        raise GrokError(f"xAI doesn't know model '{model}' — hit Test "
                        "connection to pick from the live model list.", "model")
    if resp.status_code == 429:
        raise GrokError("xAI rate limit hit (429) — the job will retry on its "
                        "next scheduled pass.", "rate")
    if resp.status_code >= 400:
        raise GrokError(f"xAI error HTTP {resp.status_code}: "
                        f"{resp.text[:200]}", "api")
    try:
        return resp.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise GrokError("Unexpected response shape from xAI.", "api") from e


def test_connection(s: Session,
                    transport: httpx.BaseTransport | None = None) -> dict:
    key = settings_store.get(s, "grok_api_key")
    if not key:
        raise GrokError("No xAI key — create one at console.x.ai and paste it "
                        "in Settings → Grok.", "auth")
    with _client(key, transport) as c:
        try:
            resp = c.get(f"{_base(s)}/models")
        except httpx.HTTPError as e:
            raise GrokError(f"Can't reach xAI ({type(e).__name__}).",
                            "network") from e
    if resp.status_code in (401, 403):
        raise GrokError("xAI rejected the API key (401) — regenerate it at "
                        "console.x.ai.", "auth")
    if resp.status_code >= 400:
        raise GrokError(f"xAI error HTTP {resp.status_code}.", "api")
    models = [m.get("id") for m in resp.json().get("data", []) if m.get("id")]
    grok_models = [m for m in models if "grok" in m] or models
    return {"ok": True, "models": grok_models,
            "detail": f"Connected · {len(grok_models)} Grok model(s) available"}


# ---------------------------------------------------------------- budget ----
def _usage(s: Session) -> dict:
    usage = settings_store.get(s, "grok_usage", None) or {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if usage.get("date") != today:
        return {"date": today, "calls": 0, "by": {}}
    return usage


def get_usage(s: Session) -> dict:
    return _usage(s)


def _bump_usage(feature: str) -> None:
    with session_scope() as s:
        usage = _usage(s)
        usage["calls"] = int(usage.get("calls", 0)) + 1
        usage.setdefault("by", {})
        usage["by"][feature] = int(usage["by"].get(feature, 0)) + 1
        settings_store.put(s, "grok_usage", usage)


def _check_curate_budget(s: Session) -> None:
    budget = int(settings_store.get(s, "grok_curate_daily_budget") or 0)
    if budget <= 0:
        return
    used = int(_usage(s).get("by", {}).get("curate", 0))
    if used >= budget:
        raise GrokBudgetExceeded(
            f"Grok curation budget reached ({budget} calls today) — raise it "
            "in Settings → Grok or wait for the UTC reset.")


def _settings_call(s: Session) -> tuple[str, str, str]:
    key = settings_store.get(s, "grok_api_key")
    if not key:
        raise GrokError("Grok isn't configured — paste an xAI key in "
                        "Settings → Grok first.", "auth")
    return key, _base(s), settings_store.get(s, "grok_model") or "grok-3-mini"


def _extract_json(text: str):
    m = re.search(r"[\[{].*[\]}]", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


# ------------------------------------------------------------- discover -----
DISCOVER_SYSTEM = (
    "You scout X (Twitter) for accounts that consistently post AI-GENERATED "
    "images or videos matching the user's interest, using live X search. Only "
    "suggest real, currently-active accounts whose own posts are AI media "
    "(not commentators or news). Reply ONLY with a JSON array.")


def discover_creators(interest: str,
                      transport: httpx.BaseTransport | None = None) -> list[dict]:
    from .. import monitoring
    with session_scope() as s:
        if not settings_store.get(s, "grok_discover_enabled"):
            raise GrokError("Discover is switched off — enable it in "
                            "Settings → Grok.", "disabled")
        key, base, model = _settings_call(s)
        monitored = {a.handle for a in s.execute(
            select(MonitoredAccount)).scalars()}
    user = (f"Interest: {interest}\n\n"
            "Find up to 8 X accounts that genuinely publish this kind of "
            "AI-generated media. Reply with a JSON array:\n"
            '[{"handle": "no @", "display_name": "", '
            '"reason": "one line: why this account fits", '
            '"evidence": "a short quote from a real recent post of theirs", '
            '"detected_models": ["model names they themselves mention"], '
            '"content_type": "image|video|workflow|mixed", '
            '"engagement_estimate": "low|medium|high", '
            '"confidence": 0.0-1.0}]')
    raw = chat(key, base, model,
               [{"role": "system", "content": DISCOVER_SYSTEM},
                {"role": "user", "content": user}],
               search=True, transport=transport)
    _bump_usage("discover")
    data = _extract_json(raw)
    if not isinstance(data, list):
        raise GrokError("Grok returned no parseable candidate list — try a "
                        "more specific interest.", "parse")
    out: list[dict] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        handle = monitoring.normalize_handle(str(item.get("handle") or ""))
        if not handle or handle in seen:
            continue
        seen.add(handle)
        from ..aliases import normalize_model
        models_raw = item.get("detected_models") or []
        if isinstance(models_raw, str):
            models_raw = [models_raw]
        models = [str(m).strip()[:40] for m in models_raw if isinstance(m, (str, int)) and str(m).strip()][:6]
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        content_type = str(item.get("content_type") or "").lower()
        engagement = str(item.get("engagement_estimate") or "").lower()
        evidence = (str(item.get("evidence") or item.get("sample") or "").strip()[:300] or None)
        out.append({
            "handle": handle,
            "display_name": (str(item.get("display_name") or "").strip()
                             or None),
            "reason": str(item.get("reason") or "").strip()[:300],
            "sample": evidence,
            "evidence": evidence,
            "detected_models": models,
            "detected_families": sorted({normalize_model(m) for m in models}),
            "content_type": content_type if content_type in ("image", "video", "workflow", "mixed") else None,
            "engagement_estimate": engagement if engagement in ("low", "medium", "high") else None,
            "confidence": confidence,
            "source": "grok",          # a claim, not a fact — verified on first poll
            "verified": False,
            "already_monitored": handle in monitored,
        })
    bus.info("grok", f"discover '{interest[:40]}': {len(out)} candidate(s)")
    return out


# --------------------------------------------------------------- curation ---
CURATE_SYSTEM = (
    "You verify and enrich posts scraped from X for an AI-art library. For "
    "each item judge from the text alone: is it genuinely AI-GENERATED "
    "image/video content; which generation model made it (only if clearly "
    "inferable); useful short tags; and visual technique labels from the "
    "allowed list. Be conservative — null beats a guess. Reply ONLY with "
    "valid JSON.")


def _uncurated_x_posts(s: Session, limit: int) -> list[Post]:
    rows = s.execute(select(Post).where(Post.platform == "x")
                     .order_by(Post.id.desc()).limit(200)).scalars().all()
    return [p for p in rows
            if not isinstance((p.params or {}).get("grok"), dict)][:limit]


def curate_batch(batch: int = CURATE_BATCH,
                 transport: httpx.BaseTransport | None = None) -> int:
    """One budgeted Grok call over up to `batch` fresh X posts. Returns the
    number of posts curated (0 when nothing pending)."""
    with session_scope() as s:
        key, base, model = _settings_call(s)
        _check_curate_budget(s)
        posts = _uncurated_x_posts(s, batch)
        if not posts:
            return 0
        lines = []
        for p in posts:
            eng = (p.params or {}).get("engagement") or {}
            lines.append(
                f"[{p.id}] media={p.media_type} "
                f"stated_model={p.model_name or 'none'} "
                f"likes={eng.get('likes', 0)} "
                f"text={((p.prompt or '')[:220])!r}")
        post_ids = [p.id for p in posts]
    allowed = ", ".join(techniques.all_slugs())
    user = (f"{len(post_ids)} posts:\n" + "\n".join(lines) +
            "\n\nReply with JSON: {\"<post_id>\": {"
            "\"ai_media\": true/false, "
            "\"model\": \"model name or null\", "
            "\"model_confidence\": \"stated\"|\"inferred\", "
            f"\"tags\": [\"up to {MAX_TAGS_PER_POST} short lowercase tags\"], "
            "\"techniques\": [\"slugs from the allowed list only\"]}}\n"
            f"Allowed technique slugs: {allowed}")
    raw = chat(key, base, model,
               [{"role": "system", "content": CURATE_SYSTEM},
                {"role": "user", "content": user}],
               max_tokens=1600, transport=transport)
    _bump_usage("curate")
    result = _extract_json(raw)
    if not isinstance(result, dict):
        bus.warn("grok", "curate: unparseable reply — batch left for retry")
        return 0
    curated = _apply_curation(post_ids, result)
    bus.info("grok", f"curated {curated} X post(s)")
    return curated


def _apply_curation(post_ids: list[int], result: dict) -> int:
    """Write Grok's verdicts back (D54): params.grok, inferred model only into
    blanks, whitelisted techniques, ordinary user tags."""
    allowed = set(techniques.all_slugs())
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    with session_scope() as s:
        for pid in post_ids:
            verdict = result.get(str(pid)) or result.get(pid)
            post = s.get(Post, pid)
            if post is None:
                continue
            if not isinstance(verdict, dict):
                verdict = {}
            params = dict(post.params or {})
            params["grok"] = {
                "checked_at": now,
                "ai_media": bool(verdict.get("ai_media", True)),
                "model_confidence": (verdict.get("model_confidence")
                                     if verdict.get("model_confidence")
                                     in ("stated", "inferred") else None),
            }
            model = verdict.get("model")
            if (isinstance(model, str) and model.strip()
                    and model.strip().lower() not in ("null", "none", "unknown")
                    and not post.model_name):
                post.model_name = model.strip()[:150]
                with_user_rules = settings_store.get(s, "model_aliases") or {}
                post.model_family = normalize_model(post.model_name,
                                                    with_user_rules)
                params["model_inferred"] = True
            post.params = params
            slugs = [t for t in (verdict.get("techniques") or [])
                     if isinstance(t, str) and t in allowed]
            if slugs:
                post.technique_tags = sorted(
                    set((post.technique_tags or []) + slugs))
            tag_names: list[str] = []
            for name in (verdict.get("tags") or [])[:MAX_TAGS_PER_POST]:
                if not isinstance(name, str) or not name.strip():
                    continue
                name = name.strip().lower()[:60]
                tag = s.execute(select(Tag).where(
                    func.lower(Tag.name) == name)).scalar_one_or_none()
                if tag is None:
                    tag = Tag(name=name)
                    s.add(tag)
                    s.flush()
                exists = s.execute(select(PostTag).where(
                    PostTag.post_id == pid,
                    PostTag.tag_id == tag.id)).first()
                if not exists:
                    s.add(PostTag(post_id=pid, tag_id=tag.id))
                    s.flush()
            tag_names = [t.name for t in s.execute(
                select(Tag).join(PostTag, PostTag.tag_id == Tag.id)
                .where(PostTag.post_id == pid)).scalars()]
            fts.index_post(s, pid, post.prompt, post.model_name, tag_names)
            count += 1
    return count


def curate_tick() -> int:
    """Scheduler entry: batched curation while enabled+configured+in budget."""
    with session_scope() as s:
        if not (settings_store.get(s, "grok_curate_enabled")
                and is_configured(s)):
            return 0
    total = 0
    for _ in range(4):  # at most 4 calls per tick
        try:
            done = curate_batch()
        except GrokBudgetExceeded as e:
            bus.warn("grok", str(e))
            break
        except GrokError as e:
            bus.error("grok", f"curate failed: {e}")
            break
        if done == 0:
            break
        total += done
    return total


# ----------------------------------------------------------------- digest ---
DIGEST_SYSTEM = (
    "You write a short, sharp digest of what a user's monitored X accounts "
    "posted recently in an AI-art library. Note standouts, trending models "
    "and techniques. Plain text, a few short paragraphs or bullets, no "
    "preamble, no markdown headers.")


def build_digest(transport: httpx.BaseTransport | None = None) -> dict | None:
    """Summarize recent finds from monitored accounts → {at, text}."""
    with session_scope() as s:
        key, base, model = _settings_call(s)
        handles = [a.handle for a in s.execute(
            select(MonitoredAccount).where(
                MonitoredAccount.active.is_(True))).scalars()]
        if not handles:
            return None
        authors = [f"@{h}" for h in handles]
        posts = s.execute(
            select(Post).where(Post.platform == "x",
                               func.lower(Post.author).in_(authors))
            .order_by(Post.id.desc()).limit(60)).scalars().all()
        if not posts:
            return None
        lines = []
        model_counts: dict[str, int] = {}
        tech_counts: dict[str, int] = {}
        for p in posts:
            if p.model_family:
                model_counts[p.model_family] = model_counts.get(p.model_family, 0) + 1
            for t in (p.technique_tags or []):
                tech_counts[t] = tech_counts.get(t, 0) + 1
            eng = (p.params or {}).get("engagement") or {}
            lines.append(f"- {p.author} [{p.media_type}] "
                         f"model={p.model_family or '?'} "
                         f"likes={eng.get('likes', 0)}: "
                         f"{(p.prompt or '')[:120]}")
    user = (f"{len(lines)} recent posts from {len(handles)} monitored accounts:\n"
            + "\n".join(lines[:50])
            + f"\n\nModel counts: {model_counts}\nTechnique counts: {tech_counts}"
            "\n\nWrite the digest (under 180 words).")
    text = chat(key, base, model,
                [{"role": "system", "content": DIGEST_SYSTEM},
                 {"role": "user", "content": user}],
                max_tokens=500, transport=transport)
    _bump_usage("digest")
    digest = {"at": datetime.now(timezone.utc).isoformat(),
              "text": text.strip()[:4000]}
    with session_scope() as s:
        settings_store.put(s, "grok_last_digest", digest)
        to_discord = settings_store.get(s, "grok_digest_to_discord")
        token = settings_store.get(s, "discord_bot_token")
        channel = settings_store.get(s, "discord_channel_id")
    if to_discord and token and channel:
        try:
            from . import discord_rest
            discord_rest.send_message(token, str(channel), {"embeds": [{
                "title": "PromptForge · Grok digest — your monitored accounts",
                "description": digest["text"][:3900],
                "color": 0xFF6A3D}]})
        except Exception as e:
            bus.warn("grok", f"digest → Discord failed: {e}")
    bus.info("grok", "digest updated")
    return digest


def digest_tick(force: bool = False) -> dict | None:
    with session_scope() as s:
        if not (settings_store.get(s, "grok_digest_enabled")
                and is_configured(s)):
            return None
        hours = max(1, int(settings_store.get(s, "grok_digest_hours") or 24))
        last = settings_store.get(s, "grok_last_digest", None) or {}
    if not force and last.get("at"):
        try:
            last_at = datetime.fromisoformat(last["at"])
            age_h = (datetime.now(timezone.utc) - last_at).total_seconds() / 3600
            if age_h < hours:
                return None
        except ValueError:
            pass
    try:
        return build_digest()
    except GrokError as e:
        bus.error("grok", f"digest failed: {e}")
        return None
