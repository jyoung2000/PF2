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


# ============================================================ Phase S3 =====
# capabilities · costs · takes · frames · local media · footage · audio ·
# subtitles · QA/repair · runs · export · reference video
from fastapi.responses import PlainTextResponse  # noqa: E402

from ..film import audio as audio_svc            # noqa: E402
from ..film import capabilities, costs, export as export_svc, footage, graphics, production  # noqa: E402
from ..film import qa as qa_svc                  # noqa: E402
from ..film import reference as reference_svc    # noqa: E402
from ..film import subtitles as sub_svc          # noqa: E402
from ..film import takes as take_svc             # noqa: E402
from ..film.models import FilmAudioTrack, FilmClip, FilmTake  # noqa: E402


def _s3_guard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except costs.BudgetBlocked as e:
        raise HTTPException(409, {"message": str(e), "budget": e.check})
    except production.GateRequired as e:
        raise HTTPException(409, {"message": str(e), "missing_gates": e.missing})
    except take_svc.TakeBlocked as e:
        raise HTTPException(409, {"message": str(e)})
    except (take_svc.TakeError, footage.FootageError, audio_svc.AudioError, export_svc.ExportError,
            reference_svc.ReferenceError, proj_svc.ProjectError, ValueError) as e:
        raise HTTPException(422, str(e))


def _take(db: Session, take_id: int) -> FilmTake:
    t = db.get(FilmTake, take_id)
    if t is None:
        raise HTTPException(404, "Take not found")
    return t


# ------------------------------------------------------------ capabilities -
@router.get("/capabilities")
def get_capabilities(db: Session = Depends(get_db)):
    return capabilities.matrix(db)


@router.get("/projects/{project_id}/costs")
def project_costs(project_id: int, db: Session = Depends(get_db)):
    return costs.spend(db, _project(db, project_id))


class CostCheck(BaseModel):
    amount_usd: float | None = None
    approve: bool = False


@router.post("/projects/{project_id}/costs/check")
def project_cost_check(project_id: int, body: CostCheck, db: Session = Depends(get_db)):
    return costs.check(db, _project(db, project_id), body.amount_usd, approve=body.approve)


# ------------------------------------------------------------------- takes -
class TakeBody(BaseModel):
    kind: str = "video"
    mode: str | None = None
    family: str | None = None
    provider: str | None = None
    params: dict = {}
    change: list[str] = []
    preserve: list[str] = []
    instruction: str | None = None
    approve_cost: bool = False


