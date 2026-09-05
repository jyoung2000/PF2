"""Projects, scenes, shots — structure CRUD (spec §12, §14, §15) plus exact
asset pinning (spec §9/§26). Timing, inheritance/context, Director and gates
build on top of this in later modules; this one only knows shape and order."""
from __future__ import annotations

import shutil
from copy import deepcopy

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import assets as asset_svc
from . import events, storage
from .models import (MEDIA_STRATEGIES, FilmAsset, FilmAssetVersion, FilmProject,
                     FilmScene, FilmShot, FilmShotAsset, FilmTake)

DEFAULT_SETTINGS: dict = {
    "aspect_ratio": "16:9",
    "fps": 24,
    "target_runtime_s": 60,
    "default_scene_gap_s": 0.5,
    "default_transition": {"kind": "cut", "duration_s": 0.0},
    "pacing_profile": "normal",
    "continuity_mode": "balanced",
    "budget": {"mode": "warn", "threshold_usd": 5.0, "cap_usd": None},
    "pipeline_template": "cinematic_narrative",
    "chain_frames": True,
    "visual_style": "",
    "tone": "",
    "audience": "",
    "objective": "",
}
PROJECT_STATUSES = ("draft", "planning", "production", "complete")
SHOT_STATUSES = ("planned", "framed", "generated", "approved", "needs_repair")
TRANSITION_KINDS = ("cut", "dissolve", "fade_black", "fade_white", "wipe")


class ProjectError(ValueError):
    pass


# --------------------------------------------------------------- helpers ---
def _num(v, default: float, lo: float = 0.0, hi: float = 3600.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, f))


def clean_transition(t) -> dict | None:
    if t in (None, "", {}):
        return None
    if isinstance(t, str):
        t = {"kind": t}
    if not isinstance(t, dict):
        return None
    kind = t.get("kind") if t.get("kind") in TRANSITION_KINDS else "cut"
    dur = _num(t.get("duration_s"), 0.0 if kind == "cut" else 0.5, 0.0, 30.0)
    return {"kind": kind, "duration_s": 0.0 if kind == "cut" else dur}


def merge_settings(base: dict | None, changes: dict | None) -> dict:
    out = deepcopy(DEFAULT_SETTINGS)
    for src in (base or {}, changes or {}):
        for k, v in src.items():
            if k in ("budget", "default_transition") and isinstance(v, dict):
                out[k] = {**out.get(k, {}), **v}
            elif v is not None:
                out[k] = v
    out["default_scene_gap_s"] = _num(out.get("default_scene_gap_s"), 0.5, 0.0, 60.0)
    out["target_runtime_s"] = _num(out.get("target_runtime_s"), 60, 1, 24 * 3600)
    out["fps"] = _num(out.get("fps"), 24, 1, 120)
    out["default_transition"] = clean_transition(out.get("default_transition")) or {"kind": "cut", "duration_s": 0.0}
    if out.get("continuity_mode") not in ("flexible", "balanced", "strict"):
        out["continuity_mode"] = "balanced"
    b = out.get("budget") or {}
    if b.get("mode") not in ("observe", "warn", "approve", "cap"):
        b["mode"] = "warn"
    out["budget"] = b
    return out


def normalize_asset_refs(s: Session, items) -> list[dict]:
    """[{asset_id, version_id?, role?}] → validated entries with exact
    version ids (default = the asset's current version, which gets frozen
    because it is now in use)."""
    out: list[dict] = []
    seen: set[int] = set()
    for x in items or []:
        if not isinstance(x, dict):
            continue
        try:
            aid = int(x.get("asset_id"))
        except (TypeError, ValueError):
            continue
        if aid in seen:
            continue
        a = s.get(FilmAsset, aid)
        if a is None:
            raise ProjectError(f"asset {aid} not found")
        vid = x.get("version_id")
        if vid:
            v = s.get(FilmAssetVersion, int(vid))
            if v is None or v.asset_id != a.id:
                raise ProjectError(f"version {vid} does not belong to asset {aid}")
        else:
            v = asset_svc.current_version(s, a)
        asset_svc.freeze_version(s, v, "used by a scene")
        seen.add(aid)
        out.append({"asset_id": a.id, "version_id": v.id, "role": x.get("role") or a.type,
                    "name": a.name})
    return out


