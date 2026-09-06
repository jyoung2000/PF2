"""Workflow learning + self-healing (Inspiration 2.0, spec §34–§35, §66).

Life of a workflow:
  discover (Stagehand observation / hand-written)  →  validate (policy)
  →  save v1  →  replay deterministically (playwright_engine) every run
  →  site changes, replay fails  →  status "broken"  →  repair (AI engine
  proposes a new action list against the live page)  →  validate  →
  verify (one replay must succeed)  →  save v2, v1 becomes "superseded".

Nothing here calls an LLM directly — repair goes through the facade
(base.repair_workflow) which picks an AI engine, respects budgets and can be
disabled; a broken workflow with repair unavailable surfaces as "needs
attention" in the GUI, never as silent failure.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..logbus import bus
from ..models import BrowserWorkflow
from . import diagnostics, playwright_engine, policy


def get_active(s: Session, source: str, task: str) -> BrowserWorkflow | None:
    return s.execute(select(BrowserWorkflow).where(
        BrowserWorkflow.source == source, BrowserWorkflow.task == task,
        BrowserWorkflow.status == "active")
        .order_by(BrowserWorkflow.version.desc())).scalars().first()


def list_workflows(s: Session, source: str | None = None) -> list[BrowserWorkflow]:
    stmt = select(BrowserWorkflow).order_by(BrowserWorkflow.source, BrowserWorkflow.task,
                                            BrowserWorkflow.version.desc())
    if source:
        stmt = stmt.where(BrowserWorkflow.source == source)
    return list(s.execute(stmt).scalars())


def save_version(s: Session, source: str, task: str, actions: list[dict],
                 engine: str, schema: dict | None = None,
                 notes: str | None = None, repaired: bool = False) -> BrowserWorkflow:
    """Validate + store a new version; the previous active one is superseded
    (kept for history, spec §35)."""
    policy.check_workflow_actions(actions)
    prev = get_active(s, source, task)
    if prev is not None:
        prev.status = "superseded"
    latest = s.execute(select(BrowserWorkflow.version).where(
        BrowserWorkflow.source == source, BrowserWorkflow.task == task)
        .order_by(BrowserWorkflow.version.desc()).limit(1)).scalar()
    version = (latest or 0) + 1
    wf = BrowserWorkflow(source=source, task=task, version=version, status="active",
                         engine=engine, actions=actions, schema=schema or {},
                         notes=notes,
                         last_repaired=datetime.now(timezone.utc) if repaired else None)
    s.add(wf)
    s.flush()
    bus.info("browserintel", f"{source}/{task}: workflow v{version} saved "
                             f"({'repaired by ' if repaired else 'from '}{engine})")
    return wf


def mark_result(workflow_id: int, ok: bool, error: str | None = None,
                broken: bool = False) -> None:
    with session_scope() as s:
        wf = s.get(BrowserWorkflow, workflow_id)
        if wf is None:
            return
        now = datetime.now(timezone.utc)
        if ok:
            wf.success_count += 1
            wf.last_success = now
            wf.last_error = None
        else:
            wf.failure_count += 1
            wf.last_failure = now
            wf.last_error = policy.sanitize_text(error or "")[:500]
            if broken and wf.status == "active":
                wf.status = "broken"


def replay(workflow_id: int, params: dict | None = None,
           storage_state: str | None = None) -> dict:
    """Run one stored workflow deterministically. Success/failure lands on
    the row; failures also record a sanitized diagnostic. Raises the original
    error so the caller can decide about repair."""
    with session_scope() as s:
        wf = s.get(BrowserWorkflow, workflow_id)
        if wf is None:
            raise ValueError(f"No workflow {workflow_id}")
        actions = list(wf.actions or [])
        source, task = wf.source, wf.task
    try:
        result = playwright_engine.run_actions(actions, params, storage_state)
    except policy.PolicyViolation:
        mark_result(workflow_id, ok=False, error="policy violation", broken=True)
        raise
    except Exception as e:
        mark_result(workflow_id, ok=False, error=str(e), broken=True)
        diagnostics.record(source, task, step="replay", error=str(e),
                           extra={"workflow_id": workflow_id, "params": params})
        raise
    if not result.get("rows") and any(a.get("op") == "extract" for a in actions):
        # navigated fine but extracted nothing — the site likely changed shape
        mark_result(workflow_id, ok=False, error="extraction returned no rows", broken=True)
        diagnostics.record(source, task, step="extract-empty", error="no rows",
                           extra={"workflow_id": workflow_id, "final_url": result.get("final_url")})
        raise RuntimeError(f"{source}/{task}: workflow replay extracted nothing "
                           "(site layout may have changed)")
    mark_result(workflow_id, ok=True)
    return result


def workflow_dict(wf: BrowserWorkflow) -> dict:
    health = "healthy"
    if wf.status == "broken":
        health = "needs_repair"
    elif wf.status == "disabled":
        health = "disabled"
    elif wf.status == "superseded":
        health = "superseded"
    elif wf.failure_count > wf.success_count and wf.failure_count > 0:
        health = "unreliable"
    return {"id": wf.id, "source": wf.source, "task": wf.task, "version": wf.version,
            "status": wf.status, "health": health, "engine": wf.engine,
            "actions": wf.actions or [], "schema": wf.schema or {}, "notes": wf.notes,
            "success_count": wf.success_count, "failure_count": wf.failure_count,
            "last_success": wf.last_success.isoformat() if wf.last_success else None,
            "last_failure": wf.last_failure.isoformat() if wf.last_failure else None,
            "last_error": wf.last_error,
            "last_repaired": wf.last_repaired.isoformat() if wf.last_repaired else None,
            "created_at": wf.created_at.isoformat() if wf.created_at else None}
