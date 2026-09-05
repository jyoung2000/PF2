"""Film Studio API (S1: assets · versions · references · projects · scenes ·
shots). Later phases add director, takes, timeline, QA and export routes to
this same router. Conventions match the rest of the API: sync endpoints,
plain-dict responses, 404 for unknown ids, 409 for state conflicts, 422 for
bad input."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..film import assets as asset_svc
from ..film import attributes, events
from ..film import projects as proj_svc
from ..film import refs as ref_svc
from ..film import storage
from ..film.models import (ASSET_TYPES, MEDIA_STRATEGIES, FilmAsset, FilmAssetRef,
                           FilmProject, FilmScene, FilmShot)

router = APIRouter(prefix="/api/film", tags=["film"])


def _asset(db: Session, asset_id: int) -> FilmAsset:
    a = db.get(FilmAsset, asset_id)
    if a is None:
        raise HTTPException(404, "Asset not found")
    return a


def _project(db: Session, project_id: int) -> FilmProject:
    p = db.get(FilmProject, project_id)
    if p is None:
        raise HTTPException(404, "Project not found")
    return p


def _scene(db: Session, scene_id: int) -> FilmScene:
    sc = db.get(FilmScene, scene_id)
    if sc is None:
        raise HTTPException(404, "Scene not found")
    return sc


def _shot(db: Session, shot_id: int) -> FilmShot:
    sh = db.get(FilmShot, shot_id)
    if sh is None:
        raise HTTPException(404, "Shot not found")
    return sh


def _guard(fn, *args, **kw):
    """Map service errors onto HTTP codes."""
    try:
        return fn(*args, **kw)
    except asset_svc.AssetInUse as e:
        raise HTTPException(409, str(e))
    except (asset_svc.AssetError, ref_svc.RefError, proj_svc.ProjectError, ValueError) as e:
        raise HTTPException(422, str(e))


# ------------------------------------------------------------------ schema --
@router.get("/schema")
def schema():
    return {"asset_types": list(ASSET_TYPES), "schemas": attributes.public_schema(),
            "media_strategies": list(MEDIA_STRATEGIES),
            "transition_kinds": list(proj_svc.TRANSITION_KINDS),
            "shot_statuses": list(proj_svc.SHOT_STATUSES),
            "project_statuses": list(proj_svc.PROJECT_STATUSES),
            "default_settings": proj_svc.DEFAULT_SETTINGS}


# ------------------------------------------------------------------ assets --
class AssetCreate(BaseModel):
    type: str
    name: str
    description: str | None = None
    tags: list[str] = []
    data: dict = {}
    locks: list[str] | None = None
    continuity_rules: list[str] = []
    negative_constraints: list[str] = []
    identity_anchors: list[str] = []
    project_id: int | None = None
    owner_asset_id: int | None = None
    provenance: dict | None = None
    notes: str | None = None


class AssetPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    favorite: bool | None = None
    pinned: bool | None = None
    approved: bool | None = None
    project_id: int | None = None


@router.get("/assets")
def list_assets(type: str | None = None, q: str | None = None, tag: str | None = None,
                project_id: int | None = None, favorite: bool = False,
                owner_asset_id: int | None = None, db: Session = Depends(get_db)):
    if type and type not in ASSET_TYPES:
        raise HTTPException(422, f"unknown asset type {type!r}")
    rows = asset_svc.list_assets(db, type=type, q=q, tag=tag, project_id=project_id,
                                 favorite=favorite or None, owner_asset_id=owner_asset_id)
    return {"assets": [asset_svc.asset_dict(db, a, include_children=False) for a in rows]}


@router.post("/assets")
def create_asset(body: AssetCreate, db: Session = Depends(get_db)):
    a = _guard(asset_svc.create_asset, db, body.type, body.name, description=body.description,
               tags=body.tags, data=body.data, locks=body.locks,
               continuity_rules=body.continuity_rules,
               negative_constraints=body.negative_constraints,
               identity_anchors=body.identity_anchors, project_id=body.project_id,
               owner_asset_id=body.owner_asset_id, provenance=body.provenance, notes=body.notes)
    db.commit()
    return asset_svc.asset_dict(db, a, include_versions=True, include_context=True)


@router.get("/assets/{asset_id}")
def get_asset(asset_id: int, versions: bool = True, usage: bool = True, context: bool = True,
              db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    return asset_svc.asset_dict(db, a, include_versions=versions, include_usage=usage,
                                include_context=context)


@router.patch("/assets/{asset_id}")
def patch_asset(asset_id: int, body: AssetPatch, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    _guard(asset_svc.update_asset, db, a, **body.model_dump(exclude_unset=True))
    db.commit()
    return asset_svc.asset_dict(db, a, include_versions=True, include_usage=True, include_context=True)


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int, force: bool = False, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    _guard(asset_svc.delete_asset, db, a, force=force)
    db.commit()
    return {"deleted": asset_id}


# ---------------------------------------------------------------- versions --
class VersionEdit(BaseModel):
    changes: dict | None = None
    locks: list[str] | None = None
    continuity_rules: list[str] | None = None
    negative_constraints: list[str] | None = None
    identity_anchors: list[str] | None = None
    label: str | None = None
    note: str | None = None
    new_version: bool = False
    reason: str | None = None


@router.get("/assets/{asset_id}/versions")
def list_versions(asset_id: int, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    return {"current_version_id": a.current_version_id,
            "versions": [asset_svc.version_dict(db, v, usage=True) for v in asset_svc.versions_of(db, a.id)]}


@router.post("/assets/{asset_id}/versions")
def edit_version(asset_id: int, body: VersionEdit, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    v, created = _guard(asset_svc.edit_version, db, a, changes=body.changes, locks=body.locks,
                        continuity_rules=body.continuity_rules,
                        negative_constraints=body.negative_constraints,
                        identity_anchors=body.identity_anchors, label=body.label,
                        note=body.note, force_new=body.new_version, reason=body.reason)
    db.commit()
    return {"created": created, "version": asset_svc.version_dict(db, v, usage=True),
            "asset": asset_svc.asset_dict(db, a, include_versions=True, include_context=True)}


@router.get("/assets/{asset_id}/versions/{version_id}")
def get_version(asset_id: int, version_id: int, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    v = asset_svc.get_version(db, version_id)
    if v is None or v.asset_id != a.id:
        raise HTTPException(404, "Version not found")
    return asset_svc.version_dict(db, v, usage=True)


@router.post("/assets/{asset_id}/versions/{version_id}/{action}")
def version_action(asset_id: int, version_id: int, action: str, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    if action == "restore":
        v = _guard(asset_svc.restore_version, db, a, version_id)
    elif action == "duplicate":
        v = _guard(asset_svc.duplicate_version, db, a, version_id)
    elif action == "use":
        v = _guard(asset_svc.use_as_current, db, a, version_id)
    else:
        raise HTTPException(404, "Unknown action (restore | duplicate | use)")
    db.commit()
    return {"version": asset_svc.version_dict(db, v, usage=True),
            "asset": asset_svc.asset_dict(db, a, include_versions=True, include_context=True)}


@router.get("/assets/{asset_id}/compare")
def compare(asset_id: int, a: int, b: int, db: Session = Depends(get_db)):
    _asset(db, asset_id)
    return _guard(asset_svc.compare_versions, db, a, b)


@router.get("/assets/{asset_id}/context")
def asset_context(asset_id: int, version_id: int | None = None, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    from ..film import context as ctx_mod
    ctx = _guard(asset_svc.context_for, db, a, version_id)
    return {"context": ctx, "prose": ctx_mod.describe(ctx)}


class Propagate(BaseModel):
    version_id: int
    scope: str = "selected"          # selected | future | project
    project_id: int | None = None
    shot_ids: list[int] = []
    from_shot_id: int | None = None


@router.post("/assets/{asset_id}/propagate")
def propagate(asset_id: int, body: Propagate, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    result = _guard(asset_svc.propagate_version, db, a, body.version_id, body.scope,
                    project_id=body.project_id, shot_ids=body.shot_ids,
                    from_shot_id=body.from_shot_id)
    db.commit()
    return result


# -------------------------------------------------------------- references --
@router.post("/assets/{asset_id}/refs")
async def upload_ref(asset_id: int, file: UploadFile, kind: str = Form("custom"),
                     label: str | None = Form(None), version_id: int | None = Form(None),
                     primary: bool = Form(False), db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    data = await file.read()
    ref, deduped = _guard(ref_svc.add_reference, db, a, data, file.content_type, file.filename,
                          kind=kind, label=label, version_id=version_id, make_primary=primary)
    db.commit()
    return {"ref": asset_svc.ref_dict(ref), "deduped": deduped}


class RefImport(BaseModel):
    post_id: int
    kind: str = "custom"
    label: str | None = None
    version_id: int | None = None
    primary: bool = False


@router.post("/assets/{asset_id}/refs/import")
def import_ref(asset_id: int, body: RefImport, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    ref, deduped = _guard(ref_svc.import_from_post, db, a, body.post_id, kind=body.kind,
                          label=body.label, version_id=body.version_id, make_primary=body.primary)
    db.commit()
    return {"ref": asset_svc.ref_dict(ref), "deduped": deduped}


def _ref(db: Session, ref_id: int) -> FilmAssetRef:
    r = db.get(FilmAssetRef, ref_id)
    if r is None:
        raise HTTPException(404, "Reference not found")
    return r


@router.get("/refs/{ref_id}/file")
def ref_file(ref_id: int, thumb: bool = False, db: Session = Depends(get_db)):
    r = _ref(db, ref_id)
    rel = (r.thumb_path if thumb and r.thumb_path else r.path)
    try:
        path = storage.resolve(rel)
    except storage.UnsafePath:
        raise HTTPException(404, "Reference file missing")
    if not path.is_file():
        raise HTTPException(404, "Reference file missing on disk")
    return FileResponse(path)


class RefPatch(BaseModel):
    kind: str | None = None
    label: str | None = None


@router.patch("/refs/{ref_id}")
def patch_ref(ref_id: int, body: RefPatch, db: Session = Depends(get_db)):
    r = _ref(db, ref_id)
    ref_svc.update_reference(db, r, kind=body.kind, label=body.label)
    db.commit()
    return asset_svc.ref_dict(r)


@router.post("/refs/{ref_id}/primary")
def make_primary(ref_id: int, version_id: int | None = None, db: Session = Depends(get_db)):
    r = _ref(db, ref_id)
    a = _asset(db, r.asset_id)
    v = _guard(ref_svc.set_primary, db, a, r, version_id)
    db.commit()
    return {"version_id": v.id, "primary_ref_id": v.primary_ref_id}


@router.delete("/refs/{ref_id}")
def delete_ref(ref_id: int, db: Session = Depends(get_db)):
    r = _ref(db, ref_id)
    ref_svc.remove_reference(db, r)
    db.commit()
    return {"deleted": ref_id}


# ---------------------------------------------------------------- projects --
class ProjectCreate(BaseModel):
    title: str
    logline: str | None = None
    synopsis: str | None = None
    script: str | None = None
    settings: dict | None = None


class ProjectPatch(BaseModel):
    title: str | None = None
    logline: str | None = None
    synopsis: str | None = None
    script: str | None = None
    status: str | None = None
    settings: dict | None = None


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    return {"projects": proj_svc.list_projects(db)}


@router.post("/projects")
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    p = _guard(proj_svc.create_project, db, body.title, logline=body.logline,
               synopsis=body.synopsis, script=body.script, settings=body.settings)
    db.commit()
    return proj_svc.project_dict(db, p, deep=True)


@router.get("/projects/{project_id}")
def get_project(project_id: int, deep: bool = True, db: Session = Depends(get_db)):
    return proj_svc.project_dict(db, _project(db, project_id), deep=deep)


@router.patch("/projects/{project_id}")
def patch_project(project_id: int, body: ProjectPatch, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    _guard(proj_svc.update_project, db, p, **body.model_dump(exclude_unset=True))
    db.commit()
    return proj_svc.project_dict(db, p, deep=True)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    proj_svc.delete_project(db, p)
    db.commit()
    return {"deleted": project_id}


@router.get("/projects/{project_id}/events")
def project_events(project_id: int, kind: str | None = None, limit: int = 200,
                   ascending: bool = False, db: Session = Depends(get_db)):
    _project(db, project_id)
    return {"events": events.list_events(db, project_id, kind=kind, limit=limit, ascending=ascending)}


# ------------------------------------------------------------------ scenes --
class SceneBody(BaseModel):
    title: str | None = None
    position: int | None = None
    act: str | None = None
    intent: str | None = None
    summary: str | None = None
    script_text: str | None = None
    defaults: dict | None = None
    gap_after_s: float | None = None
    transition: dict | str | None = None
    approved: bool | None = None


class Ids(BaseModel):
    ids: list[int]


@router.post("/projects/{project_id}/scenes")
def create_scene(project_id: int, body: SceneBody, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    fields = body.model_dump(exclude_unset=True)
    title = fields.pop("title", None)
    position = fields.pop("position", None)
    sc = _guard(proj_svc.create_scene, db, p, title=title, position=position, **fields)
    db.commit()
    return proj_svc.scene_dict(db, sc)


@router.post("/projects/{project_id}/scenes/reorder")
def reorder_scenes(project_id: int, body: Ids, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    rows = proj_svc.reorder_scenes(db, p, body.ids)
    db.commit()
    return {"scenes": [proj_svc.scene_dict(db, sc, include_shots=False) for sc in rows]}


@router.get("/scenes/{scene_id}")
def get_scene(scene_id: int, db: Session = Depends(get_db)):
    return proj_svc.scene_dict(db, _scene(db, scene_id))


@router.patch("/scenes/{scene_id}")
def patch_scene(scene_id: int, body: SceneBody, db: Session = Depends(get_db)):
    sc = _scene(db, scene_id)
    fields = body.model_dump(exclude_unset=True)
    fields.pop("position", None)
    _guard(proj_svc.update_scene, db, sc, **fields)
    db.commit()
    return proj_svc.scene_dict(db, sc)


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: int, db: Session = Depends(get_db)):
    sc = _scene(db, scene_id)
    proj_svc.delete_scene(db, sc)
    db.commit()
    return {"deleted": scene_id}


# ------------------------------------------------------------------- shots --
class ShotBody(BaseModel):
    title: str | None = None
    position: int | None = None
    status: str | None = None
    duration_s: float | None = None
    transition: dict | str | None = None
    media_strategy: str | None = None
    overrides: dict | None = None
    locks: list[str] | None = None
    start_frame: dict | None = None
    end_frame: dict | None = None
    chain_from_previous: bool | None = None
    approved: bool | None = None
    selected_take_id: int | None = None
    notes: str | None = None
    assets: list[dict] | None = None


@router.post("/scenes/{scene_id}/shots")
def create_shot(scene_id: int, body: ShotBody, db: Session = Depends(get_db)):
    sc = _scene(db, scene_id)
    fields = body.model_dump(exclude_unset=True)
    title = fields.pop("title", None)
    position = fields.pop("position", None)
    duration = fields.pop("duration_s", None)
    sh = _guard(proj_svc.create_shot, db, sc, title=title, position=position,
                duration_s=duration, **fields)
    db.commit()
    return proj_svc.shot_dict(db, sh, sc)


@router.post("/scenes/{scene_id}/shots/reorder")
def reorder_shots(scene_id: int, body: Ids, db: Session = Depends(get_db)):
    sc = _scene(db, scene_id)
    rows = proj_svc.reorder_shots(db, sc, body.ids)
    db.commit()
    return {"shots": [proj_svc.shot_dict(db, sh, sc) for sh in rows]}


@router.get("/shots/{shot_id}")
def get_shot(shot_id: int, takes: bool = True, db: Session = Depends(get_db)):
    return proj_svc.shot_dict(db, _shot(db, shot_id), include_takes=takes)


@router.patch("/shots/{shot_id}")
def patch_shot(shot_id: int, body: ShotBody, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    fields = body.model_dump(exclude_unset=True)
    fields.pop("position", None)
    _guard(proj_svc.update_shot, db, sh, **fields)
    db.commit()
    return proj_svc.shot_dict(db, sh, include_takes=True)


@router.delete("/shots/{shot_id}")
def delete_shot(shot_id: int, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    proj_svc.delete_shot(db, sh)
    db.commit()
    return {"deleted": shot_id}


@router.post("/shots/{shot_id}/duplicate")
def duplicate_shot(shot_id: int, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    new = proj_svc.duplicate_shot(db, sh)
    db.commit()
    return proj_svc.shot_dict(db, new)


class MoveBody(BaseModel):
    scene_id: int
    position: int | None = None


@router.post("/shots/{shot_id}/move")
def move_shot(shot_id: int, body: MoveBody, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    _guard(proj_svc.move_shot, db, sh, body.scene_id, body.position)
    db.commit()
    return proj_svc.shot_dict(db, sh)


class PinBody(BaseModel):
    asset_id: int
    version_id: int | None = None
    role: str | None = None
    notes: str | None = None


@router.post("/shots/{shot_id}/assets")
def pin_shot_asset(shot_id: int, body: PinBody, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    a = _asset(db, body.asset_id)
    _guard(proj_svc.pin_asset, db, sh, a, body.version_id, body.role, body.notes)
    db.commit()
    return proj_svc.shot_dict(db, sh)


@router.delete("/shots/{shot_id}/assets/{asset_id}")
def unpin_shot_asset(shot_id: int, asset_id: int, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    removed = proj_svc.unpin_asset(db, sh, asset_id)
    db.commit()
    return {"removed": removed, "shot": proj_svc.shot_dict(db, sh)}


# ============================================================ Phase S2 =====
# story import · presets · director proposals · shot context · timeline ·
# continuity · gates · board · jobs
from ..film import board as board_svc          # noqa: E402
from ..film import continuity, director, gates  # noqa: E402
from ..film import jobs as job_svc              # noqa: E402
from ..film import presets as preset_svc        # noqa: E402
from ..film import shotctx, story, timeline     # noqa: E402
from ..film.models import FilmJob               # noqa: E402
from ..llm.client import BudgetExceeded, LLMError  # noqa: E402


def _director_guard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except BudgetExceeded as e:
        raise HTTPException(429, str(e))
    except LLMError as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


# ------------------------------------------------------------------ story --
class ScriptImport(BaseModel):
    text: str
    mode: str = "replace"     # replace | append


@router.post("/projects/{project_id}/story/import")
def import_story(project_id: int, body: ScriptImport, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    if not body.text.strip():
        raise HTTPException(422, "Paste or type a script first.")
    scenes = story.import_script(db, p, body.text, mode="replace" if body.mode == "replace" else "append")
    db.commit()
    return {"project": proj_svc.project_dict(db, p, deep=True), "scene_ids": [sc.id for sc in scenes]}


@router.post("/story/parse")
def parse_story(body: ScriptImport):
    return {"scenes": [sc.to_dict() for sc in story.parse_script(body.text)]}


# ---------------------------------------------------------------- presets --
@router.get("/presets")
def get_presets(db: Session = Depends(get_db)):
    return preset_svc.merged(db)


class PresetsBody(BaseModel):
    favorites: list[str] | None = None
    shot_type_overrides: dict | None = None
    custom_shot_types: list[dict] | None = None


@router.put("/presets")
def put_presets(body: PresetsBody, db: Session = Depends(get_db)):
    out = preset_svc.save_user(db, body.model_dump(exclude_unset=True))
    db.commit()
    return out


@router.get("/presets/duration")
def suggest_duration(shot_type: str | None = None, profile: str = "normal", dialogue_words: int = 0,
                     complexity: float = 1.0, importance: float = 1.0):
    return {"duration_s": preset_svc.propose_duration(shot_type, profile, dialogue_words, complexity, importance)}


# --------------------------------------------------------------- director --
class DirectBody(BaseModel):
    use_llm: bool = True


class DirectShotBody(BaseModel):
    instruction: str
    use_llm: bool = True


@router.post("/projects/{project_id}/director/story")
def director_story(project_id: int, body: DirectBody | None = None, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    job = _director_guard(director.direct_story, db, p, use_llm=(body.use_llm if body else True))
    db.commit()
    return director.proposal_dict(job)


@router.post("/projects/{project_id}/director/plan")
def director_plan(project_id: int, body: DirectBody | None = None, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    job = _director_guard(director.production_plan, db, p, use_llm=(body.use_llm if body else True))
    db.commit()
    return director.proposal_dict(job)


@router.post("/scenes/{scene_id}/director")
def director_scene(scene_id: int, body: DirectBody | None = None, db: Session = Depends(get_db)):
    sc = _scene(db, scene_id)
    job = _director_guard(director.direct_scene, db, sc, use_llm=(body.use_llm if body else True))
    db.commit()
    return director.proposal_dict(job)


@router.post("/shots/{shot_id}/director")
def director_shot(shot_id: int, body: DirectShotBody, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    if not body.instruction.strip():
        raise HTTPException(422, "Tell the Director what to change.")
    job = _director_guard(director.direct_shot, db, sh, body.instruction, use_llm=body.use_llm)
    db.commit()
    return director.proposal_dict(job)


@router.get("/projects/{project_id}/proposals")
def list_proposals(project_id: int, pending: bool = False, db: Session = Depends(get_db)):
    _project(db, project_id)
    return {"proposals": director.list_proposals(db, project_id, pending_only=pending)}


def _proposal(db: Session, job_id: int) -> FilmJob:
    j = db.get(FilmJob, job_id)
    if j is None or j.kind not in director.PROPOSAL_KINDS:
        raise HTTPException(404, "Proposal not found")
    return j


@router.get("/proposals/{job_id}")
def get_proposal(job_id: int, db: Session = Depends(get_db)):
    return director.proposal_dict(_proposal(db, job_id))


class AcceptBody(BaseModel):
    edits: dict | None = None
    mode: str = "append"      # append | replace (story/scene proposals)


@router.post("/proposals/{job_id}/accept")
def accept_proposal(job_id: int, body: AcceptBody | None = None, db: Session = Depends(get_db)):
    j = _proposal(db, job_id)
    body = body or AcceptBody()
    result = _director_guard(director.apply, db, j, edits=body.edits,
                             mode="replace" if body.mode == "replace" else "append")
    db.commit()
    return {"result": result, "proposal": director.proposal_dict(j)}


class RejectBody(BaseModel):
    note: str | None = None


@router.post("/proposals/{job_id}/reject")
def reject_proposal(job_id: int, body: RejectBody | None = None, db: Session = Depends(get_db)):
    j = _proposal(db, job_id)
    out = _director_guard(director.reject, db, j, note=(body.note if body else None))
    db.commit()
    return out


class PlanBody(BaseModel):
    plan: dict


@router.put("/projects/{project_id}/plan")
def put_plan(project_id: int, body: PlanBody, db: Session = Depends(get_db)):
    """Direct edit of the production plan (no proposal round-trip)."""
    p = _project(db, project_id)
    plan = {**(p.plan or {}), **{k: v for k, v in body.plan.items() if k not in ("approved", "approved_at")}}
    plan["approved"] = False
    p.plan = plan
    g = gates._row(db, p.id, "plan", None)
    if g is not None and g.status == "approved":
        g.status = "pending"
        g.decided_at = None
    events.log(db, p.id, "Production plan edited", kind="edit", stage="plan", entity=("project", p.id),
               data={"keys": sorted(body.plan.keys())})
    db.commit()
    return proj_svc.project_dict(db, p)


@router.get("/projects/{project_id}/estimate")
def project_estimate(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    shots = [{"label": f"{sc.position + 1}.{sh.position + 1}", "duration_s": sh.duration_s,
              "media_strategy": sh.media_strategy} for sh, sc in proj_svc.ordered_shots(db, p.id)]
    return director.estimate_costs(db, shots)


# ------------------------------------------------------------ shot context --
@router.get("/shots/{shot_id}/context")
def shot_context(shot_id: int, kind: str = "video", db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    ctx = shotctx.effective_context(db, sh)
    return {"context": ctx, "prompt": shotctx.build_prompt(ctx, kind=kind)}


class RegenBody(BaseModel):
    change: list[str] = []
    preserve: list[str] = []
    instruction: str | None = None
    kind: str = "video"


@router.post("/shots/{shot_id}/context/regeneration")
def shot_regeneration_prompt(shot_id: int, body: RegenBody, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    ctx = shotctx.effective_context(db, sh)
    return shotctx.regeneration_prompt(ctx, body.change, body.preserve, body.instruction, body.kind)


# ---------------------------------------------------------------- timeline --
@router.get("/projects/{project_id}/timeline")
def get_timeline(project_id: int, db: Session = Depends(get_db)):
    return timeline.compute(db, _project(db, project_id))


class GapBody(BaseModel):
    default_gap_s: float | None = None
    apply_to_all: float | None = None
    reset_overrides: bool = False


@router.post("/projects/{project_id}/timeline/gap")
def set_gap(project_id: int, body: GapBody, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    out = None
    if body.default_gap_s is not None:
        out = timeline.set_default_gap(db, p, body.default_gap_s, reset_overrides=body.reset_overrides)
    if body.apply_to_all is not None:
        out = timeline.apply_gap_to_all(db, p, body.apply_to_all)
    if out is None:
        raise HTTPException(422, "Send default_gap_s and/or apply_to_all.")
    db.commit()
    return out


class SceneGapBody(BaseModel):
    gap_after_s: float | None = None


@router.post("/scenes/{scene_id}/gap")
def set_scene_gap(scene_id: int, body: SceneGapBody, db: Session = Depends(get_db)):
    sc = _scene(db, scene_id)
    out = timeline.set_scene_gap(db, sc, body.gap_after_s)
    db.commit()
    return out


# -------------------------------------------------------------- continuity --
@router.post("/projects/{project_id}/continuity")
def run_continuity(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    out = continuity.validate_project(db, p)
    db.commit()
    return out


# ------------------------------------------------------------------- gates --
@router.get("/projects/{project_id}/gates")
def list_gates(project_id: int, db: Session = Depends(get_db)):
    return {"gates": gates.list_gates(db, _project(db, project_id))}


class GateBody(BaseModel):
    status: str                     # approved | rejected | pending
    scene_id: int | None = None
    note: str | None = None
    item_ids: list[int] = []


@router.post("/projects/{project_id}/gates/{kind}")
def decide_gate(project_id: int, kind: str, body: GateBody, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    out = _guard(gates.decide, db, p, kind, body.status, scene_id=body.scene_id, note=body.note,
                 item_ids=body.item_ids)
    db.commit()
    return out


# ------------------------------------------------------------------- board --
@router.get("/projects/{project_id}/board")
def get_board(project_id: int, db: Session = Depends(get_db)):
    return board_svc.board(db, _project(db, project_id))


@router.get("/projects/{project_id}/replay")
def get_replay(project_id: int, limit: int = 500, db: Session = Depends(get_db)):
    return board_svc.replay(db, _project(db, project_id), limit=limit)


# -------------------------------------------------------------------- jobs --
@router.get("/projects/{project_id}/jobs")
def list_jobs(project_id: int, db: Session = Depends(get_db)):
    _project(db, project_id)
    rows = db.execute(select(FilmJob).where(FilmJob.project_id == project_id,
                                            FilmJob.kind.not_in(director.PROPOSAL_KINDS))
                      .order_by(FilmJob.id.desc()).limit(50)).scalars()
    return {"jobs": [board_svc.job_dict(j) for j in rows]}


def _job(db: Session, job_id: int) -> FilmJob:
    j = db.get(FilmJob, job_id)
    if j is None:
        raise HTTPException(404, "Job not found")
    return j


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    return board_svc.job_dict(_job(db, job_id))


@router.post("/jobs/{job_id}/{action}")
def job_action(job_id: int, action: str, db: Session = Depends(get_db)):
    j = _job(db, job_id)
    if action == "pause":
        job_svc.pause(db, j)
    elif action == "resume":
        job_svc.resume(db, j)
    elif action == "cancel":
        job_svc.cancel(db, j)
    else:
        raise HTTPException(404, "Unknown action (pause | resume | cancel)")
    db.commit()
    db.refresh(j)
    return board_svc.job_dict(j)
