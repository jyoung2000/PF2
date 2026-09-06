"""Forge API (spec §2–§13): model intelligence, routing, prompt compilation,
tools, test lab, plans, workflows, usage — grown phase by phase."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from ..db import session_scope
from ..forge import catalog

router = APIRouter(prefix="/api/forge", tags=["forge"])


# ----------------------------------------------------- model intelligence ---
@router.get("/models")
def list_models(modality: str | None = None):
    with session_scope() as s:
        return {"models": catalog.registry(s, modality=modality),
                "providers": catalog.providers_overview(s)}


@router.get("/models/{family}")
def get_model(family: str):
    with session_scope() as s:
        e = catalog.entry(s, family)
    if e is None:
        raise HTTPException(404, f"'{family}' is not in the model catalog")
    return e


@router.put("/models/{family}")
def update_model(family: str, patch: dict = Body(...)):
    """User edit of the intelligence entry — persists to the DATA_DIR copy,
    which wins over the seed (D16 lifecycle)."""
    catalog.save_family(family, patch)
    with session_scope() as s:
        return catalog.entry(s, family)


@router.post("/models/{family}/validate")
def validate_model_params(family: str, body: dict = Body(...)):
    return catalog.validate_params(family, body.get("params") or {},
                                   mode=body.get("mode"))


@router.get("/providers")
def list_providers():
    with session_scope() as s:
        return {"providers": catalog.providers_overview(s)}
