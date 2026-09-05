"""Creative approval gates (spec G): plan · assets · storyboard · rough_cut
(per scene) · qa · export. Approval stores a snapshot of exactly what was
approved; rejection invalidates only the artifacts that depend on the
rejected items — nothing unrelated is touched, nothing is deleted."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events
from . import projects as proj_svc
from .models import FilmGate, FilmProject, FilmScene, FilmShot, FilmTake

KINDS = ("plan", "assets", "storyboard", "rough_cut", "qa", "export")
ORDER = {k: i for i, k in enumerate(KINDS)}
LABELS = {"plan": "Production plan", "assets": "Assets", "storyboard": "Storyboard / contact sheet",
          "rough_cut": "Scene rough cut", "qa": "Final QA", "export": "Export"}


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _project_assets(s: Session, project: FilmProject) -> dict[int, int]:
    """asset_id → version_id for every asset the project's scenes/shots use."""
    out: dict[int, int] = {}
    for sh, sc in proj_svc.ordered_shots(s, project.id):
        for e in proj_svc.effective_assets(s, sh, sc):
            out[e["asset_id"]] = e["version_id"]
    for sc in proj_svc.scenes_of(s, project.id):
        for x in (sc.defaults or {}).get("assets", []) or []:
            if isinstance(x, dict) and x.get("asset_id") and x.get("version_id"):
                out.setdefault(int(x["asset_id"]), int(x["version_id"]))
    return out


def snapshot_for(s: Session, project: FilmProject, kind: str, scene_id: int | None = None) -> dict:
    if kind == "plan":
        return {"plan_hash": _h(project.plan or {}), "settings_hash": _h(project.settings or {})}
    if kind == "assets":
        return {"versions": {str(k): v for k, v in _project_assets(s, project).items()}}
    if kind == "storyboard":
        shots = {}
        for sh, sc in proj_svc.ordered_shots(s, project.id):
            shots[str(sh.id)] = _h({"o": sh.overrides, "d": sh.duration_s, "m": sh.media_strategy,
                                    "a": [(e["asset_id"], e["version_id"])
                                          for e in proj_svc.effective_assets(s, sh, sc)]})
        return {"shots": shots}
    if kind == "rough_cut":
        takes = {}
        if scene_id:
            for sh in proj_svc.shots_of(s, scene_id):
                takes[str(sh.id)] = sh.selected_take_id
        return {"scene_id": scene_id, "takes": takes}
    if kind in ("qa", "export"):
        takes = {str(sh.id): sh.selected_take_id for sh, _ in proj_svc.ordered_shots(s, project.id)}
        return {"takes": takes}
    raise ValueError(f"unknown gate {kind!r}")


def _row(s: Session, project_id: int, kind: str, scene_id: int | None) -> FilmGate | None:
    stmt = select(FilmGate).where(FilmGate.project_id == project_id, FilmGate.kind == kind)
    stmt = stmt.where(FilmGate.scene_id == scene_id) if scene_id else stmt.where(FilmGate.scene_id.is_(None))
    return s.execute(stmt).scalar_one_or_none()


def gate_dict(s: Session, project: FilmProject, g: FilmGate | None, kind: str,
              scene_id: int | None = None) -> dict:
    current = snapshot_for(s, project, kind, scene_id)
    status = g.status if g else "pending"
    stale = bool(g and g.status == "approved" and g.snapshot != current)
    return {"kind": kind, "label": LABELS[kind], "scene_id": scene_id, "status": status,
            "stale": stale, "note": g.note if g else None,
            "decided_at": g.decided_at.isoformat() if g and g.decided_at else None,
            "snapshot": g.snapshot if g else None, "current": current,
            "order": ORDER[kind]}


def list_gates(s: Session, project: FilmProject) -> list[dict]:
    out = []
    for kind in KINDS:
        if kind == "rough_cut":
            for sc in proj_svc.scenes_of(s, project.id):
                out.append(gate_dict(s, project, _row(s, project.id, kind, sc.id), kind, sc.id))
        else:
            out.append(gate_dict(s, project, _row(s, project.id, kind, None), kind))
    return out


def is_approved(s: Session, project: FilmProject, kind: str, scene_id: int | None = None,
                allow_stale: bool = True) -> bool:
    g = _row(s, project.id, kind, scene_id)
    if g is None or g.status != "approved":
        return False
    return allow_stale or g.snapshot == snapshot_for(s, project, kind, scene_id)


