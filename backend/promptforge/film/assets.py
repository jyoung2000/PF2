"""AssetService + AssetVersionService (spec §3, §9, §10).

Versions are copy-on-write: the current version stays editable in place
until it is *frozen* — pinned by a shot/take, superseded by a newer version,
or explicitly saved — and editing a frozen version creates the next one.
Old shots therefore keep the exact version they were generated against and
nothing is ever rewritten silently; propagation to shots is an explicit
action (selected / future / whole project)."""
from __future__ import annotations

import shutil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import attributes, context as ctx_mod, events, storage
from .models import (FilmAsset, FilmAssetRef, FilmAssetVersion, FilmScene,
                     FilmShot, FilmShotAsset, FilmTake)


class AssetError(ValueError):
    pass


class AssetInUse(AssetError):
    pass


def _strs(items) -> list[str]:
    out: list[str] = []
    for x in items or []:
        if isinstance(x, str) and x.strip():
            out.append(x.strip()[:500])
    return out[:60]


def _tags(items) -> list[str]:
    seen: list[str] = []
    for t in items or []:
        if isinstance(t, str):
            t = t.strip().lower()[:60]
            if t and t not in seen:
                seen.append(t)
    return seen[:40]


# ------------------------------------------------------------- lookups -----
def get_asset(s: Session, asset_id: int) -> FilmAsset | None:
    return s.get(FilmAsset, asset_id)


def get_version(s: Session, version_id: int) -> FilmAssetVersion | None:
    return s.get(FilmAssetVersion, version_id)


def versions_of(s: Session, asset_id: int) -> list[FilmAssetVersion]:
    return list(s.execute(select(FilmAssetVersion)
                          .where(FilmAssetVersion.asset_id == asset_id)
                          .order_by(FilmAssetVersion.number.asc())).scalars())


def current_version(s: Session, asset: FilmAsset) -> FilmAssetVersion:
    v = s.get(FilmAssetVersion, asset.current_version_id) if asset.current_version_id else None
    if v is None:
        rows = versions_of(s, asset.id)
        if not rows:
            raise AssetError(f"asset {asset.id} has no versions")
        v = rows[-1]
        asset.current_version_id = v.id
    return v


def refs_visible(s: Session, asset_id: int, version_id: int | None) -> list[FilmAssetRef]:
    rows = s.execute(select(FilmAssetRef).where(FilmAssetRef.asset_id == asset_id)
                     .order_by(FilmAssetRef.id.asc())).scalars()
    return [r for r in rows if r.version_id is None or r.version_id == version_id]


# ------------------------------------------------------------- creation ----
def create_asset(s: Session, type: str, name: str, description: str | None = None,
                 tags=None, data: dict | None = None, locks=None,
                 continuity_rules=None, negative_constraints=None, identity_anchors=None,
                 project_id: int | None = None, owner_asset_id: int | None = None,
                 provenance: dict | None = None, notes: str | None = None,
                 actor: str = "user") -> FilmAsset:
    if type not in attributes.asset_types():
        raise AssetError(f"unknown asset type {type!r}")
    name = (name or "").strip()[:200]
    if not name:
        raise AssetError("name is required")
    if owner_asset_id is not None:
        owner = s.get(FilmAsset, owner_asset_id)
        if owner is None:
            raise AssetError("owner asset not found")
        if type != "outfit":
            raise AssetError("only outfits belong to another asset")
    prov = dict(provenance or {})
    prov.setdefault("origin", "manual")
    a = FilmAsset(type=type, name=name, description=(description or None),
                  tags=_tags(tags), notes=notes, project_id=project_id,
                  owner_asset_id=owner_asset_id, provenance=prov)
    s.add(a)
    s.flush()
    v = FilmAssetVersion(
        asset_id=a.id, number=1,
        data=attributes.clean_data(type, data),
        locks=(attributes.valid_locks(type, locks) if locks is not None
               else attributes.default_locks(type)),
        continuity_rules=_strs(continuity_rules),
        negative_constraints=_strs(negative_constraints),
        identity_anchors=_strs(identity_anchors),
        provenance={"source": prov.get("origin", "manual"), "actor": actor})
    s.add(v)
    s.flush()
    a.current_version_id = v.id
    s.flush()
    events.log(s, project_id, f"Created {type} “{name}”", kind="edit", actor=actor,
               entity=("asset", a.id), data={"version_id": v.id, "origin": prov.get("origin")})
    return a


