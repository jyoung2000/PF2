"""Creative Plans (spec §8): one brief → an editable multi-asset generation
plan. The planner is deterministic (campaign presets + the compiler per
asset); an LLM can draft alternative asset lists when configured, but the
plan is always materialized as rows the user can edit, lock, reorder, fork
and run asset-by-asset — nothing generates until asked."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_config
from ..models import Generation, Post
from . import compiler, tools
from .models import CreativePlan, PlanAsset


class PlanError(Exception):
    pass


# preset: (match, assets) — purpose, kind, aspect ratio, depends_on by index,
# use_hero_reference (feeds the hero output in as an image reference)
PRESETS: list[tuple[re.Pattern, str, list[dict]]] = [
    (re.compile(r"\b(launch|campaign|marketing)\b", re.I), "launch_campaign", [
        {"purpose": "Hero image", "kind": "image", "aspect_ratio": "16:9"},
        {"purpose": "Social graphic (square)", "kind": "image", "aspect_ratio": "1:1", "deps": [0], "ref": True},
        {"purpose": "Story graphic (vertical)", "kind": "image", "aspect_ratio": "9:16", "deps": [0], "ref": True},
        {"purpose": "Web banner", "kind": "image", "aspect_ratio": "21:9", "deps": [0], "ref": True},
        {"purpose": "Short vertical video", "kind": "video", "aspect_ratio": "9:16", "deps": [0], "ref": True},
        {"purpose": "Thumbnail", "kind": "image", "aspect_ratio": "16:9", "deps": [0], "ref": True},
    ]),
    (re.compile(r"\b(brand kit|logo|identity)\b", re.I), "brand_kit", [
        {"purpose": "Logo treatment", "kind": "image", "aspect_ratio": "1:1"},
        {"purpose": "Social avatar", "kind": "image", "aspect_ratio": "1:1", "deps": [0], "ref": True},
        {"purpose": "Profile banner", "kind": "image", "aspect_ratio": "21:9", "deps": [0], "ref": True},
    ]),
    (re.compile(r"\b(trailer|teaser)\b", re.I), "trailer", [
        {"purpose": "Key art poster", "kind": "image", "aspect_ratio": "2:3"},
        {"purpose": "Teaser video", "kind": "video", "aspect_ratio": "16:9", "deps": [0], "ref": True},
        {"purpose": "Thumbnail", "kind": "image", "aspect_ratio": "16:9", "deps": [0], "ref": True},
    ]),
    (re.compile(r"\b(social pack|social set)\b", re.I), "social_pack", [
        {"purpose": "Square post", "kind": "image", "aspect_ratio": "1:1"},
        {"purpose": "Vertical story", "kind": "image", "aspect_ratio": "9:16", "deps": [0], "ref": True},
        {"purpose": "Banner", "kind": "image", "aspect_ratio": "16:9", "deps": [0], "ref": True},
    ]),
]
DEFAULT_ASSETS = [
    {"purpose": "Primary image", "kind": "image", "aspect_ratio": "4:3"},
    {"purpose": "Alternate crop", "kind": "image", "aspect_ratio": "9:16", "deps": [0], "ref": True},
]


def _preset_for(brief: str) -> tuple[str, list[dict]]:
    for rx, name, assets in PRESETS:
        if rx.search(brief):
            return name, assets
    return "default", DEFAULT_ASSETS


def _llm_assets(brief: str) -> tuple[list[dict] | None, dict]:
    """Optional LLM draft of the asset list — validated hard, else discarded."""
    try:
        import json as _json

        from ..llm.client import run_llm
        raw = run_llm("forge_plan",
                      "You plan multi-asset creative campaigns. Reply ONLY with a JSON "
                      "array of assets: [{\"purpose\": str, \"kind\": \"image\"|\"video\", "
                      "\"aspect_ratio\": \"W:H\", \"prompt_hint\": str}] — at most 8.",
                      f"Brief: {brief}")
        data = _json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
        assets = []
        for i, a in enumerate(data[:8]):
            if not isinstance(a, dict) or not a.get("purpose"):
                continue
            assets.append({"purpose": str(a["purpose"])[:200],
                           "kind": "video" if a.get("kind") == "video" else "image",
                           "aspect_ratio": a.get("aspect_ratio") if
                           re.fullmatch(r"\d{1,2}:\d{1,2}", str(a.get("aspect_ratio") or "")) else None,
                           "deps": [0] if i > 0 else [], "ref": i > 0,
                           "prompt_hint": str(a.get("prompt_hint") or "")[:300]})
        if assets:
            return assets, {"applied": True}
        return None, {"applied": False, "reason": "LLM draft empty/invalid — deterministic preset used"}
    except Exception as e:
        return None, {"applied": False, "reason": str(e) or type(e).__name__}


def create_plan(s: Session, brief: str, name: str | None = None,
                use_llm: bool = False) -> CreativePlan:
    preset_name, spec = _preset_for(brief)
    llm_note = None
    if use_llm:
        drafted, llm_note = _llm_assets(brief)
        if drafted:
            spec, preset_name = drafted, "llm_draft"
    plan = CreativePlan(name=name or brief[:80], brief=brief,
                        meta={"preset": preset_name, "llm": llm_note})
    s.add(plan)
    s.flush()
    ids: list[int] = []
    for i, a in enumerate(spec):
        idea = f"{brief} — {a['purpose'].lower()}"
        if a.get("prompt_hint"):
            idea += f". {a['prompt_hint']}"
        if a["kind"] == "video":
            idea += " (short video)"
        # the asset spec's kind is authoritative — wording in the brief must
        # not re-route an image asset to another modality
        from . import intent as intent_mod
        forced = intent_mod.extract(idea)
        forced["modality"] = a["kind"]
        pkg = compiler.compile_package(s, idea, intent_override=forced)
        params = dict(pkg.get("params") or {})
        if a.get("aspect_ratio"):
            params["aspect_ratio"] = a["aspect_ratio"]
        asset = PlanAsset(
            plan_id=plan.id, order=i, purpose=a["purpose"], kind=a["kind"],
            depends_on=[ids[d] for d in a.get("deps", []) if d < len(ids)],
            family=pkg.get("family"), provider=pkg.get("provider"),
            prompt=pkg.get("optimized_prompt"), package=pkg, params=params,
            references=([{"plan_asset_id": ids[d]} for d in a.get("deps", [])
                         if d < len(ids)] if a.get("ref") else []),
            cost_estimate=pkg.get("estimated_cost"))
        s.add(asset)
        s.flush()
        ids.append(asset.id)
    return plan


def _resolve_references(s: Session, asset: PlanAsset) -> list[str]:
    """{plan_asset_id: X} → that asset's output media path (absolute)."""
    out = []
    for ref in asset.references or []:
        if isinstance(ref, dict) and ref.get("plan_asset_id"):
            dep = s.get(PlanAsset, ref["plan_asset_id"])
            g = s.get(Generation, dep.generation_id) if dep and dep.generation_id else None
            post = s.get(Post, g.output_post_id) if g and g.output_post_id else None
            if post and post.media_path:
                out.append(str(get_config().data_dir / post.media_path))
        elif isinstance(ref, str):
            out.append(ref)
    return out


