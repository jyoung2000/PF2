"""Prompt Studio API (7.2, 7.5–7.8): templates (CRUD/assemble/export/import),
Enhance, saved prompts (+unified search across saved AND scraped), reference
images (sha256-deduped, role-linked)."""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import fts, settings_store
from ..aliases import display_family, normalize_model
from ..config import get_config
from ..db import get_db
from ..knowledge import template_gen
from ..models import (Collection, Post, ReferenceImage, RefLink, SavedPrompt,
                      Template)

router = APIRouter(prefix="/api/studio", tags=["studio"])


# ---------------------------------------------------------------- templates -
def _template_dict(t: Template, db: Session) -> dict:
    collection = db.get(Collection, t.collection_id) if t.collection_id else None
    cover_urls: list[str] = []
    if collection is not None:
        from .collections import _cover_urls
        cover_urls = _cover_urls(db, collection.id)
    return {
        "id": t.id,
        "name": t.name,
        "version": t.version,
        "collection_id": t.collection_id,
        "collection_name": collection.name if collection else None,
        "schema": t.schema_json,
        "text_template": t.text_template,
        "ref_slots": t.ref_slots,
        "recommended_model": t.recommended_model,
        "recommended_model_label": (display_family(t.recommended_model)
                                    if t.recommended_model else None),
        "user_edited": bool((t.schema_json or {}).get("user_edited")),
        "cover_urls": cover_urls,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("/templates")
def list_templates(db: Session = Depends(get_db)):
    # make sure every collection with posts has a template
    for c in db.execute(select(Collection)).scalars():
        exists = db.execute(select(Template.id).where(
            Template.collection_id == c.id)).first()
        if not exists:
            db.commit()
            template_gen.sync_template_for_collection(c.id)
            db.expire_all()
    rows = db.execute(select(Template).order_by(Template.updated_at.desc())).scalars()
    return {"templates": [_template_dict(t, db) for t in rows]}


@router.get("/templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db)):
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(404, "Template not found")
    return _template_dict(t, db)


class AssembleBody(BaseModel):
    values: dict


@router.post("/templates/{template_id}/assemble")
def assemble_template(template_id: int, body: AssembleBody,
                      db: Session = Depends(get_db)):
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(404, "Template not found")
    return {"prompt": template_gen.assemble(t.text_template, body.values)}


class TemplatePatch(BaseModel):
    name: str | None = None
    template_schema: dict | None = None
    text_template: str | None = None
    ref_slots: list | None = None
    recommended_model: str | None = None


@router.put("/templates/{template_id}")
def update_template(template_id: int, body: TemplatePatch,
                    db: Session = Depends(get_db)):
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(404, "Template not found")
    if body.name is not None:
        t.name = body.name
    if body.template_schema is not None:
        schema = dict(body.template_schema)
        schema["user_edited"] = True  # engine regeneration won't clobber edits
        t.schema_json = schema
    if body.text_template is not None:
        t.text_template = body.text_template
    if body.ref_slots is not None:
        t.ref_slots = body.ref_slots
    if body.recommended_model is not None:
        t.recommended_model = body.recommended_model or None
    t.version = (t.version or 1) + 1
    db.flush()
    return _template_dict(t, db)


@router.post("/templates/{template_id}/regenerate")
def regenerate_template(template_id: int, db: Session = Depends(get_db)):
    t = db.get(Template, template_id)
    if t is None or not t.collection_id:
        raise HTTPException(404, "Template not found")
    schema = dict(t.schema_json or {})
    schema.pop("user_edited", None)
    t.schema_json = schema
    collection_id = t.collection_id
    db.commit()
    template_gen.sync_template_for_collection(collection_id)
    db.expire_all()
    t = db.get(Template, template_id)
    return _template_dict(t, db)


@router.get("/templates/{template_id}/export.json")
def export_template_json(template_id: int, db: Session = Depends(get_db)):
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(404, "Template not found")
    data = json.dumps(template_gen.export_json(t), indent=2)
    return Response(content=data, media_type="application/json",
                    headers={"Content-Disposition":
                             f'attachment; filename="{t.name}.template.json"'})


@router.get("/templates/{template_id}/export.txt")
def export_template_text(template_id: int, db: Session = Depends(get_db)):
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(404, "Template not found")
    return PlainTextResponse(template_gen.export_text(t), headers={
        "Content-Disposition": f'attachment; filename="{t.name}.template.txt"'})


@router.post("/templates/import")
async def import_template(file: UploadFile, collection_id: int | None = None):
    raw = await file.read()
    text = raw.decode("utf-8", "replace")
    try:
        if text.lstrip().startswith("{"):
            tid = template_gen.import_json(json.loads(text), collection_id)
        else:
            tid = template_gen.import_text(text, collection_id)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Couldn't import template: {e}")
    return {"template_id": tid}


# ------------------------------------------------------------------ enhance -
class EnhanceBody(BaseModel):
    prompt: str
    model_family: str | None = None
    collection_id: int | None = None


@router.post("/enhance")
def enhance(body: EnhanceBody, db: Session = Depends(get_db)):
    if not body.prompt.strip():
        raise HTTPException(422, "Paste a prompt to enhance first.")
    from ..knowledge import enhance as enhance_mod
    from ..llm.client import BudgetExceeded, LLMError, LLMNotConfigured
    family = normalize_model(body.model_family) if body.model_family else None
    try:
        return enhance_mod.enhance_prompt(body.prompt, family, body.collection_id)
    except LLMNotConfigured as e:
        raise HTTPException(409, str(e))
    except BudgetExceeded as e:
        raise HTTPException(429, str(e))
    except LLMError as e:
        raise HTTPException(502, str(e))


# ------------------------------------------------------------ saved prompts -
class SavePromptBody(BaseModel):
    text: str
    negative: str | None = None
    model_family: str | None = None
    collection_id: int | None = None
    template_id: int | None = None
    params: dict = {}
    origin: str = "manual"  # manual | enhanced | template
    starred: bool = False
    refs: list[dict] = []   # [{ref_id, role}]


def _saved_dict(sp: SavedPrompt, db: Session) -> dict:
    refs = db.execute(select(RefLink, ReferenceImage)
                      .join(ReferenceImage, ReferenceImage.id == RefLink.ref_id)
                      .where(RefLink.saved_prompt_id == sp.id)).all()
    return {
        "kind": "saved",
        "id": sp.id,
        "text": sp.text,
        "negative": sp.negative,
        "model_family": sp.model_family,
        "model_family_label": (display_family(sp.model_family)
                               if sp.model_family else None),
        "collection_id": sp.collection_id,
        "template_id": sp.template_id,
        "params": sp.params or {},
        "origin": sp.origin,
        "starred": sp.starred,
        "created_at": sp.created_at.isoformat() if sp.created_at else None,
        "refs": [{"ref_id": ref.id, "role": link.role,
                  "url": f"/api/studio/refs/{ref.id}/file"}
                 for link, ref in refs],
    }


@router.post("/prompts")
def save_prompt(body: SavePromptBody, db: Session = Depends(get_db)):
    if not body.text.strip():
        raise HTTPException(422, "Prompt text is empty.")
    sp = SavedPrompt(
        text=body.text.strip(), negative=body.negative,
        model_family=normalize_model(body.model_family) if body.model_family else None,
        collection_id=body.collection_id, template_id=body.template_id,
        params=body.params or {},
        origin=body.origin if body.origin in ("manual", "enhanced", "template")
        else "manual",
        starred=body.starred)
    db.add(sp)
    db.flush()
    for ref in body.refs:
        if isinstance(ref, dict) and db.get(ReferenceImage, ref.get("ref_id")):
            db.add(RefLink(ref_id=ref["ref_id"], saved_prompt_id=sp.id,
                           role=ref.get("role", "style")))
    fts.index_saved_prompt(db, sp.id, sp.text, sp.model_family)
    db.flush()
    return _saved_dict(sp, db)


@router.get("/prompts")
def search_prompts(q: str = "", model: str | None = None,
                   collection_id: int | None = None, origin: str | None = None,
                   starred: bool = False, include_scraped: bool = True,
                   limit: int = 60, db: Session = Depends(get_db)):
    """Unified search: saved prompts + (optionally) every scraped/generated
    post prompt (7.6)."""
    limit = max(1, min(limit, 150))
    out: list[dict] = []

    want_saved = origin in (None, "", "manual", "enhanced", "template", "saved")
    if want_saved:
        stmt = select(SavedPrompt)
        if q.strip():
            ids = fts.search_saved_prompts(db, q, limit=300)
            stmt = stmt.where(SavedPrompt.id.in_(ids)) if ids else stmt.where(False)
        if model:
            stmt = stmt.where(SavedPrompt.model_family == model.lower())
        if collection_id:
            stmt = stmt.where(SavedPrompt.collection_id == collection_id)
        if origin in ("manual", "enhanced", "template"):
            stmt = stmt.where(SavedPrompt.origin == origin)
        if starred:
            stmt = stmt.where(SavedPrompt.starred.is_(True))
        rows = db.execute(stmt.order_by(SavedPrompt.id.desc()).limit(limit)).scalars()
        out += [_saved_dict(sp, db) for sp in rows]

    want_posts = include_scraped and origin in (None, "", "scraped", "generated")
    if want_posts and len(out) < limit:
        from .posts import apply_post_filters
        stmt = select(Post).where(Post.prompt.is_not(None))
        stmt = apply_post_filters(stmt, model=model, collection_id=collection_id,
                                  origin=origin if origin in ("scraped", "generated")
                                  else None, nsfw=True,
                                  favorite=starred)
        if q.strip():
            ids = fts.search_posts(db, q, limit=300)
            stmt = stmt.where(Post.id.in_(ids)) if ids else stmt.where(False)
        rows = db.execute(stmt.order_by(Post.id.desc())
                          .limit(limit - len(out))).scalars()
        for p in rows:
            out.append({
                "kind": "post", "id": p.id, "text": p.prompt,
                "negative": p.negative_prompt,
                "model_family": p.model_family,
                "model_family_label": (display_family(p.model_family)
                                       if p.model_family else None),
                "origin": p.origin, "starred": p.favorite,
                "thumb_url": f"/{p.thumb_path}" if p.thumb_path else None,
                "created_at": p.scraped_at.isoformat() if p.scraped_at else None,
            })
    return {"items": out}


class SavedPatch(BaseModel):
    starred: bool | None = None
    text: str | None = None
    negative: str | None = None


@router.patch("/prompts/{prompt_id}")
def patch_prompt(prompt_id: int, body: SavedPatch, db: Session = Depends(get_db)):
    sp = db.get(SavedPrompt, prompt_id)
    if sp is None:
        raise HTTPException(404, "Saved prompt not found")
    if body.starred is not None:
        sp.starred = body.starred
    if body.text is not None and body.text.strip():
        sp.text = body.text.strip()
        fts.index_saved_prompt(db, sp.id, sp.text, sp.model_family)
    if body.negative is not None:
        sp.negative = body.negative
    db.flush()
    return _saved_dict(sp, db)


@router.delete("/prompts/{prompt_id}")
def delete_prompt(prompt_id: int, db: Session = Depends(get_db)):
    sp = db.get(SavedPrompt, prompt_id)
    if sp is None:
        raise HTTPException(404, "Saved prompt not found")
    fts.deindex_saved_prompt(db, prompt_id)
    db.delete(sp)
    db.flush()
    return {"deleted": prompt_id}


# -------------------------------------------------------------- references --
ALLOWED_REF_TYPES = {"image/png": ".png", "image/jpeg": ".jpg",
                     "image/webp": ".webp"}


@router.post("/refs")
async def upload_ref(file: UploadFile, role: str = "style",
                     db: Session = Depends(get_db)):
    data = await file.read()
    if not data:
        raise HTTPException(422, "Empty file")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(422, "Reference image too large (25MB max)")
    ext = ALLOWED_REF_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(422, "Reference must be PNG, JPEG or WebP")
    sha = hashlib.sha256(data).hexdigest()
    existing = db.execute(select(ReferenceImage).where(
        ReferenceImage.sha256 == sha)).scalar_one_or_none()
    if existing is not None:
        return {"ref_id": existing.id, "sha256": sha, "deduped": True,
                "url": f"/api/studio/refs/{existing.id}/file"}
    cfg = get_config()
    rel = f"refs/{sha}{ext}"
    dest = cfg.data_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    ref = ReferenceImage(sha256=sha, path=rel, source="upload")
    db.add(ref)
    db.flush()
    return {"ref_id": ref.id, "sha256": sha, "deduped": False,
            "url": f"/api/studio/refs/{ref.id}/file", "role": role}


@router.get("/refs/{ref_id}/file")
def ref_file(ref_id: int, db: Session = Depends(get_db)):
    ref = db.get(ReferenceImage, ref_id)
    if ref is None:
        raise HTTPException(404, "Reference not found")
    path = get_config().data_dir / ref.path
    if not path.exists():
        raise HTTPException(404, "Reference file missing on disk")
    return FileResponse(path)


@router.get("/refs")
def list_refs(db: Session = Depends(get_db)):
    rows = db.execute(select(ReferenceImage)
                      .order_by(ReferenceImage.id.desc()).limit(100)).scalars()
    return {"refs": [{"ref_id": r.id, "sha256": r.sha256, "source": r.source,
                      "url": f"/api/studio/refs/{r.id}/file",
                      "created_at": r.created_at.isoformat() if r.created_at else None}
                     for r in rows]}


# save-to-collection helper for studio results
@router.post("/prompts/{prompt_id}/star")
def toggle_star(prompt_id: int, db: Session = Depends(get_db)):
    sp = db.get(SavedPrompt, prompt_id)
    if sp is None:
        raise HTTPException(404, "Saved prompt not found")
    sp.starred = not sp.starred
    db.flush()
    from ..knowledge import engine as kengine
    if sp.model_family and sp.starred:
        try:
            kengine.generation_event(None, sp.model_family, sp.text, "starred",
                                     sp.collection_id)
        except Exception:
            pass
    return {"starred": sp.starred}
