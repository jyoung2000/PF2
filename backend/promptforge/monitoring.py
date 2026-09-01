"""Follow-list monitoring (Phase X2, D52): walk active accounts on their
intervals, pull each timeline through the XAdapter (newest first, stopping at
the last_post_id cursor), push finds through the normal pipeline, apply
per-account auto-tag / auto-collection, advance the cursor. One failing
account never blocks the rest."""
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
from .pipeline.ingest import IngestStats, ingest_batch
from .scrapers import get_adapter

HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/(@?[A-Za-z0-9_]{1,15})"
    r"(?:[/?].*)?$", re.I)


def normalize_handle(raw: str) -> str | None:
    """@handle, bare handle, or profile URL → lowercase handle (or None)."""
    raw = (raw or "").strip().rstrip(",;")
    if not raw:
        return None
    m = _URL_RE.match(raw)
    if m:
        raw = m.group(1)
    raw = raw.lstrip("@").strip()
    if not HANDLE_RE.match(raw):
        return None
    if raw.lower() in ("home", "explore", "search", "i", "settings", "messages",
                       "notifications", "login"):
        return None  # reserved X paths pasted by accident
    return raw.lower()


def parse_bulk(text: str) -> tuple[list[str], list[str]]:
    """Bulk paste → (valid handles deduped, rejected raw tokens)."""
    valid: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\s,;]+", text or ""):
        if not token.strip():
            continue
        handle = normalize_handle(token)
        if handle is None:
            rejected.append(token.strip())
        elif handle not in seen:
            seen.add(handle)
            valid.append(handle)
    return valid, rejected


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


def run_account(account_id: int, manual: bool = False) -> IngestStats | None:
    """Poll one monitored account. Never raises; outcome lands on the row."""
    adapter = get_adapter("x")
    src = "monitoring"
    with session_scope() as s:
        account = s.get(MonitoredAccount, account_id)
        if account is None:
            return None
        if not account.active and not manual:
            return None
        handle = account.handle
        since_id = int(account.last_post_id) if account.last_post_id else None
        media_only = account.media_only
        if adapter is None or not adapter.is_configured(s):
            account.status = "error"
            account.last_error = ("X login session missing — click Connect X "
                                  "account (or upload a scripts/capture_login.py "
                                  "x export)")
            account.last_checked = datetime.now(timezone.utc)
            bus.warn(src, f"@{handle}: skipped — no X session")
            return None

    stats: IngestStats | None = None
    client = None
    try:
        bus.info(src, f"@{handle}: polling (cursor {since_id or 'none'})")
        with session_scope() as s:
            client = adapter.make_client(s)
            posts = adapter.fetch_account(s, client, handle,
                                          since_id=since_id,
                                          media_only=media_only)
        stats = ingest_batch("x", posts, client)
        max_id = max((int(str(p.platform_post_id).split("-")[0])
                      for p in posts), default=None)
        with session_scope() as s:
            account = s.get(MonitoredAccount, account_id)
            if account is None:
                return stats
            account.last_checked = datetime.now(timezone.utc)
            account.last_new = stats.new
            account.status = "ok"
            account.last_error = None
            if max_id is not None and (not account.last_post_id
                                       or max_id > int(account.last_post_id)):
                account.last_post_id = str(max_id)
            acct_snapshot = account
        _apply_auto_actions(acct_snapshot, stats.new_ids)
        bus.info(src, f"@{handle}: {stats.new} new, {stats.duplicates} dupes")
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        not_found = "404" in message or "NotFound" in message
        with session_scope() as s:
            account = s.get(MonitoredAccount, account_id)
            if account is not None:
                account.last_checked = datetime.now(timezone.utc)
                account.status = "not_found" if not_found else "error"
                account.last_error = message[:500]
        bus.error(src, f"@{handle}: poll failed — {message}")
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
        with scheduler._run_lock:
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
