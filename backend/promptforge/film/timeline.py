"""TimelineService (spec L, AB, §23): scene gaps (project default, per-scene
override, apply-all/reset) kept separate from editorial transitions,
timecode recalculation, runtime. Pure functions over the stored structure —
export (S3) renders exactly what this reports."""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import events
from . import projects as proj_svc
from .models import FilmProject, FilmScene

OVERLAP_KINDS = ("dissolve", "wipe")


def format_tc(seconds: float | None) -> str:
    s = max(0.0, float(seconds or 0.0))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:04.1f}"


def scene_gap(settings: dict, scene: FilmScene) -> tuple[float, bool]:
    """(gap seconds, inherited?) — None on the scene means the project default."""
    default = float(settings.get("default_scene_gap_s", 0.5))
    if scene.gap_after_s is None:
        return default, True
    return float(scene.gap_after_s), False


def _overlap(transition: dict | None, gap: float) -> float:
    if not transition or transition.get("kind") not in OVERLAP_KINDS:
        return 0.0
    if gap > 0:
        return 0.0          # a gap means black/silence between — nothing to cross-fade into
    return float(transition.get("duration_s") or 0.0)


def compute(s: Session, project: FilmProject) -> dict:
    settings = proj_svc.merge_settings(project.settings, None)
    default_tr = settings.get("default_transition") or {"kind": "cut", "duration_s": 0.0}
    scenes = proj_svc.scenes_of(s, project.id)
    t = 0.0
    out_scenes = []
    total_shots = 0
    for i, sc in enumerate(scenes):
        shots = proj_svc.shots_of(s, sc.id)
        scene_start = t
        out_shots = []
        for j, sh in enumerate(shots):
            start = t
            end = start + float(sh.duration_s or 0)
            tr = sh.transition or (default_tr if j < len(shots) - 1 else None)
            is_last = j == len(shots) - 1
            out_shots.append({"id": sh.id, "label": f"{sc.position + 1}.{sh.position + 1}",
                              "title": sh.title, "start_s": round(start, 3), "end_s": round(end, 3),
                              "duration_s": float(sh.duration_s or 0), "status": sh.status,
                              "media_strategy": sh.media_strategy,
                              "transition": tr if not is_last else None,
                              "tc_in": format_tc(start), "tc_out": format_tc(end)})
            t = end
            if not is_last:
                t -= _overlap(tr, 0.0)
        total_shots += len(shots)
        scene_end = t
        gap, inherited = scene_gap(settings, sc)
        last = i == len(scenes) - 1
        tr = sc.transition or (default_tr if not last else None)
        out_scenes.append({"id": sc.id, "number": sc.position + 1, "title": sc.title,
                           "start_s": round(scene_start, 3), "end_s": round(scene_end, 3),
                           "duration_s": round(scene_end - scene_start, 3),
                           "tc_in": format_tc(scene_start), "tc_out": format_tc(scene_end),
                           "gap_after_s": None if last else gap, "gap_inherited": inherited,
                           "transition": tr if not last else None, "shot_count": len(shots),
                           "shots": out_shots, "approved": bool(sc.approved)})
        if not last:
            t = scene_end + gap - _overlap(tr, gap)
    runtime = t
    return {"project_id": project.id, "runtime_s": round(runtime, 3), "runtime_tc": format_tc(runtime),
            "target_runtime_s": settings.get("target_runtime_s"),
            "target_tc": format_tc(settings.get("target_runtime_s")),
            "default_scene_gap_s": settings.get("default_scene_gap_s"),
            "default_transition": default_tr, "fps": settings.get("fps"),
            "scene_count": len(scenes), "shot_count": total_shots, "scenes": out_scenes}


def set_default_gap(s: Session, project: FilmProject, gap_s: float, reset_overrides: bool = False) -> dict:
    proj_svc.update_project(s, project, settings={"default_scene_gap_s": gap_s})
    if reset_overrides:
        for sc in proj_svc.scenes_of(s, project.id):
            sc.gap_after_s = None
    s.flush()
    events.log(s, project.id, f"Default scene gap set to {gap_s}s", kind="edit", stage="storyboard",
               entity=("project", project.id), data={"gap_s": gap_s, "reset_overrides": reset_overrides})
    return compute(s, project)


def apply_gap_to_all(s: Session, project: FilmProject, gap_s: float) -> dict:
    """Explicit per-scene override on every scene (spec L: 'Apply this gap
    to all scenes')."""
    for sc in proj_svc.scenes_of(s, project.id):
        sc.gap_after_s = float(gap_s)
    s.flush()
    events.log(s, project.id, f"Gap {gap_s}s applied to all scenes", kind="edit", stage="storyboard",
               entity=("project", project.id), data={"gap_s": gap_s})
    return compute(s, project)


def set_scene_gap(s: Session, scene: FilmScene, gap_s: float | None) -> dict:
    proj_svc.update_scene(s, scene, gap_after_s=gap_s)
    project = s.get(FilmProject, scene.project_id)
    events.log(s, scene.project_id,
               (f"Scene {scene.position + 1} gap reset to default" if gap_s is None
                else f"Scene {scene.position + 1} gap overridden to {gap_s}s"),
               kind="edit", stage="storyboard", entity=("scene", scene.id), data={"gap_s": gap_s})
    return compute(s, project)