def update_asset(s: Session, asset: FilmAsset, actor: str = "user", **fields) -> FilmAsset:
    """Metadata-only edits (never versioned): name, description, tags, notes,
    favorite, pinned, approved, project_id."""
    for key in ("name", "description", "notes"):
        if key in fields and fields[key] is not None:
            val = str(fields[key]).strip()
            if key == "name":
                if not val:
                    raise AssetError("name is required")
                val = val[:200]
            setattr(asset, key, val or None)
    if "tags" in fields and fields["tags"] is not None:
        asset.tags = _tags(fields["tags"])
    for key in ("favorite", "pinned"):
        if key in fields and fields[key] is not None:
            setattr(asset, key, bool(fields[key]))
    if "project_id" in fields:
        asset.project_id = fields["project_id"]
    if "approved" in fields and fields["approved"] is not None:
        new = bool(fields["approved"])
        if new != bool(asset.approved):
            asset.approved = new
            events.log(s, asset.project_id,
                       f"{'Approved' if new else 'Approval withdrawn for'} {asset.type} “{asset.name}”",
                       kind="gate", stage="assets", actor=actor, entity=("asset", asset.id),
                       data={"version_id": asset.current_version_id})
    s.flush()
    return asset


# ------------------------------------------------------------- versions ----
def _next_number(s: Session, asset_id: int) -> int:
    n = s.execute(select(func.max(FilmAssetVersion.number))
                  .where(FilmAssetVersion.asset_id == asset_id)).scalar()
    return int(n or 0) + 1


def freeze_version(s: Session, version: FilmAssetVersion, reason: str) -> None:
    if not version.frozen:
        version.frozen = True
        prov = dict(version.provenance or {})
        prov.setdefault("frozen_reason", reason)
        version.provenance = prov
        s.flush()


def _new_version(s: Session, asset: FilmAsset, *, data: dict, locks: list,
                 continuity_rules: list, negative_constraints: list,
                 identity_anchors: list, label: str | None, note: str | None,
                 provenance: dict, primary_ref_id: int | None = None) -> FilmAssetVersion:
    # everything before is history now
    for old in versions_of(s, asset.id):
        freeze_version(s, old, "superseded")
    v = FilmAssetVersion(
        asset_id=asset.id, number=_next_number(s, asset.id), label=label,
        data=attributes.clean_data(asset.type, data),
        locks=attributes.valid_locks(asset.type, locks),
        continuity_rules=_strs(continuity_rules),
        negative_constraints=_strs(negative_constraints),
        identity_anchors=_strs(identity_anchors),
        primary_ref_id=primary_ref_id, note=note, provenance=provenance)
    s.add(v)
    s.flush()
    return v


def edit_version(s: Session, asset: FilmAsset, changes: dict | None = None,
                 locks=None, continuity_rules=None, negative_constraints=None,
                 identity_anchors=None, label: str | None = None, note: str | None = None,
                 force_new: bool = False, actor: str = "user",
                 reason: str | None = None) -> tuple[FilmAssetVersion, bool]:
    """Apply an edit to the CURRENT version. In place while it is unfrozen;
    otherwise (or with force_new) a new version is created and made current.
    Returns (version, created)."""
    cur = current_version(s, asset)
    data = attributes.merge_data(asset.type, cur.data, changes)
    new_locks = (attributes.valid_locks(asset.type, locks) if locks is not None
                 else list(cur.locks or []))
    rules = _strs(continuity_rules) if continuity_rules is not None else list(cur.continuity_rules or [])
    negs = _strs(negative_constraints) if negative_constraints is not None else list(cur.negative_constraints or [])
    anchors = _strs(identity_anchors) if identity_anchors is not None else list(cur.identity_anchors or [])
    if cur.frozen or force_new:
        v = _new_version(s, asset, data=data, locks=new_locks, continuity_rules=rules,
                         negative_constraints=negs, identity_anchors=anchors,
                         label=label, note=note, primary_ref_id=cur.primary_ref_id,
                         provenance={"source": "edit", "from_version_id": cur.id,
                                     "actor": actor, "reason": reason})
        asset.current_version_id = v.id
        s.flush()
        events.log(s, asset.project_id, f"{asset.name}: new version v{v.number}", kind="edit",
                   actor=actor, reason=reason or ("previous version was in use"
                                                  if cur.frozen else "saved as new version"),
                   entity=("asset", asset.id),
                   data={"version_id": v.id, "from_version_id": cur.id,
                         "changed": sorted((changes or {}).keys())})
        return v, True
    cur.data = data
    cur.locks = new_locks
    cur.continuity_rules = rules
    cur.negative_constraints = negs
    cur.identity_anchors = anchors
    if label is not None:
        cur.label = label or None
    if note is not None:
        cur.note = note or None
    s.flush()
    return cur, False