def run_asset(s: Session, asset_id: int, allow_fallback: bool = False) -> dict:
    asset = s.get(PlanAsset, asset_id)
    if asset is None:
        raise PlanError(f"plan asset {asset_id} not found")
    if asset.locked:
        raise PlanError(f"'{asset.purpose}' is locked — unlock it to regenerate")
    unmet = []
    for dep_id in asset.depends_on or []:
        dep = s.get(PlanAsset, dep_id)
        if dep is None or dep.status != "succeeded":
            unmet.append(dep.purpose if dep else f"#{dep_id}")
    if unmet:
        raise PlanError("waiting on: " + ", ".join(unmet))
    refs = _resolve_references(s, asset)
    args: dict = {"prompt": asset.prompt or "", "family": asset.family,
                  "provider": asset.provider, "params": dict(asset.params or {})}
    tool = "generate_video" if asset.kind == "video" else "generate_image"
    if refs:
        if asset.kind == "video":
            tool = "image_to_video"
            args["image"] = refs[0]
        else:
            args["references"] = refs
    job = tools.invoke(s, tool, args, allow_fallback=allow_fallback)
    asset.generation_id = job["job_id"]
    asset.status = "queued"
    plan = s.get(CreativePlan, asset.plan_id)
    if plan is not None:
        plan.status = "running"
    return job


