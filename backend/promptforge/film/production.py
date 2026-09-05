"""Production runs (spec AE, F, Y): sample runs (a few representative shots
before bulk generation) and batch generation across scenes/shots, both as
checkpointed film_jobs so a restart or a provider failure never redoes
finished shots. Batches respect the plan/storyboard gates and the budget
mode; single takes remain available at any time (that IS sample mode)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import session_scope
from . import costs, events, gates
from . import jobs as job_svc
from . import projects as proj_svc
from . import scoring, takes
from .models import FilmJob, FilmProject, FilmShot, FilmTake


class GateRequired(ValueError):
    def __init__(self, message: str, missing: list[str]):
        super().__init__(message)
        self.missing = missing


def sample_shots(s: Session, project: FilmProject, scene_id: int | None = None, limit: int = 3) -> list[FilmShot]:
    """Representative shots: an establishing/wide, a character close/medium, the last."""
    ordered = [sh for sh, sc in proj_svc.ordered_shots(s, project.id) if scene_id is None or sc.id == scene_id]
    if not ordered:
        return []
    picks: list[FilmShot] = []

    def st(sh: FilmShot) -> str:
        return (sh.overrides or {}).get("shot_type") or ""

    wide = next((sh for sh in ordered if st(sh) in ("establishing", "wide", "extreme_wide")), ordered[0])
    picks.append(wide)
    close = next((sh for sh in ordered if sh not in picks and st(sh) in ("close_up", "medium_close", "medium", "two_shot")), None)
    if close is not None:
        picks.append(close)
    if ordered[-1] not in picks:
        picks.append(ordered[-1])
    return picks[:limit]


def _estimate_shots(s: Session, project: FilmProject, shots: list[FilmShot], kind: str) -> float | None:
    from .. import settings_store
    family = (settings_store.get(s, "film_video_family" if kind == "video" else "film_image_family") or "kling").lower()
    total = 0.0
    unknown = False
    for sh in shots:
        best, _ = scoring.pick(s, "text_to_video" if kind == "video" else "text_to_image", kind,
                               {"duration_s": min(float(sh.duration_s or 4), takes.MAX_CLIP_S_DEFAULT),
                                "resolution": "720p", "size": "1344x768"}, family)
        if best is None or best["estimate"] is None:
            unknown = True
            continue
        total += best["estimate"]
    return None if unknown and total == 0 else round(total, 4)


def _needs_take(s: Session, sh: FilmShot, kind: str) -> bool:
    t = s.get(FilmTake, sh.selected_take_id) if sh.selected_take_id else None
    if t is not None and t.status in ("succeeded", "imported") and (t.kind == kind or kind == "video" and t.kind in ("footage", "graphics")):
        return False
    return sh.media_strategy not in takes.STRATEGY_TOOL


def start_run(s: Session, project: FilmProject, kind: str = "video", scene_ids: list[int] | None = None,
              shot_ids: list[int] | None = None, sample: bool = False, force: bool = False,
              approve_cost: bool = False, skip_done: bool = True, actor: str = "user") -> FilmJob:
    if sample:
        shots = sample_shots(s, project, (scene_ids or [None])[0])
    else:
        shots = [sh for sh, sc in proj_svc.ordered_shots(s, project.id)
                 if (not scene_ids or sc.id in scene_ids) and (not shot_ids or sh.id in shot_ids)]
        missing = []
        if not force:
            if not gates.is_approved(s, project, "plan"):
                missing.append("plan")
            if not gates.is_approved(s, project, "storyboard"):
                missing.append("storyboard")
        if missing:
            raise GateRequired("Approve the " + " and ".join(gates.LABELS[m].lower() for m in missing)
                               + " before bulk generation (or run with force).", missing)
    if skip_done:
        shots = [sh for sh in shots if _needs_take(s, sh, kind)]
    if not shots:
        raise ValueError("Nothing to generate — every selected shot already has a finished take "
                         "or uses a non-AI media strategy.")
    estimate = _estimate_shots(s, project, shots, kind)
    check = costs.check(s, project, estimate, approve=approve_cost)
    if not check["allowed"]:
        raise costs.BudgetBlocked(check["reason"], check)
    job = job_svc.create(s, project.id, "sample" if sample else "batch_generate",
                         payload={"kind": kind, "shot_ids": [sh.id for sh in shots], "approve_cost": approve_cost,
                                  "estimate_usd": estimate, "check": check},
                         total=len(shots), stage="shot_generation")
    events.log(s, project.id, f"{'Sample' if sample else 'Batch'} run queued: {len(shots)} shot(s), est. "
               f"${estimate:.2f}" if estimate is not None else f"{'Sample' if sample else 'Batch'} run queued: "
               f"{len(shots)} shot(s), price unknown", kind="generation", stage="shot_generation", actor=actor,
               entity=("job", job.id), data={"shot_ids": [sh.id for sh in shots], "estimate_usd": estimate,
                                             "warning": check.get("warning")})
    return job


def _run_handler(job_id: int) -> dict:
    with session_scope() as s:
        j = s.get(FilmJob, job_id)
        payload = dict(j.payload or {})
    kind = payload.get("kind", "video")
    take_ids: list[int] = []
    skipped: list[dict] = []
    for sid in payload.get("shot_ids", []):
        if sid in set(job_svc.done_items(job_id)):
            continue
        job_svc.check_stop(job_id)
        job_svc.set_progress(job_id, current=f"shot {sid}")
        with session_scope() as s:
            sh = s.get(FilmShot, sid)
            if sh is None:
                job_svc.checkpoint(job_id, sid)
                continue
            try:
                t = takes.create_take(s, sh, kind=kind, approve_cost=bool(payload.get("approve_cost")),
                                      actor="director", enqueue=False)
                s.commit()
                from ..generation import queue as gen_queue
                gen_queue.start_worker()
                gen_queue.enqueue(t.generation_id)
                take_ids.append(t.id)
            except (takes.TakeError, costs.BudgetBlocked) as e:
                s.rollback()
                skipped.append({"shot_id": sid, "reason": str(e)})
        job_svc.checkpoint(job_id, sid, extra={"take_ids": take_ids, "skipped": skipped})
    return {"take_ids": take_ids, "skipped": skipped, "kind": kind}


job_svc.register("sample", _run_handler)
job_svc.register("batch_generate", _run_handler)