# -------------------------------------------------------------- projects ---
def create_project(s: Session, title: str, logline: str | None = None,
                   synopsis: str | None = None, script: str | None = None,
                   settings: dict | None = None) -> FilmProject:
    title = (title or "").strip()[:200]
    if not title:
        raise ProjectError("title is required")
    p = FilmProject(title=title, logline=logline, synopsis=synopsis, script=script,
                    settings=merge_settings(None, settings))
    s.add(p)
    s.flush()
    events.log(s, p.id, f"Project “{title}” created", kind="edit", stage="concept",
               entity=("project", p.id))
    return p


def update_project(s: Session, p: FilmProject, **fields) -> FilmProject:
    for key in ("title", "logline", "synopsis", "script"):
        if key in fields and fields[key] is not None:
            val = str(fields[key])
            if key == "title":
                val = val.strip()[:200]
                if not val:
                    raise ProjectError("title is required")
            setattr(p, key, val)
    if fields.get("status") in PROJECT_STATUSES:
        p.status = fields["status"]
    if fields.get("settings") is not None:
        before = p.settings or {}
        p.settings = merge_settings(before, fields["settings"])
        changed = {k: p.settings[k] for k in p.settings if before.get(k) != p.settings[k]}
        if changed:
            events.log(s, p.id, "Project settings changed", kind="edit", stage="concept",
                       entity=("project", p.id), data={"changed": changed})
    s.flush()
    return p


def delete_project(s: Session, p: FilmProject) -> None:
    pid = p.id
    s.delete(p)
    s.flush()
    try:
        shutil.rmtree(storage.resolve(f"film/projects/{pid}/x").parent, ignore_errors=True)
    except storage.UnsafePath:
        pass


def scenes_of(s: Session, project_id: int) -> list[FilmScene]:
    return list(s.execute(select(FilmScene).where(FilmScene.project_id == project_id)
                          .order_by(FilmScene.position.asc(), FilmScene.id.asc())).scalars())


def shots_of(s: Session, scene_id: int) -> list[FilmShot]:
    return list(s.execute(select(FilmShot).where(FilmShot.scene_id == scene_id)
                          .order_by(FilmShot.position.asc(), FilmShot.id.asc())).scalars())


def ordered_shots(s: Session, project_id: int) -> list[tuple[FilmShot, FilmScene]]:
    out = []
    for sc in scenes_of(s, project_id):
        out += [(sh, sc) for sh in shots_of(s, sc.id)]
    return out


# ---------------------------------------------------------------- scenes ---
def create_scene(s: Session, p: FilmProject, title: str | None = None,
                 position: int | None = None, **fields) -> FilmScene:
    existing = scenes_of(s, p.id)
    sc = FilmScene(project_id=p.id, title=(title or f"Scene {len(existing) + 1}").strip()[:200],
                   position=len(existing))
    s.add(sc)
    s.flush()
    update_scene(s, sc, **fields)
    if position is not None and 0 <= position < len(existing):
        ids = [x.id for x in existing]
        ids.insert(position, sc.id)
        reorder_scenes(s, p, ids)
    return sc


def update_scene(s: Session, sc: FilmScene, **fields) -> FilmScene:
    for key in ("title", "act", "intent", "summary", "script_text"):
        if key in fields and fields[key] is not None:
            val = str(fields[key])
            if key == "title":
                val = val.strip()[:200] or sc.title
            elif key == "act":
                val = val.strip()[:100] or None
            setattr(sc, key, val)
    if "defaults" in fields and fields["defaults"] is not None:
        d = dict(fields["defaults"])
        if "assets" in d:
            d["assets"] = normalize_asset_refs(s, d.get("assets"))
        sc.defaults = {**(sc.defaults or {}), **d}
    if "gap_after_s" in fields:
        g = fields["gap_after_s"]
        sc.gap_after_s = None if g in (None, "") else _num(g, 0.5, 0.0, 60.0)
    if "transition" in fields:
        sc.transition = clean_transition(fields["transition"])
    if "approved" in fields and fields["approved"] is not None:
        sc.approved = bool(fields["approved"])
    s.flush()
    return sc