@router.post("/shots/{shot_id}/takes")
def create_take(shot_id: int, body: TakeBody, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    t = _s3_guard(take_svc.create_take, db, sh, kind=body.kind, mode=body.mode, family=body.family,
                  provider=body.provider, params=body.params, change=body.change, preserve=body.preserve,
                  instruction=body.instruction, approve_cost=body.approve_cost)
    db.commit()
    return {"take": proj_svc.take_dict(t), "shot": proj_svc.shot_dict(db, sh, include_takes=True)}


@router.get("/shots/{shot_id}/takes")
def list_takes(shot_id: int, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    take_svc.sync_pending(db, sh.project_id)
    db.commit()
    return {"takes": [proj_svc.take_dict(t) for t in take_svc.takes_of(db, sh.id)],
            "selected_take_id": sh.selected_take_id}


@router.post("/shots/{shot_id}/takes/import")
async def import_take(shot_id: int, file: UploadFile, kind: str = Form("footage"), select: bool = Form(True),
                      db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    data = await file.read()
    t = _s3_guard(take_svc.import_take, db, sh, data, file.content_type, file.filename, kind=kind,
                  select=select)
    db.commit()
    return {"take": proj_svc.take_dict(t), "shot": proj_svc.shot_dict(db, sh, include_takes=True)}


@router.get("/takes/{take_id}")
def get_take(take_id: int, db: Session = Depends(get_db)):
    return proj_svc.take_dict(_take(db, take_id))


@router.post("/takes/{take_id}/select")
def select_take(take_id: int, db: Session = Depends(get_db)):
    t = _take(db, take_id)
    sh = _shot(db, t.shot_id)
    _s3_guard(take_svc.select_take, db, sh, t)
    db.commit()
    return proj_svc.shot_dict(db, sh, include_takes=True)


@router.get("/takes/{take_id}/compare/{other_id}")
def compare_takes(take_id: int, other_id: int, db: Session = Depends(get_db)):
    return take_svc.compare(db, _take(db, take_id), _take(db, other_id))


@router.post("/takes/{take_id}/qa")
def take_qa(take_id: int, db: Session = Depends(get_db)):
    t = _take(db, take_id)
    t.qa = qa_svc.check_take(db, t)
    sh = _shot(db, t.shot_id)
    if sh.selected_take_id == t.id:
        sh.qa = t.qa
    db.commit()
    return t.qa


# ------------------------------------------------------------------ frames -
class FrameBody(BaseModel):
    kind: str                       # previous_shot | post | ref | clear | lock
    post_id: int | None = None
    ref_id: int | None = None
    locked: bool | None = None


@router.post("/shots/{shot_id}/frames/{which}")
def set_frame(shot_id: int, which: str, body: FrameBody, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    if which not in take_svc.FRAME_KINDS:
        raise HTTPException(404, "which must be start_frame | end_frame")
    if body.kind == "previous_shot":
        _s3_guard(take_svc.use_previous_last_frame, db, sh)
    elif body.kind == "post" and body.post_id:
        _s3_guard(take_svc.frame_from_post, db, sh, which, body.post_id)
    elif body.kind == "ref" and body.ref_id:
        _s3_guard(take_svc.frame_from_ref, db, sh, which, body.ref_id)
    elif body.kind == "clear":
        take_svc.set_frame(db, sh, which, None)
    elif body.kind == "lock":
        frame = dict(getattr(sh, which) or {})
        if not frame:
            raise HTTPException(422, "No frame to lock yet.")
        frame["locked"] = bool(body.locked) if body.locked is not None else not frame.get("locked")
        take_svc.set_frame(db, sh, which, frame)
    else:
        raise HTTPException(422, "kind must be previous_shot | post | ref | clear | lock")
    db.commit()
    return proj_svc.shot_dict(db, sh)


@router.post("/shots/{shot_id}/frames/{which}/upload")
async def upload_frame(shot_id: int, which: str, file: UploadFile, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    if which not in take_svc.FRAME_KINDS:
        raise HTTPException(404, "which must be start_frame | end_frame")
    data = await file.read()
    _s3_guard(take_svc.store_frame_upload, db, sh, which, data, file.content_type, file.filename)
    db.commit()
    return proj_svc.shot_dict(db, sh)


@router.post("/shots/{shot_id}/frames/{which}/generate")
def generate_frame(shot_id: int, which: str, body: TakeBody | None = None, db: Session = Depends(get_db)):
    sh = _shot(db, shot_id)
    if which not in take_svc.FRAME_KINDS:
        raise HTTPException(404, "which must be start_frame | end_frame")
    body = body or TakeBody()
    t = _s3_guard(take_svc.create_take, db, sh, kind=which, mode=body.mode, family=body.family,
                  provider=body.provider, params=body.params, instruction=body.instruction,
                  approve_cost=body.approve_cost)
    db.commit()
    return {"take": proj_svc.take_dict(t), "shot": proj_svc.shot_dict(db, sh, include_takes=True)}


# ------------------------------------------------------------- local media -
class StillBody(BaseModel):
    source: str = "start_frame"     # start_frame | end_frame | post | ref
    post_id: int | None = None
    ref_id: int | None = None


@router.post("/shots/{shot_id}/still")
def still_take(shot_id: int, body: StillBody, db: Session = Depends(get_db)):
    """Ken Burns still → video take (local, free)."""
    sh = _shot(db, shot_id)
    if body.source in take_svc.FRAME_KINDS:
        src = take_svc.frame_path(getattr(sh, body.source))
    elif body.source == "post" and body.post_id:
        from ..models import Post
        post = db.get(Post, body.post_id)
        src = take_svc.abs_path(post.media_path if post and post.media_type == "image" else (post.thumb_path if post else None))
    elif body.source == "ref" and body.ref_id:
        r = db.get(FilmAssetRef, body.ref_id)
        src = take_svc.abs_path(r.path) if r else None
    else:
        src = None
    if src is None:
        raise HTTPException(422, "No image found for that source.")
    settings = proj_svc.merge_settings(_project(db, sh.project_id).settings, None)
    rel = storage.project_rel(sh.project_id, "takes", storage.new_name(".mp4"))
    try:
        graphics.still_video(src, storage.resolve(rel), float(sh.duration_s or 4), settings.get("aspect_ratio"),
                             int(settings.get("fps") or 24))
    except Exception as e:
        raise HTTPException(502, f"ffmpeg failed: {e}")
    t = _s3_guard(take_svc.import_take, db, sh, storage.resolve(rel).read_bytes(), "video/mp4", "still.mp4",
                  kind="video", source="still", provenance={"origin": "still", "source": body.source,
                                                             "post_id": body.post_id, "ref_id": body.ref_id})
    storage.remove(rel)
    t.provider, t.mode = "local", "still_to_video"
    if sh.media_strategy == "ai_video":
        sh.media_strategy = "still"
    db.commit()
    return {"take": proj_svc.take_dict(t), "shot": proj_svc.shot_dict(db, sh, include_takes=True)}


class CardBody(BaseModel):
    text: str
    subtitle: str | None = None
    style: str = "title"            # title | lower_third | caption | end_card
    background_post_id: int | None = None
    background_ref_id: int | None = None


@router.post("/shots/{shot_id}/card")
def card_take(shot_id: int, body: CardBody, db: Session = Depends(get_db)):
    """Motion-graphics card take (local, free)."""
    sh = _shot(db, shot_id)
    if not body.text.strip():
        raise HTTPException(422, "Card text is empty.")
    settings = proj_svc.merge_settings(_project(db, sh.project_id).settings, None)
    bg = None
    if body.background_post_id:
        from ..models import Post
        post = db.get(Post, body.background_post_id)
        bg = take_svc.abs_path(post.media_path if post and post.media_type == "image" else (post.thumb_path if post else None))
    elif body.background_ref_id:
        r = db.get(FilmAssetRef, body.background_ref_id)
        bg = take_svc.abs_path(r.path) if r else None
    rel = storage.project_rel(sh.project_id, "takes", storage.new_name(".mp4"))
    try:
        graphics.card_video(body.text.strip(), storage.resolve(rel), float(sh.duration_s or 3), body.subtitle,
                            body.style if body.style in graphics.STYLES else "title", settings.get("aspect_ratio"),
                            int(settings.get("fps") or 24), background=bg)
    except Exception as e:
        raise HTTPException(502, f"ffmpeg failed: {e}")
    t = _s3_guard(take_svc.import_take, db, sh, storage.resolve(rel).read_bytes(), "video/mp4", "card.mp4",
                  kind="graphics", source="card", provenance={"origin": "motion_graphics", "style": body.style,
                                                              "text": body.text[:200]})
    storage.remove(rel)
    t.provider, t.mode = "local", "motion_graphics"
    if sh.media_strategy == "ai_video":
        sh.media_strategy = "motion_graphics"
    db.commit()
    return {"take": proj_svc.take_dict(t), "shot": proj_svc.shot_dict(db, sh, include_takes=True)}


# ----------------------------------------------------------------- footage -
@router.get("/footage/sources")
def footage_sources(db: Session = Depends(get_db)):
    return {"sources": footage.configured_sources(db)}


@router.get("/footage/search")
def footage_search(q: str, media_type: str = "video", sources: str | None = None, db: Session = Depends(get_db)):
    src = [x.strip() for x in sources.split(",") if x.strip()] if sources else None
    return _s3_guard(footage.search, db, q, src, media_type)


class AttachResult(BaseModel):
    shot_id: int
    result: dict


@router.post("/footage/attach")
def footage_attach(body: AttachResult, db: Session = Depends(get_db)):
    sh = _shot(db, body.shot_id)
    clip = _s3_guard(footage.download_result, db, body.result)
    t = _s3_guard(footage.attach_clip, db, sh, clip)
    db.commit()
    return {"clip": footage.clip_dict(clip), "take": proj_svc.take_dict(t),
            "shot": proj_svc.shot_dict(db, sh, include_takes=True)}


@router.post("/footage/upload")
async def footage_upload(file: UploadFile, project_id: int | None = Form(None), title: str | None = Form(None),
                         description: str | None = Form(None), tags: str | None = Form(None),
                         db: Session = Depends(get_db)):
    data = await file.read()
    clip = _s3_guard(footage.import_user_clip, db, data, file.content_type, file.filename, project_id=project_id,
                     title=title, description=description,
                     tags=[t.strip() for t in (tags or "").split(",") if t.strip()])
    db.commit()
    return footage.clip_dict(clip)


@router.get("/footage/clips")
def footage_clips(q: str | None = None, project_id: int | None = None, media_type: str | None = None,
                  db: Session = Depends(get_db)):
    if q:
        return {"results": footage.search_clips(db, q, project_id, media_type)}
    stmt = select(FilmClip).order_by(FilmClip.id.desc()).limit(200)
    if project_id is not None:
        stmt = stmt.where((FilmClip.project_id == project_id) | (FilmClip.project_id.is_(None)))
    return {"clips": [footage.clip_dict(c) for c in db.execute(stmt).scalars()]}


@router.get("/footage/clips/{clip_id}")
def footage_clip(clip_id: int, db: Session = Depends(get_db)):
    c = db.get(FilmClip, clip_id)
    if c is None:
        raise HTTPException(404, "Clip not found")
    return footage.clip_dict(c)


class ClipAttach(BaseModel):
    shot_id: int
    start_s: float | None = None
    end_s: float | None = None


@router.post("/footage/clips/{clip_id}/attach")
def footage_clip_attach(clip_id: int, body: ClipAttach, db: Session = Depends(get_db)):
    c = db.get(FilmClip, clip_id)
    if c is None:
        raise HTTPException(404, "Clip not found")
    sh = _shot(db, body.shot_id)
    t = _s3_guard(footage.attach_clip, db, sh, c, body.start_s, body.end_s)
    db.commit()
    return {"take": proj_svc.take_dict(t), "shot": proj_svc.shot_dict(db, sh, include_takes=True)}


@router.post("/footage/clips/{clip_id}/describe")
def footage_clip_describe(clip_id: int, db: Session = Depends(get_db)):
    c = db.get(FilmClip, clip_id)
    if c is None:
        raise HTTPException(404, "Clip not found")
    words = _director_guard(footage.describe_with_llm, db, c)
    db.commit()
    return {"keywords": c.keywords or [], "added": words, "llm": words is not None}


# ------------------------------------------------------------------- audio -
@router.get("/projects/{project_id}/audio")
def project_audio(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    tl = timeline.compute(db, p)
    return {"tracks": [audio_svc.track_dict(t, tl) for t in audio_svc.tracks_of(db, p.id)],
            "mix": audio_svc.mix_plan(db, p), "capabilities": audio_svc.capability_flags(db),
            "kinds": list(audio_svc.KINDS)}


@router.post("/projects/{project_id}/audio")
async def add_audio(project_id: int, file: UploadFile, kind: str = Form("music"), label: str | None = Form(None),
                    anchor_kind: str = Form("timeline"), anchor_id: int | None = Form(None),
                    offset_s: float = Form(0.0), gain_db: float = Form(0.0), db: Session = Depends(get_db)):
    p = _project(db, project_id)
    data = await file.read()
    t = _s3_guard(audio_svc.add_track, db, p, data, file.content_type, file.filename, kind=kind, label=label,
                  anchor_kind=anchor_kind, anchor_id=anchor_id, offset_s=offset_s, gain_db=gain_db)
    db.commit()
    return audio_svc.track_dict(t, timeline.compute(db, p))


class AudioPatch(BaseModel):
    label: str | None = None
    kind: str | None = None
    anchor_kind: str | None = None
    anchor_id: int | None = None
    offset_s: float | None = None
    gain_db: float | None = None
    muted: bool | None = None
    loop: bool | None = None
    trim_start_s: float | None = None
    trim_end_s: float | None = None
    fade_in_s: float | None = None
    fade_out_s: float | None = None


@router.patch("/audio/{track_id}")
def patch_audio(track_id: int, body: AudioPatch, db: Session = Depends(get_db)):
    t = db.get(FilmAudioTrack, track_id)
    if t is None:
        raise HTTPException(404, "Track not found")
    _s3_guard(audio_svc.update_track, db, t, **body.model_dump(exclude_unset=True))
    db.commit()
    return audio_svc.track_dict(t, timeline.compute(db, _project(db, t.project_id)))


@router.delete("/audio/{track_id}")
def delete_audio(track_id: int, db: Session = Depends(get_db)):
    t = db.get(FilmAudioTrack, track_id)
    if t is None:
        raise HTTPException(404, "Track not found")
    audio_svc.remove_track(db, t)
    db.commit()
    return {"deleted": track_id}


# --------------------------------------------------------------- subtitles -
@router.get("/projects/{project_id}/subtitles")
def get_subtitles(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    return {**sub_svc.subtitle_dict(sub_svc.get(db, p.id)), "validation": sub_svc.validate(db, p)}


class SubtitleBody(BaseModel):
    cues: list[dict] | None = None
    style: dict | None = None
    burn_in: bool | None = None
    language: str | None = None


@router.put("/projects/{project_id}/subtitles")
def put_subtitles(project_id: int, body: SubtitleBody, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    st = sub_svc.ensure(db, p)
    cues = body.cues if body.cues is not None else st.cues
    st = sub_svc.set_cues(db, p, cues, source="manual" if body.cues is not None else st.source,
                          style=body.style, burn_in=body.burn_in, language=body.language)
    db.commit()
    return {**sub_svc.subtitle_dict(st), "validation": sub_svc.validate(db, p)}


@router.post("/projects/{project_id}/subtitles/from-script")
def subtitles_from_script(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    st = sub_svc.from_script(db, p)
    db.commit()
    return {**sub_svc.subtitle_dict(st), "validation": sub_svc.validate(db, p)}


class SubtitleImport(BaseModel):
    text: str


@router.post("/projects/{project_id}/subtitles/import")
def subtitles_import(project_id: int, body: SubtitleImport, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    cues = sub_svc.parse(body.text)
    if not cues:
        raise HTTPException(422, "No cues found — paste SRT or WebVTT text.")
    st = sub_svc.set_cues(db, p, cues, source="imported")
    db.commit()
    return {**sub_svc.subtitle_dict(st), "validation": sub_svc.validate(db, p)}


@router.post("/projects/{project_id}/subtitles/resync")
def subtitles_resync(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    st = sub_svc.resync(db, p)
    db.commit()
    return {**sub_svc.subtitle_dict(st), "validation": sub_svc.validate(db, p)}


@router.get("/projects/{project_id}/subtitles.srt")
def subtitles_srt(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    st = sub_svc.get(db, p.id)
    return PlainTextResponse(sub_svc.to_srt(st) if st else "", media_type="application/x-subrip")


@router.get("/projects/{project_id}/subtitles.vtt")
def subtitles_vtt(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    st = sub_svc.get(db, p.id)
    return PlainTextResponse(sub_svc.to_vtt(st) if st else "WEBVTT\n", media_type="text/vtt")


# --------------------------------------------------------------- QA/repair -
@router.get("/projects/{project_id}/qa")
def project_qa(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    report = qa_svc.check_project(db, p)
    db.commit()
    return report


@router.get("/projects/{project_id}/repairs")
def project_repairs(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    out = qa_svc.repair_queue(db, p)
    db.commit()
    return {"repairs": out}


# -------------------------------------------------------------------- runs -
class RunBody(BaseModel):
    kind: str = "video"
    scene_ids: list[int] = []
    shot_ids: list[int] = []
    sample: bool = False
    force: bool = False
    approve_cost: bool = False
    skip_done: bool = True
    inline: bool = False


@router.post("/projects/{project_id}/runs")
def start_run(project_id: int, body: RunBody, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    job = _s3_guard(production.start_run, db, p, kind=body.kind, scene_ids=body.scene_ids or None,
                    shot_ids=body.shot_ids or None, sample=body.sample, force=body.force,
                    approve_cost=body.approve_cost, skip_done=body.skip_done)
    db.commit()
    job_svc.start(job.id, inline=body.inline)
    db.refresh(job)
    return board_svc.job_dict(job)


@router.get("/projects/{project_id}/sample-shots")
def sample_shots(project_id: int, scene_id: int | None = None, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    return {"shots": [proj_svc.shot_dict(db, sh) for sh in production.sample_shots(db, p, scene_id)]}


# ------------------------------------------------------------------ export -
class ExportBody(BaseModel):
    label: str | None = None
    burn_in: bool | None = None
    include_audio: bool = True
    quality: str = "1080p"
    force: bool = False
    inline: bool = False


@router.post("/projects/{project_id}/export")
def start_export(project_id: int, body: ExportBody, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    job = _s3_guard(export_svc.start_export, db, p, label=body.label, burn_in=body.burn_in,
                    include_audio=body.include_audio, quality=body.quality, force=body.force)
    db.commit()
    job_svc.start(job.id, inline=body.inline)
    db.refresh(job)
    return board_svc.job_dict(job)


@router.get("/projects/{project_id}/exports")
def list_exports(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    return {"exports": export_svc.exports_of(db, p), "plan": export_svc.plan(db, p)}


# --------------------------------------------------------------- reference -
@router.get("/projects/{project_id}/reference")
def get_reference(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    return {"reference": p.reference or {}, "yt_dlp": _has_ytdlp()}


def _has_ytdlp() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


@router.post("/projects/{project_id}/reference/upload")
async def reference_upload(project_id: int, file: UploadFile, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    data = await file.read()
    out = _s3_guard(reference_svc.analyze_upload, db, p, data, file.content_type, file.filename)
    db.commit()
    return {"reference": out}


class ReferenceBody(BaseModel):
    post_id: int | None = None
    clip_id: int | None = None
    url: str | None = None


@router.post("/projects/{project_id}/reference")
def reference_from(project_id: int, body: ReferenceBody, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    if body.post_id:
        out = _s3_guard(reference_svc.analyze_post, db, p, body.post_id)
    elif body.clip_id:
        out = _s3_guard(reference_svc.analyze_clip, db, p, body.clip_id)
    elif body.url:
        out = _s3_guard(reference_svc.analyze_url, db, p, body.url)
    else:
        raise HTTPException(422, "Send post_id, clip_id or url.")
    db.commit()
    return {"reference": out}


@router.post("/projects/{project_id}/reference/propose")
def reference_propose(project_id: int, body: DirectBody | None = None, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    job = _director_guard(lambda: _s3_guard(reference_svc.propose, db, p, use_llm=(body.use_llm if body else True)))
    db.commit()
    return director.proposal_dict(job)


# ------------------------------------------------------------ asset AI tools -
from ..film import asset_gen  # noqa: E402


@router.get("/assets/{asset_id}/tools")
def asset_tools(asset_id: int, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    asset_gen.sync_pending(db, a)
    db.commit()
    return {"tools": asset_gen.tools_for(db, a), "generations": asset_gen.generations_of(db, a)}


class AssetGenBody(BaseModel):
    tool: str = "generate"
    instruction: str | None = None
    family: str | None = None
    provider: str | None = None
    strength: float | None = None
    kind: str | None = None


@router.post("/assets/{asset_id}/generate")
def asset_generate(asset_id: int, body: AssetGenBody, db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    try:
        out = asset_gen.generate(db, a, tool=body.tool, instruction=body.instruction, family=body.family,
                                 provider=body.provider, strength=body.strength, kind=body.kind)
    except asset_gen.AssetGenError as e:
        raise HTTPException(422, str(e))
    return out


# ------------------------------------------------------- editor sequence ---
from ..film import sequence as seq_svc                       # noqa: E402
from ..film.models import (FilmMarker, FilmTimelineClip,     # noqa: E402
                           FilmTimelineTrack)


def _sguard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except seq_svc.SequenceConflict as e:
        raise HTTPException(409, str(e))
    except seq_svc.SequenceError as e:
        raise HTTPException(422, str(e))


def _seq_track(db: Session, track_id: int) -> FilmTimelineTrack:
    t = db.get(FilmTimelineTrack, track_id)
    if t is None:
        raise HTTPException(404, "Track not found")
    return t


def _seq_clip(db: Session, clip_id: int) -> FilmTimelineClip:
    c = db.get(FilmTimelineClip, clip_id)
    if c is None:
        raise HTTPException(404, "Clip not found")
    return c


def _seq_marker(db: Session, marker_id: int) -> FilmMarker:
    m = db.get(FilmMarker, marker_id)
    if m is None:
        raise HTTPException(404, "Marker not found")
    return m


@router.get("/projects/{project_id}/sequence")
def get_sequence(project_id: int, db: Session = Depends(get_db)):
    return seq_svc.sequence_dict(db, _project(db, project_id))


class SequenceBuild(BaseModel):
    replace: bool = False


@router.post("/projects/{project_id}/sequence/build")
def build_sequence(project_id: int, body: SequenceBuild | None = None, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    return _sguard(seq_svc.build_from_storyboard, db, p, replace=bool(body and body.replace))


@router.delete("/projects/{project_id}/sequence")
def delete_sequence(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    if not seq_svc.exists(db, p.id):
        raise HTTPException(404, "No sequence to delete")
    _sguard(seq_svc.drop_sequence, db, p)
    return {"ok": True}


class TrackCreate(BaseModel):
    kind: str = "video"
    label: str | None = None


@router.post("/projects/{project_id}/sequence/tracks")
def add_seq_track(project_id: int, body: TrackCreate, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    _sguard(seq_svc.add_track, db, p, body.kind, body.label)
    return seq_svc.sequence_dict(db, p)


class TrackPatch(BaseModel):
    label: str | None = None
    muted: bool | None = None
    solo: bool | None = None
    locked: bool | None = None
    position: int | None = None


@router.patch("/sequence/tracks/{track_id}")
def patch_seq_track(track_id: int, body: TrackPatch, db: Session = Depends(get_db)):
    t = _seq_track(db, track_id)
    p = _project(db, t.project_id)
    _sguard(seq_svc.patch_track, db, p, t, **body.model_dump())
    return seq_svc.sequence_dict(db, p)


@router.delete("/sequence/tracks/{track_id}")
def delete_seq_track(track_id: int, db: Session = Depends(get_db)):
    t = _seq_track(db, track_id)
    p = _project(db, t.project_id)
    _sguard(seq_svc.delete_track, db, p, t)
    return seq_svc.sequence_dict(db, p)


class ClipCreate(BaseModel):
    track_id: int
    source_kind: str = "take"
    start_s: float = 0.0
    duration_s: float | None = None
    take_id: int | None = None
    footage_id: int | None = None
    audio_track_id: int | None = None
    shot_id: int | None = None
    label: str | None = None
    data: dict | None = None


@router.post("/projects/{project_id}/sequence/clips")
def add_seq_clip(project_id: int, body: ClipCreate, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    t = _seq_track(db, body.track_id)
    if t.project_id != p.id:
        raise HTTPException(422, "Track belongs to another project")
    return _sguard(seq_svc.add_clip, db, p, t, body.source_kind, body.start_s,
                   duration_s=body.duration_s, take_id=body.take_id, footage_id=body.footage_id,
                   audio_track_id=body.audio_track_id, shot_id=body.shot_id, label=body.label,
                   data=body.data)


class ClipPatch(BaseModel):
    track_id: int | None = None
    start_s: float | None = None
    duration_s: float | None = None
    trim_start_s: float | None = None
    speed: float | None = None
    gain_db: float | None = None
    muted: bool | None = None
    fade_in_s: float | None = None
    fade_out_s: float | None = None
    effects: dict | None = None
    transition_after: dict | None = None
    label: str | None = None
    data: dict | None = None
    label_op: str | None = None      # undo-history label for this edit


@router.patch("/sequence/clips/{clip_id}")
def patch_seq_clip(clip_id: int, body: ClipPatch, db: Session = Depends(get_db)):
    c = _seq_clip(db, clip_id)
    p = _project(db, c.project_id)
    fields = body.model_dump(exclude_unset=True)
    label_op = fields.pop("label_op", None)
    return _sguard(seq_svc.patch_clip, db, p, c, label_op=label_op, **fields)


class BatchOps(BaseModel):
    ops: list[dict]
    label: str = "move clips"


@router.post("/projects/{project_id}/sequence/clips/batch")
def batch_seq_clips(project_id: int, body: BatchOps, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    return _sguard(seq_svc.batch_patch, db, p, body.ops, label=body.label)


class SplitBody(BaseModel):
    at_s: float


@router.post("/sequence/clips/{clip_id}/split")
def split_seq_clip(clip_id: int, body: SplitBody, db: Session = Depends(get_db)):
    c = _seq_clip(db, clip_id)
    p = _project(db, c.project_id)
    return _sguard(seq_svc.split_clip, db, p, c, body.at_s)


class ClipTake(BaseModel):
    take_id: int


@router.post("/sequence/clips/{clip_id}/take")
def seq_clip_take(clip_id: int, body: ClipTake, db: Session = Depends(get_db)):
    c = _seq_clip(db, clip_id)
    p = _project(db, c.project_id)
    t = db.get(FilmTake, body.take_id)
    if t is None:
        raise HTTPException(404, "Take not found")
    return _sguard(seq_svc.replace_take, db, p, c, t)


class DeleteClips(BaseModel):
    ids: list[int]
    ripple: bool = False


@router.post("/projects/{project_id}/sequence/delete-clips")
def delete_seq_clips(project_id: int, body: DeleteClips, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    return _sguard(seq_svc.delete_clips, db, p, body.ids, ripple=body.ripple)


class InsertGap(BaseModel):
    at_s: float
    gap_s: float


@router.post("/projects/{project_id}/sequence/insert-gap")
def seq_insert_gap(project_id: int, body: InsertGap, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    return _sguard(seq_svc.ripple_insert, db, p, body.at_s, body.gap_s)


class MarkerCreate(BaseModel):
    t_s: float
    label: str = ""
    color: str = "amber"
    note: str | None = None


@router.post("/projects/{project_id}/sequence/markers")
def add_seq_marker(project_id: int, body: MarkerCreate, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    return _sguard(seq_svc.add_marker, db, p, body.t_s, label=body.label, color=body.color, note=body.note)


class MarkerPatch(BaseModel):
    t_s: float | None = None
    label: str | None = None
    color: str | None = None
    note: str | None = None


@router.patch("/sequence/markers/{marker_id}")
def patch_seq_marker(marker_id: int, body: MarkerPatch, db: Session = Depends(get_db)):
    m = _seq_marker(db, marker_id)
    p = _project(db, m.project_id)
    return _sguard(seq_svc.patch_marker, db, p, m, **body.model_dump(exclude_unset=True))


@router.delete("/sequence/markers/{marker_id}")
def delete_seq_marker(marker_id: int, db: Session = Depends(get_db)):
    m = _seq_marker(db, marker_id)
    p = _project(db, m.project_id)
    return _sguard(seq_svc.delete_marker, db, p, m)


@router.post("/projects/{project_id}/sequence/undo")
def seq_undo(project_id: int, db: Session = Depends(get_db)):
    return _sguard(seq_svc.undo, db, _project(db, project_id))


@router.post("/projects/{project_id}/sequence/redo")
def seq_redo(project_id: int, db: Session = Depends(get_db)):
    return _sguard(seq_svc.redo, db, _project(db, project_id))


@router.get("/projects/{project_id}/sequence/history")
def seq_history(project_id: int, db: Session = Depends(get_db)):
    _project(db, project_id)
    return seq_svc.history(db, project_id)
