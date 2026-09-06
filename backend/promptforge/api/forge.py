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


# ------------------------------------------------- intent / route / compile ---
@router.post("/intent")
def extract_intent(body: dict = Body(...)):
    from ..forge import intent
    return intent.extract(str(body.get("brief") or ""))


@router.post("/route")
def route_brief(body: dict = Body(...)):
    """Ranked, explainable model candidates for a brief (spec §3)."""
    from ..forge import intent as intent_mod, router as forge_router
    spec = body.get("intent") or intent_mod.extract(str(body.get("brief") or ""))
    with session_scope() as s:
        return forge_router.recommend(
            s, spec, family=body.get("family"), provider=body.get("provider"),
            connected_only=bool(body.get("connected_only")))


@router.post("/compile")
def compile_prompt(body: dict = Body(...)):
    """Idea → PromptPackage (spec §4). Pass family to pin the model; pass a
    previous package + family to recompile for a new model."""
    from ..forge import compiler
    with session_scope() as s:
        if body.get("package") and body.get("family"):
            return compiler.recompile(s, body["package"], body["family"],
                                      provider=body.get("provider"),
                                      use_llm=bool(body.get("use_llm")))
        idea = str(body.get("idea") or "").strip()
        if not idea:
            raise HTTPException(422, "idea is required")
        return compiler.compile_package(
            s, idea, family=body.get("family"), provider=body.get("provider"),
            params_override=body.get("params"), use_llm=bool(body.get("use_llm")))


# ------------------------------------------------------------- tool layer ---
@router.get("/tools")
def list_tools():
    from ..forge import tools
    with session_scope() as s:
        return {"tools": tools.availability(s)}


@router.post("/tools/{name}")
def invoke_tool(name: str, body: dict = Body(default={})):
    from ..forge import tools
    try:
        with session_scope() as s:
            return tools.invoke(s, name, body,
                                allow_fallback=bool(body.get("allow_fallback")))
    except tools.ToolError as e:
        raise HTTPException(409, detail=e.detail)


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    from ..forge import tools
    try:
        with session_scope() as s:
            return tools.job_status(s, job_id)
    except tools.ToolError as e:
        raise HTTPException(404, detail=e.detail)


# ---------------------------------------------------------------- test lab ---
@router.post("/experiments")
def create_experiment(body: dict = Body(...)):
    from ..forge import experiments
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    with session_scope() as s:
        exp = experiments.create_experiment(s, name, body.get("brief"))
        s.commit()
        return experiments.experiment_view(s, exp.id)


@router.get("/experiments")
def list_experiments():
    from sqlalchemy import select
    from ..forge.models import PromptExperiment, PromptVariant
    with session_scope() as s:
        rows = list(s.execute(select(PromptExperiment)
                              .order_by(PromptExperiment.id.desc())).scalars())
        counts = {}
        for exp in rows:
            counts[exp.id] = s.query(PromptVariant).filter_by(experiment_id=exp.id).count()
        return {"experiments": [
            {"id": e.id, "name": e.name, "brief": e.brief, "archived": e.archived,
             "variant_count": counts.get(e.id, 0),
             "created_at": e.created_at.isoformat() if e.created_at else None}
            for e in rows]}


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: int):
    from ..forge import experiments
    try:
        with session_scope() as s:
            return experiments.experiment_view(s, experiment_id)
    except experiments.LabError as e:
        raise HTTPException(404, str(e))


@router.post("/experiments/{experiment_id}/variants")
def add_variant(experiment_id: int, body: dict = Body(default={})):
    from ..forge import experiments
    try:
        with session_scope() as s:
            if body.get("compile_family"):
                v = experiments.compile_variant(s, experiment_id, body["compile_family"],
                                                provider=body.get("provider"),
                                                use_llm=bool(body.get("use_llm")))
            else:
                v = experiments.add_variant(
                    s, experiment_id, package=body.get("package"),
                    prompt=body.get("prompt"), negative=body.get("negative"),
                    family=body.get("family"), provider=body.get("provider"),
                    params=body.get("params"), label=body.get("label"))
            s.commit()
            return experiments.experiment_view(s, experiment_id)
    except experiments.LabError as e:
        raise HTTPException(409, str(e))


@router.post("/variants/{variant_id}/fork")
def fork_variant(variant_id: int, body: dict = Body(default={})):
    from ..forge import experiments
    try:
        with session_scope() as s:
            v = experiments.fork_variant(s, variant_id, body.get("changes") or {},
                                         label=body.get("label"))
            s.commit()
            return experiments.experiment_view(s, v.experiment_id)
    except experiments.LabError as e:
        raise HTTPException(404, str(e))


@router.post("/variants/{variant_id}/run")
def run_variant(variant_id: int, body: dict = Body(default={})):
    from ..forge import experiments, tools
    try:
        with session_scope() as s:
            run = experiments.run_variant(s, variant_id,
                                          allow_fallback=bool(body.get("allow_fallback")))
            s.commit()
            return {"run_id": run.id, "generation_id": run.generation_id,
                    "provider": run.provider, "family": run.family,
                    "status": run.status, "cost": run.cost}
    except experiments.LabError as e:
        raise HTTPException(404, str(e))
    except tools.ToolError as e:
        raise HTTPException(409, detail=e.detail)


@router.post("/runs/{run_id}/score")
def score_run(run_id: int, body: dict = Body(default={})):
    from ..forge import experiments
    try:
        with session_scope() as s:
            run = experiments.score_run(s, run_id, score=body.get("score"),
                                        notes=body.get("notes"), winner=body.get("winner"))
            s.commit()
            return {"id": run.id, "user_score": run.user_score,
                    "user_notes": run.user_notes}
    except experiments.LabError as e:
        raise HTTPException(409, str(e))


@router.post("/runs/{run_id}/refine")
def refine_run(run_id: int, body: dict = Body(default={})):
    from ..forge import evaluate, experiments
    try:
        with session_scope() as s:
            out = evaluate.refine_run(s, run_id, use_llm=bool(body.get("use_llm")),
                                      create_variant=body.get("create_variant", True))
            s.commit()
            return out
    except experiments.LabError as e:
        raise HTTPException(404, str(e))
