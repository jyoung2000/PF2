"""Run one adapter end-to-end and record its state. Never raises — every
failure lands on the adapter's ScraperState + the log bus. One adapter's
breakage never blocks others (they run through separate calls, serialized by
the scheduler's global lock, D22)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..db import session_scope
from ..logbus import bus
from ..models import ScraperState
from ..pipeline.ingest import IngestStats, ingest_batch
from . import get_adapter


def run_scraper(name: str, limit: int = 100, manual: bool = False) -> IngestStats | None:
    adapter = get_adapter(name)
    src = f"scraper.{name}"
    if adapter is None:
        bus.error(src, "unknown adapter")
        return None

    with session_scope() as s:
        st = adapter.get_state(s)
        if not manual and not st.enabled:
            return None
        if not adapter.is_configured(s):
            reason = adapter.needs_setup_reason(s) or "not configured"
            bus.warn(src, f"skipped — needs setup: {reason}")
            return None
        st.last_status = "running"

    stats = IngestStats()
    client = None
    t0 = time.monotonic()
    try:
        bus.info(src, f"run started (limit {limit})")
        with session_scope() as s:
            client = adapter.make_client(s)
            posts = adapter.fetch_recent(s, client, limit=limit)
        bus.info(src, f"fetched {len(posts)} candidate posts")
        stats = ingest_batch(name, posts, client)
        bus.info(src, f"done — {stats.new} new, {stats.duplicates} dupes, "
                      f"{stats.skipped} skipped, {stats.errors} errors")
        with session_scope() as s:
            st = s.get(ScraperState, name)
            st.last_run_at = datetime.now(timezone.utc)
            st.last_status = "ok" if stats.errors < max(1, stats.found) else "error"
            st.last_error = stats.error_messages[-1] if stats.error_messages else None
            st.last_found = stats.found
            st.last_new = stats.new
            from ..intel import sources
            sources.record_run(s, name, stats, time.monotonic() - t0)
    except Exception as e:
        bus.error(src, f"run failed: {type(e).__name__}: {e}")
        with session_scope() as s:
            st = s.get(ScraperState, name)
            if st is not None:
                st.last_run_at = datetime.now(timezone.utc)
                st.last_status = "error"
                st.last_error = f"{type(e).__name__}: {e}"
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return stats