def reorder_scenes(s: Session, p: FilmProject, ids: list[int]) -> list[FilmScene]:
    current = scenes_of(s, p.id)
    by_id = {sc.id: sc for sc in current}
    order = [i for i in ids if i in by_id] + [sc.id for sc in current if sc.id not in ids]
    for pos, sid in enumerate(order):
        by_id[sid].position = pos
    s.flush()
    return scenes_of(s, p.id)


def delete_scene(s: Session, sc: FilmScene) -> None:
    pid = sc.project_id
    s.delete(sc)
    s.flush()
    p = s.get(FilmProject, pid)
    if p is not None:
        reorder_scenes(s, p, [x.id for x in scenes_of(s, pid)])


# ----------------------------------------------------------------- shots ---
def create_shot(s: Session, sc: FilmScene, title: str | None = None,
                position: int | None = None, duration_s: float | None = None,
                **fields) -> FilmShot:
    existing = shots_of(s, sc.id)
    sh = FilmShot(project_id=sc.project_id, scene_id=sc.id, position=len(existing),
                  title=(title or "").strip()[:200] or None,
                  duration_s=_num(duration_s, 4.0, 0.1, 600.0))
    s.add(sh)
    s.flush()
    update_shot(s, sh, **fields)
    if position is not None and 0 <= position < len(existing):
        ids = [x.id for x in existing]
        ids.insert(position, sh.id)
        reorder_shots(s, sc, ids)
    return sh


def update_shot(s: Session, sh: FilmShot, **fields) -> FilmShot:
    if "title" in fields and fields["title"] is not None:
        sh.title = str(fields["title"]).strip()[:200] or None
    if "notes" in fields and fields["notes"] is not None:
        sh.notes = str(fields["notes"]) or None
    if fields.get("status") in SHOT_STATUSES:
        sh.status = fields["status"]
    if fields.get("duration_s") is not None:
        sh.duration_s = _num(fields["duration_s"], sh.duration_s, 0.1, 600.0)
    if "transition" in fields:
        sh.transition = clean_transition(fields["transition"])
    if fields.get("media_strategy") in MEDIA_STRATEGIES:
        sh.media_strategy = fields["media_strategy"]
    if "overrides" in fields and fields["overrides"] is not None:
        if not isinstance(fields["overrides"], dict):
            raise ProjectError("overrides must be an object")
        sh.overrides = _clean_overrides(fields["overrides"])
    if "locks" in fields and fields["locks"] is not None:
        sh.locks = [str(x)[:60] for x in fields["locks"] if isinstance(x, str) and x.strip()][:60]
    for key in ("start_frame", "end_frame"):
        if key in fields:
            v = fields[key]
            setattr(sh, key, dict(v) if isinstance(v, dict) and v else None)
    if "chain_from_previous" in fields and fields["chain_from_previous"] is not None:
        sh.chain_from_previous = bool(fields["chain_from_previous"])
    if "approved" in fields and fields["approved"] is not None:
        sh.approved = bool(fields["approved"])
        if sh.approved and sh.status in ("generated", "framed"):
            sh.status = "approved"
    if "selected_take_id" in fields:
        tid = fields["selected_take_id"]
        if tid is not None:
            t = s.get(FilmTake, int(tid))
            if t is None or t.shot_id != sh.id:
                raise ProjectError("take does not belong to this shot")
        sh.selected_take_id = tid
    if "assets" in fields and fields["assets"] is not None:
        set_shot_assets(s, sh, fields["assets"])
    s.flush()
    return sh


_OVERRIDE_GROUPS = ("action", "camera", "lighting", "environment", "color", "motion",
                    "style", "prompt", "negative", "generation", "assets_note", "subject",
                    "shot_type", "lighting_preset", "camera_preset", "expression", "pose",
                    "characters", "continuity_override", "reference_ids", "inspiration")