def run_plan(s: Session, plan_id: int, only_failed: bool = False,
             allow_fallback: bool = False) -> dict:
    """Queue every runnable asset (deps met, not locked, not done). Blocked
    assets are reported, not silently skipped."""
    plan = s.get(CreativePlan, plan_id)
    if plan is None:
        raise PlanError(f"plan {plan_id} not found")
    sync_plan(s, plan_id)
    queued, blocked, skipped = [], [], []
    for asset in s.execute(select(PlanAsset).where(PlanAsset.plan_id == plan_id)
                           .order_by(PlanAsset.order)).scalars():
        if asset.locked or asset.status == "succeeded" or \
                (only_failed and asset.status not in ("failed",)) or \
                asset.status in ("queued", "running"):
            skipped.append({"id": asset.id, "purpose": asset.purpose, "status": asset.status,
                            "locked": asset.locked})
            continue
        try:
            job = run_asset(s, asset.id, allow_fallback=allow_fallback)
            queued.append({"id": asset.id, "purpose": asset.purpose, "job_id": job["job_id"]})
        except (PlanError, tools.ToolError) as e:
            blocked.append({"id": asset.id, "purpose": asset.purpose, "reason": str(e)})
    return {"queued": queued, "blocked": blocked, "skipped": skipped}


def sync_plan(s: Session, plan_id: int) -> None:
    assets = list(s.execute(select(PlanAsset).where(PlanAsset.plan_id == plan_id)).scalars())
    for asset in assets:
        if asset.generation_id and asset.status in ("queued", "running"):
            g = s.get(Generation, asset.generation_id)
            if g is not None:
                asset.status = g.status
    plan = s.get(CreativePlan, plan_id)
    if plan is not None and assets:
        if all(a.status == "succeeded" or a.locked for a in assets):
            plan.status = "done"
        elif any(a.status in ("queued", "running") for a in assets):
            plan.status = "running"


def fork_plan(s: Session, plan_id: int) -> CreativePlan:
    plan = s.get(CreativePlan, plan_id)
    if plan is None:
        raise PlanError(f"plan {plan_id} not found")
    clone = CreativePlan(name=f"{plan.name} (branch)", brief=plan.brief,
                         meta={**(plan.meta or {}), "forked_from": plan.id})
    s.add(clone)
    s.flush()
    id_map: dict[int, int] = {}
    for a in s.execute(select(PlanAsset).where(PlanAsset.plan_id == plan_id)
                       .order_by(PlanAsset.order)).scalars():
        na = PlanAsset(plan_id=clone.id, order=a.order, purpose=a.purpose,
                       kind=a.kind, family=a.family, provider=a.provider,
                       prompt=a.prompt, package=dict(a.package or {}),
                       params=dict(a.params or {}), locked=a.locked,
                       cost_estimate=a.cost_estimate,
                       depends_on=list(a.depends_on or []),
                       references=list(a.references or []))
        s.add(na)
        s.flush()
        id_map[a.id] = na.id
    # remap sibling links into the clone
    for na in s.execute(select(PlanAsset).where(PlanAsset.plan_id == clone.id)).scalars():
        na.depends_on = [id_map.get(d, d) for d in na.depends_on or []]
        na.references = [({"plan_asset_id": id_map.get(r["plan_asset_id"], r["plan_asset_id"])}
                          if isinstance(r, dict) and r.get("plan_asset_id") else r)
                         for r in na.references or []]
    return clone


def plan_view(s: Session, plan_id: int) -> dict:
    plan = s.get(CreativePlan, plan_id)
    if plan is None:
        raise PlanError(f"plan {plan_id} not found")
    sync_plan(s, plan_id)
    assets = []
    for a in s.execute(select(PlanAsset).where(PlanAsset.plan_id == plan_id)
                       .order_by(PlanAsset.order)).scalars():
        g = s.get(Generation, a.generation_id) if a.generation_id else None
        post = s.get(Post, g.output_post_id) if g and g.output_post_id else None
        assets.append({
            "id": a.id, "order": a.order, "purpose": a.purpose, "kind": a.kind,
            "depends_on": a.depends_on, "family": a.family, "provider": a.provider,
            "prompt": a.prompt, "params": a.params, "references": a.references,
            "status": a.status, "locked": a.locked,
            "generation_id": a.generation_id, "cost_estimate": a.cost_estimate,
            "cost_actual": g.cost_actual if g else None,
            "error": g.error if g and g.status == "failed" else None,
            "output_post_id": g.output_post_id if g else None,
            "thumb_url": f"/media/{post.thumb_path.split('media/', 1)[-1]}"
                         if post and post.thumb_path else None,
        })
    total = sum(a["cost_estimate"] or 0 for a in assets)
    return {"id": plan.id, "name": plan.name, "brief": plan.brief,
            "status": plan.status, "meta": plan.meta,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "estimated_total": round(total, 4), "assets": assets}