def decide(s: Session, project: FilmProject, kind: str, status: str, scene_id: int | None = None,
           note: str | None = None, item_ids: list[int] | None = None, actor: str = "user") -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown gate {kind!r}")
    if status not in ("approved", "rejected", "pending"):
        raise ValueError("status must be approved | rejected | pending")
    if kind == "rough_cut" and not scene_id:
        raise ValueError("rough_cut gates are per scene (scene_id required)")
    g = _row(s, project.id, kind, scene_id)
    if g is None:
        g = FilmGate(project_id=project.id, kind=kind, scene_id=scene_id)
        s.add(g)
    g.status = status
    g.note = note
    g.decided_at = datetime.now(timezone.utc) if status != "pending" else None
    invalidated: dict = {}
    if status == "approved":
        g.snapshot = snapshot_for(s, project, kind, scene_id)
        if kind == "assets":
            _mark_assets_approved(s, project, True)
        if kind == "storyboard":
            for sh, _ in proj_svc.ordered_shots(s, project.id):
                sh.approved = True
                if sh.status in ("planned", "framed"):
                    sh.status = "framed"
        if kind == "rough_cut" and scene_id:
            sc = s.get(FilmScene, scene_id)
            if sc:
                sc.approved = True
        if kind == "plan":
            plan = dict(project.plan or {})
            plan["approved"] = True
            plan["approved_at"] = g.decided_at.isoformat()
            project.plan = plan
    elif status == "rejected":
        invalidated = _invalidate(s, project, kind, scene_id, item_ids or [])
        if kind == "plan":
            plan = dict(project.plan or {})
            plan["approved"] = False
            project.plan = plan
    s.flush()
    events.log(s, project.id, f"{LABELS[kind]} {status}" + (f" (scene {scene_id})" if scene_id else ""),
               kind="gate", stage=kind, actor=actor, reason=note, entity=("gate", g.id),
               data={"items": item_ids or [], "invalidated": invalidated})
    d = gate_dict(s, project, g, kind, scene_id)
    d["invalidated"] = invalidated
    return d


def _mark_assets_approved(s: Session, project: FilmProject, value: bool, only: set[int] | None = None) -> list[int]:
    from .models import FilmAsset
    touched = []
    for aid in _project_assets(s, project):
        if only is not None and aid not in only:
            continue
        a = s.get(FilmAsset, aid)
        if a is not None and bool(a.approved) != value:
            a.approved = value
            touched.append(aid)
    return touched


def _set_pending(s: Session, project: FilmProject, kind: str, scene_id: int | None = None) -> bool:
    g = _row(s, project.id, kind, scene_id)
    if g is not None and g.status == "approved":
        g.status = "pending"
        g.decided_at = None
        return True
    return False


def _invalidate(s: Session, project: FilmProject, kind: str, scene_id: int | None,
                item_ids: list[int]) -> dict:
    """Only dependents of the rejected items lose their approval."""
    inv: dict = {"shots": [], "scenes": [], "gates": [], "assets": []}
    if kind == "plan":
        return inv                        # upstream: revising the plan deletes nothing
    if kind == "assets":
        used = _project_assets(s, project)
        rejected = set(item_ids) if item_ids else set(used)
        inv["assets"] = _mark_assets_approved(s, project, False, rejected)
        for sh, sc in proj_svc.ordered_shots(s, project.id):
            uses = {e["asset_id"] for e in proj_svc.effective_assets(s, sh, sc)}
            if uses & rejected:
                if sh.approved:
                    sh.approved = False
                names = ", ".join(str(a) for a in sorted(uses & rejected))
                sh.warnings = [w for w in (sh.warnings or []) if w.get("kind") != "asset_rejected"] + [
                    {"kind": "asset_rejected", "severity": "warn", "shot_ids": [sh.id], "heuristic": False,
                     "message": f"Uses rejected asset(s) {names} — re-approve assets or repin."}]
                inv["shots"].append(sh.id)
                if _set_pending(s, project, "rough_cut", sc.id) and sc.id not in inv["scenes"]:
                    inv["scenes"].append(sc.id)
        if inv["shots"]:
            for k in ("storyboard", "qa", "export"):
                if _set_pending(s, project, k):
                    inv["gates"].append(k)
    elif kind == "storyboard":
        targets = set(item_ids) if item_ids else {sh.id for sh, _ in proj_svc.ordered_shots(s, project.id)}
        for sh, sc in proj_svc.ordered_shots(s, project.id):
            if sh.id in targets:
                sh.approved = False
                if sh.status == "approved":
                    sh.status = "framed"
                inv["shots"].append(sh.id)
                if _set_pending(s, project, "rough_cut", sc.id) and sc.id not in inv["scenes"]:
                    inv["scenes"].append(sc.id)
        for k in ("qa", "export"):
            if _set_pending(s, project, k):
                inv["gates"].append(k)
    elif kind == "rough_cut" and scene_id:
        sc = s.get(FilmScene, scene_id)
        if sc:
            sc.approved = False
            inv["scenes"].append(sc.id)
        for k in ("qa", "export"):
            if _set_pending(s, project, k):
                inv["gates"].append(k)
    elif kind == "qa":
        if _set_pending(s, project, "export"):
            inv["gates"].append("export")
    return inv