def restore_version(s: Session, asset: FilmAsset, version_id: int,
                    actor: str = "user") -> FilmAssetVersion:
    """Bring an old version back as a NEW current version (history intact)."""
    old = s.get(FilmAssetVersion, version_id)
    if old is None or old.asset_id != asset.id:
        raise AssetError("version not found")
    v = _new_version(s, asset, data=dict(old.data or {}), locks=list(old.locks or []),
                     continuity_rules=list(old.continuity_rules or []),
                     negative_constraints=list(old.negative_constraints or []),
                     identity_anchors=list(old.identity_anchors or []),
                     label=f"restored v{old.number}", note=old.note,
                     primary_ref_id=old.primary_ref_id,
                     provenance={"source": "restore", "from_version_id": old.id, "actor": actor})
    asset.current_version_id = v.id
    s.flush()
    events.log(s, asset.project_id, f"{asset.name}: restored v{old.number} as v{v.number}",
               kind="edit", actor=actor, entity=("asset", asset.id),
               data={"version_id": v.id, "from_version_id": old.id})
    return v


def duplicate_version(s: Session, asset: FilmAsset, version_id: int,
                      label: str | None = None, actor: str = "user") -> FilmAssetVersion:
    """Copy a version into a new one WITHOUT changing what is current."""
    src = s.get(FilmAssetVersion, version_id)
    if src is None or src.asset_id != asset.id:
        raise AssetError("version not found")
    v = _new_version(s, asset, data=dict(src.data or {}), locks=list(src.locks or []),
                     continuity_rules=list(src.continuity_rules or []),
                     negative_constraints=list(src.negative_constraints or []),
                     identity_anchors=list(src.identity_anchors or []),
                     label=label or f"copy of v{src.number}", note=src.note,
                     primary_ref_id=src.primary_ref_id,
                     provenance={"source": "duplicate", "from_version_id": src.id, "actor": actor})
    # the duplicate is a fresh draft; `_new_version` froze the others, but the
    # current one keeps its editability only if it was not in use
    events.log(s, asset.project_id, f"{asset.name}: duplicated v{src.number} as v{v.number}",
               kind="edit", actor=actor, entity=("asset", asset.id),
               data={"version_id": v.id, "from_version_id": src.id})
    return v


def use_as_current(s: Session, asset: FilmAsset, version_id: int,
                   actor: str = "user") -> FilmAssetVersion:
    v = s.get(FilmAssetVersion, version_id)
    if v is None or v.asset_id != asset.id:
        raise AssetError("version not found")
    if asset.current_version_id != v.id:
        prev = asset.current_version_id
        asset.current_version_id = v.id
        s.flush()
        events.log(s, asset.project_id, f"{asset.name}: v{v.number} is now current", kind="edit",
                   actor=actor, entity=("asset", asset.id),
                   data={"version_id": v.id, "previous_version_id": prev})
    return v