def _clean_overrides(o: dict) -> dict:
    out: dict = {}
    for k, v in o.items():
        if not isinstance(k, str) or k not in _OVERRIDE_GROUPS:
            continue
        if v in (None, "", {}, []):
            continue
        if isinstance(v, dict):
            out[k] = {str(a)[:60]: (b if not isinstance(b, str) else b[:4000])
                      for a, b in v.items() if b not in (None, "")}
            if not out[k]:
                out.pop(k)
        elif isinstance(v, str):
            out[k] = v[:4000]
        else:
            out[k] = v
    return out


def reorder_shots(s: Session, sc: FilmScene, ids: list[int]) -> list[FilmShot]:
    current = shots_of(s, sc.id)
    by_id = {sh.id: sh for sh in current}
    order = [i for i in ids if i in by_id] + [sh.id for sh in current if sh.id not in ids]
    for pos, sid in enumerate(order):
        by_id[sid].position = pos
    s.flush()
    return shots_of(s, sc.id)


def move_shot(s: Session, sh: FilmShot, scene_id: int, position: int | None = None) -> FilmShot:
    target = s.get(FilmScene, scene_id)
    if target is None or target.project_id != sh.project_id:
        raise ProjectError("target scene not found in this project")
    old_scene = s.get(FilmScene, sh.scene_id)
    sh.scene_id = target.id
    s.flush()
    ids = [x.id for x in shots_of(s, target.id) if x.id != sh.id]
    ids.insert(len(ids) if position is None else max(0, min(position, len(ids))), sh.id)
    reorder_shots(s, target, ids)
    if old_scene is not None and old_scene.id != target.id:
        reorder_shots(s, old_scene, [x.id for x in shots_of(s, old_scene.id)])
    return sh


def duplicate_shot(s: Session, sh: FilmShot) -> FilmShot:
    sc = s.get(FilmScene, sh.scene_id)
    new = FilmShot(project_id=sh.project_id, scene_id=sh.scene_id, position=sh.position + 1,
                   title=(f"{sh.title} (copy)" if sh.title else None), status="planned",
                   duration_s=sh.duration_s, transition=deepcopy(sh.transition),
                   media_strategy=sh.media_strategy, overrides=deepcopy(sh.overrides or {}),
                   locks=list(sh.locks or []), start_frame=deepcopy(sh.start_frame),
                   end_frame=deepcopy(sh.end_frame), chain_from_previous=sh.chain_from_previous,
                   notes=sh.notes)
    s.add(new)
    s.flush()
    for pin in shot_pins(s, sh):
        s.add(FilmShotAsset(shot_id=new.id, asset_id=pin.asset_id, version_id=pin.version_id,
                            role=pin.role, notes=pin.notes))
    s.flush()
    ids = [x.id for x in shots_of(s, sc.id) if x.id != new.id]
    ids.insert(sh.position + 1, new.id)
    reorder_shots(s, sc, ids)
    return new


def delete_shot(s: Session, sh: FilmShot) -> None:
    sc = s.get(FilmScene, sh.scene_id)
    s.delete(sh)
    s.flush()
    if sc is not None:
        reorder_shots(s, sc, [x.id for x in shots_of(s, sc.id)])


# ---------------------------------------------------------- shot assets ----
def shot_pins(s: Session, sh: FilmShot) -> list[FilmShotAsset]:
    return list(s.execute(select(FilmShotAsset).where(FilmShotAsset.shot_id == sh.id)
                          .order_by(FilmShotAsset.id.asc())).scalars())


