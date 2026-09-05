"""Central staged pipeline queue (D63) on the existing SQLite + APScheduler.

Stages: enrich (detail/author/comments/media variants) → analysis (LLM/VLM,
budget-gated) → knowledge. Handlers register per stage; a handler returns
"complete"/"skipped", raises Deferred to leave the job queued untouched
(budget exhausted, provider offline), or raises anything else to record a
failure (retryable with backoff until max_attempts)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import func, select

from .. import settings_store
from ..db import session_scope
from ..logbus import bus
from ..models import PipelineJob

STAGES = ("enrich", "analysis", "knowledge")
STATES = ("queued", "processing", "complete", "skipped", "failed", "retryable")
RETRY_BACKOFF = timedelta(minutes=10)

Handler = Callable[[int | None, dict], str | None]
_handlers: dict[str, Handler] = {}


class Deferred(Exception):
    """Leave the job queued without counting an attempt."""


def register(stage: str, fn: Handler) -> None:
    _handlers[stage] = fn


def ensure_handlers() -> None:
    """Import the stage modules (they self-register). Missing modules are
    fine — their stages simply stay queued."""
    for mod in ("analysis", "enrichment"):
        try:
            __import__(f"promptforge.intel.{mod}")
        except ImportError:
            pass


def handlers() -> dict[str, Handler]:
    return dict(_handlers)


def enqueue(s, post_id: int | None, stage: str, priority: float = 0.0,
            payload: dict | None = None, cost_estimate: float | None = None) -> PipelineJob:
    """Idempotent per (post, stage) while pending: re-enqueue bumps priority."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage}")
    existing = s.execute(select(PipelineJob).where(
        PipelineJob.post_id == post_id, PipelineJob.stage == stage,
        PipelineJob.state.in_(("queued", "retryable", "processing")))).scalars().first()
    if existing:
        existing.priority = max(existing.priority or 0, priority)
        if payload:
            existing.payload = {**(existing.payload or {}), **payload}
        s.flush()
        return existing
    job = PipelineJob(post_id=post_id, stage=stage, priority=priority,
                      payload=payload or {}, cost_estimate=cost_estimate)
    s.add(job)
    s.flush()
    return job


def claim_next(s, stages: tuple[str, ...] | None = None) -> PipelineJob | None:
    now = datetime.now(timezone.utc)
    stmt = select(PipelineJob).where(PipelineJob.state.in_(("queued", "retryable")))
    if stages:
        stmt = stmt.where(PipelineJob.stage.in_(stages))
    stmt = stmt.order_by(PipelineJob.priority.desc(), PipelineJob.id.asc())
    for job in s.execute(stmt).scalars():
        if job.state == "retryable":
            ts = job.updated_at
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts and now - ts < RETRY_BACKOFF:
                continue
        if job.stage not in _handlers:
            continue  # nothing can run it yet — leave it queued
        job.state = "processing"
        job.started_at = now
        s.flush()
        return job
    return None


def _finish(s, job: PipelineJob, state: str, error: str | None = None) -> None:
    job.state = state
    job.error = error
    job.finished_at = datetime.now(timezone.utc)
    s.flush()


def process_one(stages: tuple[str, ...] | None = None) -> str | None:
    """Claim + run one job in its own transaction. Returns final state."""
    with session_scope() as s:
        job = claim_next(s, stages)
        if job is None:
            return None
        job_id, post_id, stage, payload = job.id, job.post_id, job.stage, dict(job.payload or {})
    handler = _handlers[stage]
    try:
        result = handler(post_id, payload) or "complete"
    except Deferred:
        with session_scope() as s:
            job = s.get(PipelineJob, job_id)
            job.state = "queued"
            job.started_at = None
            s.flush()
        return "deferred"
    except Exception as e:  # noqa: BLE001 — any handler failure is recorded, never raised
        with session_scope() as s:
            job = s.get(PipelineJob, job_id)
            job.attempts = (job.attempts or 0) + 1
            state = "retryable" if job.attempts < (job.max_attempts or 3) else "failed"
            _finish(s, job, state, f"{type(e).__name__}: {e}")
            if state == "failed":
                bus.error("intel", f"{stage} job {job_id} (post {post_id}) failed: {e}")
        return state
    with session_scope() as s:
        job = s.get(PipelineJob, job_id)
        _finish(s, job, "skipped" if result == "skipped" else "complete")
    return "skipped" if result == "skipped" else "complete"


def tick(max_jobs: int | None = None) -> dict:
    """Scheduler entry: drain up to N jobs; stops early when a stage defers."""
    ensure_handlers()
    if max_jobs is None:
        with session_scope() as s:
            max_jobs = int(settings_store.get(s, "intel_queue_batch") or 20)
    counts: dict[str, int] = defaultdict(int)
    deferred_stages: set[str] = set()
    for _ in range(max_jobs):
        stages = tuple(st for st in STAGES if st not in deferred_stages) or None
        if deferred_stages and not stages:
            break
        with session_scope() as s:
            peek = claim_preview(s, stages)
        if peek is None:
            break
        state = process_one(stages)
        if state is None:
            break
        counts[state] += 1
        if state == "deferred":
            deferred_stages.add(peek)
    return dict(counts)


def claim_preview(s, stages: tuple[str, ...] | None = None) -> str | None:
    """Stage of the next runnable job, without claiming it."""
    stmt = select(PipelineJob.stage, PipelineJob.state, PipelineJob.updated_at).where(
        PipelineJob.state.in_(("queued", "retryable")))
    if stages:
        stmt = stmt.where(PipelineJob.stage.in_(stages))
    stmt = stmt.order_by(PipelineJob.priority.desc(), PipelineJob.id.asc())
    now = datetime.now(timezone.utc)
    for stage, state, ts in s.execute(stmt):
        if stage not in _handlers:
            continue
        if state == "retryable" and ts:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if now - ts < RETRY_BACKOFF:
                continue
        return stage
    return None


def stats(s) -> dict:
    rows = s.execute(select(PipelineJob.stage, PipelineJob.state, func.count())
                     .group_by(PipelineJob.stage, PipelineJob.state)).all()
    out: dict[str, dict[str, int]] = {st: {} for st in STAGES}
    for stage, state, n in rows:
        out.setdefault(stage, {})[state] = n
    errors = s.execute(select(PipelineJob).where(PipelineJob.state.in_(("failed", "retryable")))
                       .order_by(PipelineJob.updated_at.desc()).limit(25)).scalars().all()
    return {"stages": out,
            "errors": [{"id": j.id, "post_id": j.post_id, "stage": j.stage, "state": j.state,
                        "attempts": j.attempts, "error": j.error} for j in errors],
            "pending": sum(n for st in out.values() for k, n in st.items()
                           if k in ("queued", "retryable", "processing"))}


def retry(s, job_ids: list[int] | None = None) -> int:
    stmt = select(PipelineJob).where(PipelineJob.state.in_(("failed", "retryable")))
    if job_ids:
        stmt = stmt.where(PipelineJob.id.in_(job_ids))
    n = 0
    for job in s.execute(stmt).scalars():
        job.state, job.attempts, job.error = "queued", 0, None
        n += 1
    s.flush()
    return n


def clear(s, states: tuple[str, ...] = ("complete", "skipped")) -> int:
    jobs = s.execute(select(PipelineJob).where(PipelineJob.state.in_(states))).scalars().all()
    for j in jobs:
        s.delete(j)
    s.flush()
    return len(jobs)