def _flatten(d: dict, prefix: str = "") -> dict:
    out: dict = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def compare_versions(s: Session, a_id: int, b_id: int) -> dict:
    a = s.get(FilmAssetVersion, a_id)
    b = s.get(FilmAssetVersion, b_id)
    if a is None or b is None or a.asset_id != b.asset_id:
        raise AssetError("versions not found or belong to different assets")
    fa, fb = _flatten(a.data or {}), _flatten(b.data or {})
    added = {k: fb[k] for k in fb if k not in fa}
    removed = {k: fa[k] for k in fa if k not in fb}
    changed = {k: {"a": fa[k], "b": fb[k]} for k in fa if k in fb and fa[k] != fb[k]}
    same = sorted(k for k in fa if k in fb and fa[k] == fb[k])
    la, lb = set(a.locks or []), set(b.locks or [])
    return {
        "a": {"id": a.id, "number": a.number, "label": a.label, "primary_ref_id": a.primary_ref_id},
        "b": {"id": b.id, "number": b.number, "label": b.label, "primary_ref_id": b.primary_ref_id},
        "added": added, "removed": removed, "changed": changed, "same": same,
        "locks": {"a": sorted(la), "b": sorted(lb),
                  "locked_in_b": sorted(lb - la), "unlocked_in_b": sorted(la - lb)},
        "continuity_rules": {"a": list(a.continuity_rules or []), "b": list(b.continuity_rules or [])},
        "identical": not added and not removed and not changed and la == lb,
    }


# --------------------------------------------------------------- usage -----
def version_usage(s: Session, version_id: int) -> dict:
    shots = [r for (r,) in s.execute(select(FilmShotAsset.shot_id)
                                     .where(FilmShotAsset.version_id == version_id))]
    takes = _take_usage(s, version_id)
    scenes = [sc.id for sc in s.execute(select(FilmScene)).scalars()
              if any(int(x.get("version_id") or 0) == version_id
                     for x in (sc.defaults or {}).get("assets", []) if isinstance(x, dict))]
    return {"shots": sorted(set(shots)), "takes": takes, "scenes": scenes,
            "in_use": bool(shots or takes or scenes)}


def _take_usage(s: Session, version_id: int) -> list[int]:
    out: list[int] = []
    for t in s.execute(select(FilmTake)).scalars():
        for entry in (t.context or {}).get("assets", []) or []:
            if isinstance(entry, dict) and int(entry.get("version_id") or 0) == version_id:
                out.append(t.id)
                break
    return out


def asset_usage(s: Session, asset_id: int) -> dict:
    pins = list(s.execute(select(FilmShotAsset).where(FilmShotAsset.asset_id == asset_id)).scalars())
    shot_ids = sorted({p.shot_id for p in pins})
    scene_ids: list[int] = []
    for sc in s.execute(select(FilmScene)).scalars():
        for x in (sc.defaults or {}).get("assets", []) or []:
            if isinstance(x, dict) and int(x.get("asset_id") or 0) == asset_id:
                scene_ids.append(sc.id)
                break
    project_ids: set[int] = set()
    if shot_ids:
        project_ids |= {pid for (pid,) in s.execute(
            select(FilmShot.project_id).where(FilmShot.id.in_(shot_ids)))}
    if scene_ids:
        project_ids |= {pid for (pid,) in s.execute(
            select(FilmScene.project_id).where(FilmScene.id.in_(scene_ids)))}
    shots = []
    if shot_ids:
        for sh in s.execute(select(FilmShot).where(FilmShot.id.in_(shot_ids))
                            .order_by(FilmShot.scene_id, FilmShot.position)).scalars():
            pin = next(p for p in pins if p.shot_id == sh.id)
            shots.append({"shot_id": sh.id, "scene_id": sh.scene_id, "project_id": sh.project_id,
                          "position": sh.position, "title": sh.title,
                          "version_id": pin.version_id, "role": pin.role})
    return {"shots": shots, "scene_ids": scene_ids, "project_ids": sorted(project_ids),
            "in_use": bool(shots or scene_ids)}


