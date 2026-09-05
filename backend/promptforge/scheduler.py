"""APScheduler wiring (3.6): one interval job per enabled adapter, all runs
serialized through a single global lock (D22 — one site at a time, Chromium
only alive during a browser run). Also hosts the hourly learning pass and the
Discord digest job once those phases land."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from .db import session_scope
from .logbus import bus
from .scrapers import all_adapters

_scheduler: BackgroundScheduler | None = None
_run_lock = threading.Lock()


def _locked_run(name: str, manual: bool = False) -> None:
    from .scrapers.runner import run_scraper
    with _run_lock:
        run_scraper(name, manual=manual)


def _job_id(name: str) -> str:
    return f"scrape:{name}"


def start() -> None:
    global _scheduler
    import os
    if os.environ.get("PF_DISABLE_SCHEDULER") == "1":
        return
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    with session_scope() as s:
        for adapter in all_adapters().values():
            st = adapter.get_state(s)
            _scheduler.add_job(
                _locked_run, "interval",
                minutes=max(adapter.min_interval_minutes, st.interval_minutes),
                args=[adapter.name], id=_job_id(adapter.name),
                max_instances=1, coalesce=True)
    try:
        from .knowledge import engine as kengine
        _scheduler.add_job(kengine.scheduled_learning_pass, "interval",
                           minutes=60, id="learning", max_instances=1, coalesce=True)
    except ImportError:
        pass
    try:
        from .integrations import discord_rules
        _scheduler.add_job(discord_rules.digest_tick, "interval",
                           minutes=15, id="discord_digest", max_instances=1,
                           coalesce=True)
    except ImportError:
        pass
    try:
        from . import monitoring
        _scheduler.add_job(monitoring.monitor_tick, "interval",
                           minutes=2, id="monitoring", max_instances=1,
                           coalesce=True)
    except ImportError:
        pass
    try:
        from .integrations import grok
        _scheduler.add_job(grok.curate_tick, "interval", minutes=10,
                           id="grok_curate", max_instances=1, coalesce=True)
        _scheduler.add_job(grok.digest_tick, "interval", minutes=30,
                           id="grok_digest", max_instances=1, coalesce=True)
    except ImportError:
        pass
    try:
        from .companion import manager as companion_manager
        _scheduler.add_job(companion_manager.drain_job_queue, "interval",
                           minutes=2, id="llm_jobs", max_instances=1, coalesce=True)
    except ImportError:
        pass
    try:
        from .intel import clusters as intel_clusters
        _scheduler.add_job(intel_clusters.rebuild_job, "interval", minutes=30,
                           id="intel_clusters", max_instances=1, coalesce=True)
    except ImportError:
        pass
    try:
        from .intel import queue as intel_queue
        _scheduler.add_job(intel_queue.tick, "interval", minutes=1,
                           id="intel_queue", max_instances=1, coalesce=True)
    except ImportError:
        pass
    _scheduler.start()
    bus.info("system", "scheduler started")


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def reschedule(name: str) -> None:
    if _scheduler is None:
        return
    from .scrapers import get_adapter
    adapter = get_adapter(name)
    if adapter is None:
        return
    with session_scope() as s:
        st = adapter.get_state(s)
        minutes = max(adapter.min_interval_minutes, st.interval_minutes)
    job = _scheduler.get_job(_job_id(name))
    if job is not None:
        _scheduler.reschedule_job(_job_id(name), trigger="interval", minutes=minutes)


def trigger_run(name: str) -> bool:
    """Queue an immediate one-off run (serialized by the global lock)."""
    if _scheduler is None:
        return None  # scheduler not started (tests/dev) — caller runs directly
    _scheduler.add_job(_locked_run, args=[name, True],
                       id=f"manual:{name}:{datetime.now().timestamp()}",
                       max_instances=1)
    return True


def next_run_time(name: str) -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(_job_id(name))
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.astimezone(timezone.utc).isoformat()
