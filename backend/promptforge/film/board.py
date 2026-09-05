"""Backlot-style production board (spec F): stage status derived from REAL
project state (scenes, assets, shots, takes, gates, jobs, events) — never a
fake progress animation. Replay reads the event log back in order."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events, gates
from . import projects as proj_svc
from .models import FilmAsset, FilmJob, FilmProject, FilmTake

STAGES = ["concept", "story", "assets", "storyboard", "asset_approval", "shot_generation",
          "audio", "edit", "qa", "export"]
LABELS = {"concept": "Concept", "story": "Story", "assets": "Assets", "storyboard": "Storyboard",
          "asset_approval": "Asset approval", "shot_generation": "Shot generation", "audio": "Audio",
          "edit": "Edit", "qa": "QA", "export": "Export"}


def _stage(key: str, status: str, current: str | None = None, done: int = 0, total: int = 0,
           failures: int = 0, waiting: list | None = None, cost: dict | None = None,
           detail: str | None = None) -> dict:
    return {"key": key, "label": LABELS[key], "status": status, "current": current,
            "progress": {"done": done, "total": total}, "failures": failures,
            "waiting": waiting or [], "cost": cost or {}, "detail": detail}


def board(s: Session, project: FilmProject) -> dict:
    gate_map = {(g["kind"], g["scene_id"]): g for g in gates.list_gates(s, project)}
    scenes = proj_svc.scenes_of(s, project.id)
    shots = [sh for sh, _ in proj_svc.ordered_shots(s, project.id)]
    takes = list(s.execute(select(FilmTake).where(FilmTake.project_id == project.id)).scalars())
    jobs = list(s.execute(select(FilmJob).where(FilmJob.project_id == project.id)
                          .order_by(FilmJob.id.desc()).limit(50)).scalars())
    running = [j for j in jobs if j.status in ("running", "queued", "paused")]
    plan_gate = gate_map[("plan", None)]
    stages: list[dict] = []

    has_concept = bool(project.logline or project.synopsis or project.script or project.plan)
    stages.append(_stage("concept", "done" if plan_gate["status"] == "approved" else
                         ("waiting_approval" if (project.plan and not plan_gate["status"] == "approved")
                          else ("in_progress" if has_concept else "todo")),
                         waiting=(["Production plan approval"] if project.plan and plan_gate["status"] != "approved" else []),
                         detail=(project.plan or {}).get("objective")))
    stages.append(_stage("story", "done" if scenes else ("in_progress" if project.script or project.synopsis else "todo"),
                         done=len(scenes), total=len(scenes),
                         detail=f"{len(scenes)} scene(s), {len(shots)} shot(s)" if scenes else None))

    used = gates._project_assets(s, project)
    assets = [s.get(FilmAsset, aid) for aid in used]
    assets = [a for a in assets if a is not None]
    approved_assets = [a for a in assets if a.approved]
    stages.append(_stage("assets", "done" if assets and len(approved_assets) == len(assets) else
                         ("in_progress" if assets else ("todo" if not scenes else "in_progress")),
                         done=len(approved_assets), total=len(assets),
                         detail=", ".join(a.name for a in assets[:6]) or None))

    framed = [sh for sh in shots if (sh.overrides or {}).get("shot_type") or (sh.overrides or {}).get("camera")
              or (sh.overrides or {}).get("action")]
    sb_gate = gate_map[("storyboard", None)]
    stages.append(_stage("storyboard", "done" if sb_gate["status"] == "approved" and not sb_gate["stale"] else
                         ("waiting_approval" if shots and len(framed) == len(shots) else
                          ("in_progress" if shots else "todo")),
                         done=len(framed), total=len(shots),
                         waiting=(["Storyboard / contact sheet approval"] if shots and sb_gate["status"] != "approved" else []),
                         detail=("approved (stale — shots changed since)" if sb_gate["stale"] else None)))
    ag = gate_map[("assets", None)]
    stages.append(_stage("asset_approval", "done" if ag["status"] == "approved" and not ag["stale"] else
                         ("waiting_approval" if assets else "todo"),
                         done=len(approved_assets), total=len(assets),
                         waiting=([f"{a.name}" for a in assets if not a.approved][:8])))

    by_shot: dict[int, list[FilmTake]] = {}
    for t in takes:
        by_shot.setdefault(t.shot_id, []).append(t)
    generated = [sh for sh in shots if sh.selected_take_id and any(
        t.id == sh.selected_take_id and t.status in ("succeeded", "imported") for t in by_shot.get(sh.id, []))]
    active = [t for t in takes if t.status in ("queued", "running")]
    failed = [t for t in takes if t.status == "failed"]
    est = round(sum(float(t.cost_estimate or 0) for t in takes), 4)
    act = round(sum(float(t.cost_actual or 0) for t in takes if t.cost_actual is not None), 4)
    current = None
    if active:
        sh = next((x for x in shots if x.id == active[0].shot_id), None)
        current = f"Shot {sh.position + 1}" if sh else f"take {active[0].id}"
    stages.append(_stage("shot_generation",
                         "in_progress" if active else ("done" if shots and len(generated) == len(shots) else
                                                       ("failed" if failed and not generated else
                                                        ("in_progress" if generated else "todo"))),
                         current=current, done=len(generated), total=len(shots), failures=len(failed),
                         cost={"estimated_usd": est, "actual_usd": act},
                         detail=f"{len(takes)} take(s)" if takes else None))
    audio_tracks = _count_audio(s, project)
    stages.append(_stage("audio", "done" if audio_tracks else "todo", done=audio_tracks, total=audio_tracks,
                         detail=f"{audio_tracks} track(s)" if audio_tracks else "no audio tracks yet"))
    rough = [gate_map.get(("rough_cut", sc.id)) for sc in scenes]
    rough_ok = [g for g in rough if g and g["status"] == "approved"]
    stages.append(_stage("edit", "done" if scenes and len(rough_ok) == len(scenes) else
                         ("in_progress" if generated else "todo"), done=len(rough_ok), total=len(scenes),
                         waiting=[f"Scene {sc.position + 1} rough cut" for sc, g in zip(scenes, rough)
                                  if g and g["status"] != "approved" and generated][:6]))
    qa_gate = gate_map[("qa", None)]
    qa_fail = [sh for sh in shots if (sh.qa or {}).get("verdict") == "FAIL"]
    qa_done = [sh for sh in shots if sh.qa]
    stages.append(_stage("qa", "done" if qa_gate["status"] == "approved" else
                         ("failed" if qa_fail else ("in_progress" if qa_done else "todo")),
                         done=len(qa_done), total=len(shots), failures=len(qa_fail),
                         waiting=(["Final QA approval"] if qa_done and qa_gate["status"] != "approved" else [])))
    export_jobs = [j for j in jobs if j.kind == "export"]
    ex = export_jobs[0] if export_jobs else None
    stages.append(_stage("export", "done" if ex and ex.status == "done" else
                         ("in_progress" if ex and ex.status in ("queued", "running") else
                          ("failed" if ex and ex.status == "failed" else "todo")),
                         current=(ex.progress or {}).get("current") if ex else None,
                         detail=(ex.result or {}).get("path") if ex and ex.result else None))

    return {"project_id": project.id, "stages": stages,
            "jobs": [job_dict(j) for j in running[:10]],
            "cost": {"estimated_usd": est, "actual_usd": act,
                     "budget": (proj_svc.merge_settings(project.settings, None).get("budget"))},
            "recent_events": events.list_events(s, project.id, limit=12)}


def _count_audio(s: Session, project: FilmProject) -> int:
    try:
        from .models import FilmAudioTrack
    except ImportError:
        return 0
    return len(list(s.execute(select(FilmAudioTrack.id).where(FilmAudioTrack.project_id == project.id))))


def job_dict(j: FilmJob) -> dict:
    return {"id": j.id, "project_id": j.project_id, "kind": j.kind, "status": j.status, "stage": j.stage,
            "progress": j.progress or {}, "checkpoint": j.checkpoint or {}, "payload": j.payload or {},
            "result": j.result, "error": j.error,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None}


def replay(s: Session, project: FilmProject, limit: int = 500) -> dict:
    """Recorded events in order — replay shows exactly what was logged."""
    evs = events.list_events(s, project.id, limit=limit, ascending=True)
    return {"project_id": project.id, "events": evs, "count": len(evs)}