# -------------------------------------------------------------- deletion ---
def delete_asset(s: Session, asset: FilmAsset, force: bool = False, actor: str = "user") -> None:
    usage = asset_usage(s, asset.id)
    if usage["in_use"] and not force:
        raise AssetInUse(
            f"“{asset.name}” is used by {len(usage['shots'])} shot(s) and "
            f"{len(usage['scene_ids'])} scene default(s) — remove it from them first "
            "or delete with force.")
    if force:
        for pin in s.execute(select(FilmShotAsset).where(FilmShotAsset.asset_id == asset.id)).scalars():
            s.delete(pin)
        for sc_id in usage["scene_ids"]:
            sc = s.get(FilmScene, sc_id)
            if sc is not None:
                d = dict(sc.defaults or {})
                d["assets"] = [x for x in d.get("assets", [])
                               if not (isinstance(x, dict) and int(x.get("asset_id") or 0) == asset.id)]
                sc.defaults = d
        s.flush()
    children = list(s.execute(select(FilmAsset).where(FilmAsset.owner_asset_id == asset.id)).scalars())
    for child in children:
        delete_asset(s, child, force=True, actor=actor)
    name, atype, aid, project_id = asset.name, asset.type, asset.id, asset.project_id
    s.delete(asset)
    s.flush()
    try:
        shutil.rmtree(storage.resolve(f"film/assets/{aid}/refs").parent, ignore_errors=True)
    except storage.UnsafePath:
        pass
    events.log(s, project_id, f"Deleted {atype} “{name}”", kind="edit", actor=actor,
               entity=("asset", aid), data={"forced": force})


# ----------------------------------------------------------- propagation ---
def _ordered_shots(s: Session, project_id: int) -> list[tuple[FilmShot, FilmScene]]:
    scenes = {sc.id: sc for sc in s.execute(select(FilmScene).where(FilmScene.project_id == project_id)).scalars()}
    shots = list(s.execute(select(FilmShot).where(FilmShot.project_id == project_id)).scalars())
    shots.sort(key=lambda sh: (scenes[sh.scene_id].position if sh.scene_id in scenes else 0,
                               sh.position, sh.id))
    return [(sh, scenes.get(sh.scene_id)) for sh in shots]


def _scene_uses(sc: FilmScene | None, asset_id: int) -> dict | None:
    if sc is None:
        return None
    for x in (sc.defaults or {}).get("assets", []) or []:
        if isinstance(x, dict) and int(x.get("asset_id") or 0) == asset_id:
            return x
    return None


def _set_scene_version(s: Session, sc: FilmScene, asset_id: int, version_id: int) -> None:
    d = dict(sc.defaults or {})
    items = []
    for x in d.get("assets", []) or []:
        if isinstance(x, dict) and int(x.get("asset_id") or 0) == asset_id:
            x = dict(x, version_id=version_id)
        items.append(x)
    d["assets"] = items
    sc.defaults = d


def _set_pin(s: Session, shot: FilmShot, asset: FilmAsset, version_id: int,
             role: str | None = None) -> FilmShotAsset:
    pin = s.execute(select(FilmShotAsset).where(FilmShotAsset.shot_id == shot.id,
                                                FilmShotAsset.asset_id == asset.id)).scalar_one_or_none()
    if pin is None:
        pin = FilmShotAsset(shot_id=shot.id, asset_id=asset.id, version_id=version_id,
                            role=role or asset.type)
        s.add(pin)
    else:
        pin.version_id = version_id
    s.flush()
    return pin


