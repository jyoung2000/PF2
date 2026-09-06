"""Prompt Test Lab (spec §5): experiments hold versioned prompt variants;
variants run through the tool layer as ordinary generations; runs carry the
exact model/provider/params snapshot plus user and automatic scores, cost
and latency — so "which prompt + model + settings worked best?" is a query,
not a memory."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Generation, Post
from . import compiler, tools
from .models import PromptExperiment, PromptVariant, VariantRun


class LabError(Exception):
    pass


def _next_version(s: Session, experiment_id: int) -> int:
    versions = [v for (v,) in s.execute(select(PromptVariant.version).where(
        PromptVariant.experiment_id == experiment_id))]
    return (max(versions) + 1) if versions else 1


def create_experiment(s: Session, name: str, brief: str | None = None) -> PromptExperiment:
    from . import intent as intent_mod
    exp = PromptExperiment(name=name, brief=brief,
                           intent=intent_mod.extract(brief) if brief else {})
    s.add(exp)
    s.flush()
    return exp


def add_variant(s: Session, experiment_id: int, *, package: dict | None = None,
                prompt: str | None = None, negative: str | None = None,
                family: str | None = None, provider: str | None = None,
                params: dict | None = None, label: str | None = None,
                parent_id: int | None = None, origin: str = "manual") -> PromptVariant:
    """Either a full PromptPackage (compiled path) or raw fields (manual)."""
    exp = s.get(PromptExperiment, experiment_id)
    if exp is None:
        raise LabError(f"experiment {experiment_id} not found")
    if package:
        prompt = package.get("optimized_prompt") or prompt
        negative = package.get("negative_prompt") if negative is None else negative
        family = package.get("family") or family
        provider = package.get("provider") or provider
        params = package.get("params") or params
    if not prompt:
        raise LabError("a variant needs a prompt (or a compiled package)")
    v = PromptVariant(experiment_id=experiment_id, parent_id=parent_id,
                      version=_next_version(s, experiment_id), label=label,
                      origin=origin, prompt=prompt, negative=negative,
                      family=family, provider=provider, params=params or {},
                      package=package or {})
    s.add(v)
    s.flush()
    return v


def compile_variant(s: Session, experiment_id: int, family: str,
                    provider: str | None = None, use_llm: bool = False) -> PromptVariant:
    """Compile the experiment's brief for a target model → a new variant."""
    exp = s.get(PromptExperiment, experiment_id)
    if exp is None or not exp.brief:
        raise LabError("experiment (with a brief) required to compile")
    pkg = compiler.compile_package(s, exp.brief, family=family, provider=provider,
                                   use_llm=use_llm,
                                   intent_override=exp.intent or None)
    if pkg.get("error"):
        raise LabError(pkg["error"])
    return add_variant(s, experiment_id, package=pkg, origin="compiled",
                       label=f"{pkg['display_name']} compile")


def fork_variant(s: Session, variant_id: int, changes: dict,
                 label: str | None = None) -> PromptVariant:
    v = s.get(PromptVariant, variant_id)
    if v is None:
        raise LabError(f"variant {variant_id} not found")
    return add_variant(
        s, v.experiment_id,
        prompt=changes.get("prompt", v.prompt),
        negative=changes.get("negative", v.negative),
        family=changes.get("family", v.family),
        provider=changes.get("provider", v.provider),
        params={**(v.params or {}), **(changes.get("params") or {})},
        label=label or (f"fork of v{v.version}"),
        parent_id=v.id, origin="fork")


def run_variant(s: Session, variant_id: int, allow_fallback: bool = False) -> VariantRun:
    """One generation for this variant through the tool layer."""
    v = s.get(PromptVariant, variant_id)
    if v is None:
        raise LabError(f"variant {variant_id} not found")
    kind = (v.package or {}).get("kind") or "image"
    tool = "generate_video" if kind == "video" else "generate_image"
    job = tools.invoke(s, tool, {"prompt": v.prompt, "negative": v.negative,
                                 "family": v.family, "provider": v.provider,
                                 "params": dict(v.params or {})},
                       allow_fallback=allow_fallback)
    run = VariantRun(variant_id=v.id, generation_id=job["job_id"],
                     family=job["family"], provider=job["provider"],
                     provider_model_id=job["provider_model_id"],
                     params=dict(v.params or {}), status="queued",
                     cost=job.get("estimate"))
    s.add(run)
    s.flush()
    return run


def sync_runs(s: Session, experiment_id: int) -> None:
    """Pull generation outcomes into the runs (status, cost, latency)."""
    runs = s.execute(select(VariantRun).join(PromptVariant).where(
        PromptVariant.experiment_id == experiment_id,
        VariantRun.status.in_(["queued", "running"]))).scalars()
    for run in runs:
        g = s.get(Generation, run.generation_id) if run.generation_id else None
        if g is None:
            run.status = "failed"
            continue
        run.status = g.status
        run.cost = g.cost_actual if g.cost_actual is not None else g.cost_estimate
        if g.finished_at and g.created_at:
            run.latency_s = round((g.finished_at - g.created_at).total_seconds(), 2)


def score_run(s: Session, run_id: int, score: int | None = None,
              notes: str | None = None, winner: bool | None = None) -> VariantRun:
    run = s.get(VariantRun, run_id)
    if run is None:
        raise LabError(f"run {run_id} not found")
    if score is not None:
        if not 1 <= int(score) <= 5:
            raise LabError("score is 1–5")
        run.user_score = int(score)
    if notes is not None:
        run.user_notes = notes
    if winner is not None:
        v = s.get(PromptVariant, run.variant_id)
        if v is not None:
            v.winner = bool(winner)
    return run


def experiment_view(s: Session, experiment_id: int) -> dict:
    exp = s.get(PromptExperiment, experiment_id)
    if exp is None:
        raise LabError(f"experiment {experiment_id} not found")
    sync_runs(s, experiment_id)
    variants = list(s.execute(select(PromptVariant).where(
        PromptVariant.experiment_id == experiment_id)
        .order_by(PromptVariant.version)).scalars())
    out_vars = []
    for v in variants:
        runs = list(s.execute(select(VariantRun).where(VariantRun.variant_id == v.id)
                              .order_by(VariantRun.id)).scalars())
        out_runs = []
        for r in runs:
            g = s.get(Generation, r.generation_id) if r.generation_id else None
            post = s.get(Post, g.output_post_id) if g and g.output_post_id else None
            out_runs.append({
                "id": r.id, "generation_id": r.generation_id, "status": r.status,
                "family": r.family, "provider": r.provider,
                "provider_model_id": r.provider_model_id, "params": r.params,
                "user_score": r.user_score, "user_notes": r.user_notes,
                "evaluation": r.evaluation, "cost": r.cost, "latency_s": r.latency_s,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "output_post_id": g.output_post_id if g else None,
                "thumb_url": f"/media/{post.thumb_path.split('media/', 1)[-1]}"
                             if post and post.thumb_path else None,
                "error": g.error if g else None,
            })
        out_vars.append({
            "id": v.id, "version": v.version, "label": v.label, "origin": v.origin,
            "parent_id": v.parent_id, "prompt": v.prompt, "negative": v.negative,
            "family": v.family, "provider": v.provider, "params": v.params,
            "winner": v.winner, "archived": v.archived,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "runs": out_runs,
        })
    return {"id": exp.id, "name": exp.name, "brief": exp.brief, "intent": exp.intent,
            "notes": exp.notes, "archived": exp.archived,
            "created_at": exp.created_at.isoformat() if exp.created_at else None,
            "variants": out_vars}
