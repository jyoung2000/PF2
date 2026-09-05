"""Resumable jobs (spec Y, F): long-running film work (director batches,
sample runs, exports, analyses) runs in a background thread, checkpoints
every finished item into `film_jobs.checkpoint`, and can be paused,
resumed and cancelled. A restart or a provider failure never redoes items
that already completed. Handlers are registered per kind and must be
idempotent over `checkpoint["done"]`."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..logbus import bus
from . import events
from .models import FilmJob

Handler = Callable[[int], dict | None]
_handlers: dict[str, Handler] = {}
_threads: dict[int, threading.Thread] = {}
_lock = threading.Lock()


class StopRequested(Exception):
    """Raised inside handlers by `check_stop` when paused/cancelled."""


def register(kind: str, fn: Handler) -> None:
    _handlers[kind] = fn


def create(s: Session, project_id: int | None, kind: str, payload: dict | None = None,
           total: int | None = None, stage: str | None = None) -> FilmJob:
    j = FilmJob(project_id=project_id, kind=kind, status="queued", stage=stage,
                payload=payload or {}, progress={"done": 0, "total": total or 0, "current": None},
                checkpoint={"done": []})
    s.add(j)
    s.flush()
    return j


def get(s: Session, job_id: int) -> FilmJob | None:
    return s.get(FilmJob, job_id)


# ------------------------------------------------------------ checkpointing -
def checkpoint(job_id: int, item_id, current: str | None = None, extra: dict | None = None) -> None:
    """Record one finished item (idempotent) and refresh progress."""
    with session_scope() as s:
        j = s.get(FilmJob, job_id)
        if j is None:
            return
        cp = dict(j.checkpoint or {})
        done = list(cp.get("done", []))
        if item_id is not None and item_id not in done:
            done.append(item_id)
        cp["done"] = done
        if extra:
            cp.update(extra)
        j.checkpoint = cp
        prog = dict(j.progress or {})
        prog["done"] = len(done)
        prog["current"] = current
        j.progress = prog


def set_progress(job_id: int, current: str | None = None, total: int | None = None) -> None:
    with session_scope() as s:
        j = s.get(FilmJob, job_id)
        if j is None:
            return
        prog = dict(j.progress or {})
        if current is not None:
            prog["current"] = current
        if total is not None:
            prog["total"] = total
        j.progress = prog


def done_items(job_id: int) -> list:
    with session_scope() as s:
        j = s.get(FilmJob, job_id)
        return list((j.checkpoint or {}).get("done", [])) if j else []


def check_stop(job_id: int) -> None:
    with session_scope() as s:
        j = s.get(FilmJob, job_id)
        if j is None or j.status in ("paused", "cancelled"):
            raise StopRequested(j.status if j else "gone")


# ----------------------------------------------------------------- running -
def run(job_id: int) -> str:
    """Execute a job synchronously (the thread target; tests call it directly).
    Returns the final status."""
    with session_scope() as s:
        j = s.get(FilmJob, job_id)
        if j is None:
            return "gone"
        if j.status in ("done", "cancelled"):
            return j.status
        kind, project_id = j.kind, j.project_id
        handler = _handlers.get(kind)
        if handler is None:
            j.status = "failed"
            j.error = f"no handler for job kind {kind!r}"
            j.finished_at = datetime.now(timezone.utc)
            return "failed"
        j.status = "running"
        j.error = None
    try:
        result = handler(job_id)
    except StopRequested as e:
        with session_scope() as s:
            j = s.get(FilmJob, job_id)
            if j is not None and j.status == "running":
                j.status = str(e) if str(e) in ("paused", "cancelled") else "paused"
            status = j.status if j else "paused"
        bus.info("film", f"job {job_id} {status}")
        return status
    except Exception as e:  # noqa: BLE001 — a failed job must surface, not crash the runner
        with session_scope() as s:
            j = s.get(FilmJob, job_id)
            if j is not None:
                j.status = "failed"
                j.error = f"{type(e).__name__}: {e}"[:1000]
                j.finished_at = datetime.now(timezone.utc)
            events.log(s, project_id, f"{kind} job failed", kind="checkpoint", actor="system",
                       reason=str(e)[:500], entity=("job", job_id))
        bus.error("film", f"job {job_id} ({kind}) failed: {e}")
        return "failed"
    with session_scope() as s:
        j = s.get(FilmJob, job_id)
        if j is not None and j.status == "running":
            j.status = "done"
            j.result = result if isinstance(result, dict) else (j.result or {})
            j.finished_at = datetime.now(timezone.utc)
            prog = dict(j.progress or {})
            prog["current"] = None
            j.progress = prog
        events.log(s, project_id, f"{kind} job finished", kind="checkpoint", actor="system",
                   entity=("job", job_id), data={"result_keys": sorted((result or {}).keys())
                                                 if isinstance(result, dict) else []})
    return "done"


def start(job_id: int, inline: bool = False) -> None:
    """Run in a daemon thread (or inline for tests / tiny jobs)."""
    if inline:
        run(job_id)
        return
    with _lock:
        t = _threads.get(job_id)
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=run, args=(job_id,), daemon=True, name=f"film-job-{job_id}")
        _threads[job_id] = t
        t.start()


def pause(s: Session, job: FilmJob) -> FilmJob:
    if job.status in ("queued", "running"):
        job.status = "paused"
        s.flush()
    return job


def resume(s: Session, job: FilmJob, inline: bool = False) -> FilmJob:
    """Continue from the checkpoint: the handler skips `checkpoint.done`."""
    if job.status in ("paused", "failed", "queued"):
        job.status = "queued"
        job.error = None
        s.flush()
        s.commit()
        start(job.id, inline=inline)
    return job


def cancel(s: Session, job: FilmJob) -> FilmJob:
    if job.status not in ("done",):
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        s.flush()
    return job


def recover_on_boot() -> int:
    """Jobs left 'running' by a previous process are re-queued (their
    checkpoints make the retry cheap)."""
    n = 0
    with session_scope() as s:
        for j in s.execute(select(FilmJob).where(FilmJob.status == "running")).scalars():
            j.status = "queued"
            n += 1
    return n


def tick() -> int:
    """Scheduler entry: start queued jobs that nobody is running."""
    with session_scope() as s:
        ids = [j.id for j in s.execute(select(FilmJob).where(FilmJob.status == "queued")
                                       .order_by(FilmJob.id.asc())).scalars()]
    started = 0
    for jid in ids:
        t = _threads.get(jid)
        if t is None or not t.is_alive():
            start(jid)
            started += 1
    return started