def pin_asset(s: Session, sh: FilmShot, asset: FilmAsset, version_id: int | None = None,
              role: str | None = None, notes: str | None = None) -> FilmShotAsset:
    if version_id:
        v = s.get(FilmAssetVersion, version_id)
        if v is None or v.asset_id != asset.id:
            raise ProjectError("version does not belong to this asset")
    else:
        v = asset_svc.current_version(s, asset)
    pin = s.execute(select(FilmShotAsset).where(FilmShotAsset.shot_id == sh.id,
                                                FilmShotAsset.asset_id == asset.id)).scalar_one_or_none()
    if pin is None:
        pin = FilmShotAsset(shot_id=sh.id, asset_id=asset.id, version_id=v.id,
                            role=role or asset.type, notes=notes)
        s.add(pin)
    else:
        pin.version_id = v.id
        if role:
            pin.role = role
        if notes is not None:
            pin.notes = notes
    asset_svc.freeze_version(s, v, "pinned by a shot")
    s.flush()
    return pin


def unpin_asset(s: Session, sh: FilmShot, asset_id: int) -> bool:
    pin = s.execute(select(FilmShotAsset).where(FilmShotAsset.shot_id == sh.id,
                                                FilmShotAsset.asset_id == asset_id)).scalar_one_or_none()
    if pin is None:
        return False
    s.delete(pin)
    s.flush()
    return True


def set_shot_assets(s: Session, sh: FilmShot, items) -> list[FilmShotAsset]:
    """Replace the shot's explicit pins with the given list."""
    wanted = normalize_asset_refs(s, items)
    keep = {w["asset_id"] for w in wanted}
    for pin in shot_pins(s, sh):
        if pin.asset_id not in keep:
            s.delete(pin)
    s.flush()
    for w in wanted:
        a = s.get(FilmAsset, w["asset_id"])
        pin_asset(s, sh, a, w["version_id"], w.get("role"))
    return shot_pins(s, sh)


def effective_assets(s: Session, sh: FilmShot, sc: FilmScene | None = None) -> list[dict]:
    """Scene default assets overridden by the shot's explicit pins — every
    entry carries the exact version and where it came from."""
    sc = sc or s.get(FilmScene, sh.scene_id)
    out: dict[int, dict] = {}
    for x in (sc.defaults or {}).get("assets", []) if sc else []:
        if isinstance(x, dict) and x.get("asset_id"):
            out[int(x["asset_id"])] = {"asset_id": int(x["asset_id"]),
                                       "version_id": int(x.get("version_id") or 0) or None,
                                       "role": x.get("role"), "source": "scene"}
    for pin in shot_pins(s, sh):
        out[pin.asset_id] = {"asset_id": pin.asset_id, "version_id": pin.version_id,
                             "role": pin.role, "source": "shot", "notes": pin.notes}
    result = []
    for entry in out.values():
        a = s.get(FilmAsset, entry["asset_id"])
        if a is None:
            continue
        v = s.get(FilmAssetVersion, entry["version_id"]) if entry.get("version_id") else None
        if v is None:
            v = asset_svc.current_version(s, a)
        entry.update({"name": a.name, "type": a.type, "version_id": v.id,
                      "version": v.number, "version_label": v.label or f"v{v.number}",
                      "role": entry.get("role") or a.type,
                      "is_current": v.id == a.current_version_id,
                      "thumb_url": asset_svc.version_dict(s, v)["primary_thumb_url"]})
        result.append(entry)
    order = {"character": 0, "location": 1, "prop": 2, "vehicle": 3, "outfit": 4, "style": 5}
    result.sort(key=lambda e: (order.get(e["type"], 9), e["name"].lower()))
    return result


# ----------------------------------------------------------------- dicts ---
def take_dict(t: FilmTake) -> dict:
    return {"id": t.id, "shot_id": t.shot_id, "number": t.number, "kind": t.kind,
            "status": t.status, "mode": t.mode, "generation_id": t.generation_id,
            "provider": t.provider, "model_family": t.model_family,
            "provider_model_id": t.provider_model_id, "prompt": t.prompt, "negative": t.negative,
            "params": t.params or {}, "context": t.context or {}, "decision": t.decision or {},
            "cost_estimate": t.cost_estimate, "cost_actual": t.cost_actual,
            "duration_s": t.duration_s, "media_url": _media_url(t.media_path),
            "thumb_url": _media_url(t.thumb_path), "width": t.width, "height": t.height,
            "post_id": t.post_id, "qa": t.qa, "error": t.error,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "finished_at": t.finished_at.isoformat() if t.finished_at else None}