def propagate_version(s: Session, asset: FilmAsset, version_id: int, scope: str,
                      project_id: int | None = None, shot_ids: list[int] | None = None,
                      from_shot_id: int | None = None, actor: str = "user") -> dict:
    """Explicit version update (spec §9): scope = selected (shot_ids) |
    future (from_shot_id onward, in project order) | project (everything).
    Shots that must keep the old version get an explicit pin so nothing
    changes for them."""
    v = s.get(FilmAssetVersion, version_id)
    if v is None or v.asset_id != asset.id:
        raise AssetError("version not found")
    updated_shots: list[int] = []
    updated_scenes: list[int] = []

    if scope == "selected":
        for sid in shot_ids or []:
            shot = s.get(FilmShot, sid)
            if shot is None:
                continue
            _set_pin(s, shot, asset, v.id)
            updated_shots.append(shot.id)
    elif scope in ("future", "project"):
        if project_id is None and from_shot_id is not None:
            fs = s.get(FilmShot, from_shot_id)
            project_id = fs.project_id if fs else None
        if project_id is None:
            raise AssetError("project_id (or from_shot_id) is required")
        ordered = _ordered_shots(s, project_id)
        start = 0
        if scope == "future":
            if from_shot_id is None:
                raise AssetError("from_shot_id is required for scope=future")
            idx = next((i for i, (sh, _) in enumerate(ordered) if sh.id == from_shot_id), None)
            if idx is None:
                raise AssetError("from_shot_id is not in this project")
            start = idx
            # earlier shots in the SAME scene keep what they effectively use today
            from_scene_id = ordered[idx][0].scene_id
            for sh, sc in ordered[:idx]:
                if sh.scene_id != from_scene_id:
                    continue
                pin = s.execute(select(FilmShotAsset).where(
                    FilmShotAsset.shot_id == sh.id, FilmShotAsset.asset_id == asset.id)).scalar_one_or_none()
                if pin is None:
                    entry = _scene_uses(sc, asset.id)
                    if entry and entry.get("version_id"):
                        _set_pin(s, sh, asset, int(entry["version_id"]), entry.get("role"))
        touched_scenes: set[int] = set()
        for sh, sc in ordered[start:]:
            pin = s.execute(select(FilmShotAsset).where(
                FilmShotAsset.shot_id == sh.id, FilmShotAsset.asset_id == asset.id)).scalar_one_or_none()
            if pin is not None:
                if pin.version_id != v.id:
                    pin.version_id = v.id
                    updated_shots.append(sh.id)
            elif sc is not None and _scene_uses(sc, asset.id) and sc.id not in touched_scenes:
                touched_scenes.add(sc.id)
                _set_scene_version(s, sc, asset.id, v.id)
                updated_scenes.append(sc.id)
        # scenes with the asset in defaults but no shots at all (future scenes)
        if scope == "project":
            for sc in s.execute(select(FilmScene).where(FilmScene.project_id == project_id)).scalars():
                if _scene_uses(sc, asset.id) and sc.id not in touched_scenes:
                    _set_scene_version(s, sc, asset.id, v.id)
                    updated_scenes.append(sc.id)
    else:
        raise AssetError("scope must be selected | future | project")

    if updated_shots or updated_scenes:
        freeze_version(s, v, "pinned by shots")
    s.flush()
    events.log(s, project_id, f"{asset.name}: v{v.number} applied to {scope} shots", kind="edit",
               actor=actor, entity=("asset", asset.id),
               data={"version_id": v.id, "scope": scope, "shots": updated_shots,
                     "scenes": updated_scenes})
    return {"version_id": v.id, "updated_shots": updated_shots, "updated_scenes": updated_scenes}


# ------------------------------------------------------------- listing -----
def list_assets(s: Session, type: str | None = None, q: str | None = None,
                tag: str | None = None, project_id: int | None = None,
                favorite: bool | None = None, owner_asset_id: int | None = None,
                include_children: bool = False, limit: int = 500) -> list[FilmAsset]:
    stmt = select(FilmAsset)
    if type:
        stmt = stmt.where(FilmAsset.type == type)
    if owner_asset_id is not None:
        stmt = stmt.where(FilmAsset.owner_asset_id == owner_asset_id)
    elif not include_children:
        stmt = stmt.where(FilmAsset.owner_asset_id.is_(None))
    if project_id is not None:
        stmt = stmt.where((FilmAsset.project_id == project_id) | (FilmAsset.project_id.is_(None)))
    if favorite:
        stmt = stmt.where(FilmAsset.favorite.is_(True))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(FilmAsset.name).like(like)
                          | func.lower(func.coalesce(FilmAsset.description, "")).like(like))
    rows = list(s.execute(stmt.order_by(FilmAsset.pinned.desc(), FilmAsset.favorite.desc(),
                                        FilmAsset.updated_at.desc()).limit(limit)).scalars())
    if tag:
        t = tag.strip().lower()
        rows = [a for a in rows if t in (a.tags or [])]
    return rows


