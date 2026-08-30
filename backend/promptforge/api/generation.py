"""Generation API (8.4–8.6): options + estimates + start + status + spend +
per-provider guided test + GUI-editable pricing catalog."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..aliases import normalize_model
from ..db import get_db
from ..generation import pricing, router as gen_router
from ..generation import queue as gen_queue
from ..models import Generation, RefLink

router = APIRouter(prefix="/api/generation", tags=["generation"])


def _gen_dict(g: Generation) -> dict:
    return {
        "id": g.id,
        "status": g.status,
        "error": g.error,
        "provider": g.provider,
        "provider_model_id": g.provider_model_id,
        "model_family": g.model_family,
        "cost_estimate": g.cost_estimate,
        "cost_actual": g.cost_actual,
        "output_post_id": g.output_post_id,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "finished_at": g.finished_at.isoformat() if g.finished_at else None,
    }


@router.get("/options")
def options(db: Session = Depends(get_db)):
    return gen_router.model_options(db)


@router.get("/estimate")
def estimate(model_family: str, provider: str | None = None,
             size: str | None = None, duration: float | None = None,
             resolution: str | None = None, db: Session = Depends(get_db)):
    params: dict = {}
    if size:
        params["size"] = size
    if duration:
        params["duration_s"] = duration
    if resolution:
        params["resolution"] = resolution
    family = model_family.lower()
    try:
        chosen_provider, model_id, est = gen_router.route(
            db, family, params, provider or None)
    except LookupError as e:
        return {"estimate": None, "error": str(e)}
    return {"estimate": est, "provider": chosen_provider,
            "provider_model_id": model_id}


class StartBody(BaseModel):
    prompt: str
    negative: str | None = None
    model_family: str
    provider: str | None = None
    params: dict = {}
    collection_id: int | None = None
    template_id: int | None = None
    saved_prompt_id: int | None = None
    ref_ids: list[int] = []


@router.post("/start")
def start(body: StartBody, db: Session = Depends(get_db)):
    if not body.prompt.strip():
        raise HTTPException(422, "Prompt is empty.")
    family = normalize_model(body.model_family) or body.model_family.lower()
    try:
        provider, model_id, est = gen_router.route(
            db, family, body.params, body.provider or None)
    except LookupError as e:
        raise HTTPException(409, str(e))
    params = dict(body.params or {})
    if body.negative:
        params["_negative"] = body.negative
    if body.collection_id:
        params["_collection_id"] = body.collection_id
    g = Generation(
        saved_prompt_id=body.saved_prompt_id,
        provider=provider, provider_model_id=model_id,
        model_family=family, prompt=body.prompt.strip(),
        cost_estimate=est, status="queued", params=params)
    db.add(g)
    db.flush()
    for ref_id in body.ref_ids or []:
        db.add(RefLink(ref_id=ref_id, generation_id=g.id, role="style"))
    db.commit()
    gen_queue.start_worker()
    gen_queue.enqueue(g.id)
    return _gen_dict(g)


@router.get("/spend")
def spend(db: Session = Depends(get_db)):
    totals = settings_store.get(db, "gen_spend", None) or {}
    recent = db.execute(select(Generation)
                        .order_by(Generation.id.desc()).limit(25)).scalars()
    return {"totals": totals,
            "total": round(sum(float(v) for v in totals.values()), 4),
            "recent": [_gen_dict(g) for g in recent]}


@router.get("/pricing")
def get_pricing():
    return {"families": pricing.load_catalog()}


@router.put("/pricing")
def put_pricing(families: dict = Body(...)):
    if not isinstance(families, dict):
        raise HTTPException(422, "Body must be the families object")
    pricing.save_catalog(families)
    return {"families": pricing.load_catalog()}


@router.get("/{generation_id}")
def get_generation(generation_id: int, db: Session = Depends(get_db)):
    g = db.get(Generation, generation_id)
    if g is None:
        raise HTTPException(404, "Generation not found")
    return _gen_dict(g)