def _media_url(rel: str | None) -> str | None:
    if not rel:
        return None
    if rel.startswith("film/"):
        return storage.url_for(rel)
    return "/" + rel  # library media (DATA_DIR/media/…) served at /media


def shot_dict(s: Session, sh: FilmShot, sc: FilmScene | None = None,
              include_takes: bool = False) -> dict:
    sc = sc or s.get(FilmScene, sh.scene_id)
    takes = list(s.execute(select(FilmTake).where(FilmTake.shot_id == sh.id)
                           .order_by(FilmTake.id.asc())).scalars())
    selected = next((t for t in takes if t.id == sh.selected_take_id), None)
    d = {"id": sh.id, "project_id": sh.project_id, "scene_id": sh.scene_id,
         "position": sh.position, "number": sh.position + 1,
         "label": f"{(sc.position + 1) if sc else 0}.{sh.position + 1}",
         "title": sh.title, "status": sh.status, "duration_s": sh.duration_s,
         "transition": sh.transition, "media_strategy": sh.media_strategy,
         "overrides": sh.overrides or {}, "locks": list(sh.locks or []),
         "start_frame": sh.start_frame, "end_frame": sh.end_frame,
         "chain_from_previous": bool(sh.chain_from_previous),
         "selected_take_id": sh.selected_take_id,
         "selected_take": take_dict(selected) if selected else None,
         "approved": bool(sh.approved), "qa": sh.qa, "warnings": list(sh.warnings or []),
         "notes": sh.notes, "assets": effective_assets(s, sh, sc),
         "take_count": len(takes),
         "thumb_url": (take_dict(selected)["thumb_url"] if selected else
                       next((take_dict(t)["thumb_url"] for t in reversed(takes)
                             if t.thumb_path or t.media_path), None)),
         "created_at": sh.created_at.isoformat() if sh.created_at else None,
         "updated_at": sh.updated_at.isoformat() if sh.updated_at else None}
    if include_takes:
        d["takes"] = [take_dict(t) for t in takes]
    return d


def scene_dict(s: Session, sc: FilmScene, include_shots: bool = True) -> dict:
    d = {"id": sc.id, "project_id": sc.project_id, "position": sc.position,
         "number": sc.position + 1, "act": sc.act, "title": sc.title, "intent": sc.intent,
         "summary": sc.summary, "script_text": sc.script_text, "defaults": sc.defaults or {},
         "gap_after_s": sc.gap_after_s, "transition": sc.transition,
         "approved": bool(sc.approved),
         "created_at": sc.created_at.isoformat() if sc.created_at else None,
         "updated_at": sc.updated_at.isoformat() if sc.updated_at else None}
    if include_shots:
        d["shots"] = [shot_dict(s, sh, sc) for sh in shots_of(s, sc.id)]
    return d


def project_dict(s: Session, p: FilmProject, deep: bool = False) -> dict:
    scene_count = s.execute(select(func.count(FilmScene.id)).where(FilmScene.project_id == p.id)).scalar_one()
    shot_count = s.execute(select(func.count(FilmShot.id)).where(FilmShot.project_id == p.id)).scalar_one()
    d = {"id": p.id, "title": p.title, "logline": p.logline, "synopsis": p.synopsis,
         "script": p.script, "status": p.status, "settings": merge_settings(p.settings, None),
         "plan": p.plan or {}, "reference": p.reference or {},
         "scene_count": scene_count, "shot_count": shot_count,
         "created_at": p.created_at.isoformat() if p.created_at else None,
         "updated_at": p.updated_at.isoformat() if p.updated_at else None}
    if deep:
        d["scenes"] = [scene_dict(s, sc) for sc in scenes_of(s, p.id)]
    return d


def list_projects(s: Session) -> list[dict]:
    rows = s.execute(select(FilmProject).order_by(FilmProject.updated_at.desc())).scalars()
    return [project_dict(s, p) for p in rows]