# --------------------------------------------------------------- dicts -----
def ref_dict(r: FilmAssetRef) -> dict:
    return {"id": r.id, "asset_id": r.asset_id, "version_id": r.version_id, "kind": r.kind,
            "label": r.label, "url": storage.url_for(r.path),
            "thumb_url": storage.url_for(r.thumb_path) or storage.url_for(r.path),
            "width": r.width, "height": r.height, "sha256": r.sha256, "source": r.source,
            "source_post_id": r.source_post_id, "provenance": r.provenance or {},
            "created_at": r.created_at.isoformat() if r.created_at else None}


def version_dict(s: Session, v: FilmAssetVersion, refs: list[FilmAssetRef] | None = None,
                 usage: bool = False) -> dict:
    refs = refs if refs is not None else refs_visible(s, v.asset_id, v.id)
    primary = next((r for r in refs if r.id == v.primary_ref_id), refs[0] if refs else None)
    d = {"id": v.id, "asset_id": v.asset_id, "number": v.number,
         "label": v.label or f"v{v.number}", "data": v.data or {}, "locks": list(v.locks or []),
         "identity_anchors": list(v.identity_anchors or []),
         "continuity_rules": list(v.continuity_rules or []),
         "negative_constraints": list(v.negative_constraints or []),
         "primary_ref_id": primary.id if primary else None,
         "primary_thumb_url": ref_dict(primary)["thumb_url"] if primary else None,
         "frozen": bool(v.frozen), "provenance": v.provenance or {}, "note": v.note,
         "refs": [ref_dict(r) for r in refs],
         "created_at": v.created_at.isoformat() if v.created_at else None,
         "updated_at": v.updated_at.isoformat() if v.updated_at else None}
    if usage:
        d["usage"] = version_usage(s, v.id)
    return d


def asset_dict(s: Session, a: FilmAsset, include_versions: bool = False,
               include_usage: bool = False, include_context: bool = False,
               include_children: bool = True) -> dict:
    cur = current_version(s, a)
    refs_all = list(s.execute(select(FilmAssetRef).where(FilmAssetRef.asset_id == a.id)
                              .order_by(FilmAssetRef.id.asc())).scalars())
    cur_refs = [r for r in refs_all if r.version_id is None or r.version_id == cur.id]
    cur_d = version_dict(s, cur, cur_refs)
    versions = versions_of(s, a.id)
    d = {"id": a.id, "type": a.type, "name": a.name, "description": a.description,
         "tags": list(a.tags or []), "notes": a.notes, "favorite": bool(a.favorite),
         "pinned": bool(a.pinned), "approved": bool(a.approved), "project_id": a.project_id,
         "owner_asset_id": a.owner_asset_id, "provenance": a.provenance or {},
         "current_version_id": cur.id, "current_version": cur_d,
         "version_count": len(versions), "ref_count": len(refs_all),
         "thumb_url": cur_d["primary_thumb_url"],
         "created_at": a.created_at.isoformat() if a.created_at else None,
         "updated_at": a.updated_at.isoformat() if a.updated_at else None}
    if include_children and a.type == "character":
        kids = list(s.execute(select(FilmAsset).where(FilmAsset.owner_asset_id == a.id)
                              .order_by(FilmAsset.id.asc())).scalars())
        d["outfits"] = [asset_dict(s, k, include_children=False) for k in kids]
    if include_versions:
        d["versions"] = [version_dict(s, v, [r for r in refs_all if r.version_id is None or r.version_id == v.id],
                                      usage=include_usage) for v in versions]
    if include_usage:
        d["usage"] = asset_usage(s, a.id)
    if include_context:
        d["context"] = ctx_mod.build(a, cur, cur_refs)
    return d


def context_for(s: Session, a: FilmAsset, version_id: int | None = None) -> dict:
    v = s.get(FilmAssetVersion, version_id) if version_id else current_version(s, a)
    if v is None or v.asset_id != a.id:
        raise AssetError("version not found")
    return ctx_mod.build(a, v, refs_visible(s, a.id, v.id))
