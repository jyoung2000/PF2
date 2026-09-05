"""AI tools on assets (spec §8): Generate / Variation / Edit from the
canonical context + selected references + locked properties + the requested
change, through the same provider router/queue as everything else. The
output lands as a new reference (kind `generated`) with full provenance —
never overwriting an existing reference or version."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..db import session_scope
from ..generation import queue as gen_queue
from ..models import Generation, Post
from . import assets as asset_svc
from . import capabilities, context as ctx_mod, events, refs as ref_svc, scoring
from . import takes as take_svc
from .models import FilmAsset, FilmAssetRef

TOOLS = {
    "generate": {"label": "Generate", "mode": "text_to_image", "what": "A new reference from the canonical description."},
    "variation": {"label": "Variation", "mode": "reference_to_image", "what": "Keep identity from the primary reference, vary the rest."},
    "edit": {"label": "Edit", "mode": "image_to_image", "what": "Change one thing about the primary reference."},
}
UNSUPPORTED = {"upscale": "upscale", "remove_background": "remove_background", "expand": "inpainting",
               "inpaint": "inpainting"}


class AssetGenError(ValueError):
    pass


def tools_for(s: Session, asset: FilmAsset) -> list[dict]:
    """Which AI tools are usable right now (provider-declared only)."""
    available = capabilities.modes_available(s, "image")
    has_primary = bool(_primary_path(s, asset))
    out = []
    for key, t in TOOLS.items():
        supported = t["mode"] in available
        needs_ref = t["mode"] != "text_to_image"
        reason = None
        if not supported:
            reason = f"No connected provider declares {t['mode'].replace('_', ' ')}."
        elif needs_ref and not has_primary:
            reason = "Add a reference image first (used as the identity anchor)."
        out.append({"key": key, "label": t["label"], "mode": t["mode"], "what": t["what"],
                    "supported": supported and (has_primary or not needs_ref), "reason": reason,
                    "families": available.get(t["mode"], [])})
    extra = capabilities.matrix(s)["extra"]
    for key, cap in UNSUPPORTED.items():
        out.append({"key": key, "label": key.replace("_", " ").title(), "mode": cap, "supported": False,
                    "reason": extra[cap]["reason"], "families": []})
    return out


def _primary_path(s: Session, asset: FilmAsset):
    v = asset_svc.current_version(s, asset)
    refs = asset_svc.refs_visible(s, asset.id, v.id)
    primary = next((r for r in refs if r.id == v.primary_ref_id), refs[0] if refs else None)
    return take_svc.abs_path(primary.path) if primary else None


def build_prompt(s: Session, asset: FilmAsset, instruction: str | None, tool: str) -> tuple[str, str]:
    ctx = asset_svc.context_for(s, asset)
    base = ctx_mod.describe(ctx, max_chars=900)
    kind_line = {"character": "Character reference portrait, neutral studio background, full detail on the face",
                 "location": "Location reference plate, wide establishing view", "prop": "Product-style prop reference on neutral background",
                 "vehicle": "Vehicle reference, three-quarter view", "outfit": "Outfit reference on a mannequin, front view",
                 "style": "Style frame"}.get(asset.type, "Reference image")
    parts = [kind_line, base]
    if instruction:
        parts.append(("Change only: " if tool == "edit" else "Direction: ") + instruction.strip()[:600])
    if ctx["locked_attributes"]:
        parts.append("Keep exactly: " + ", ".join(a["label"].lower() for a in ctx["locked_attributes"]))
    negative = ", ".join(ctx.get("negative_constraints") or [])
    return ". ".join(p.rstrip(".") for p in parts) + ".", negative


def generate(s: Session, asset: FilmAsset, tool: str = "generate", instruction: str | None = None,
             family: str | None = None, provider: str | None = None, strength: float | None = None,
             kind: str | None = None, actor: str = "user") -> dict:
    if tool not in TOOLS:
        raise AssetGenError("tool must be generate | variation | edit")
    mode = TOOLS[tool]["mode"]
    family = (family or settings_store.get(s, "film_image_family") or "flux").lower()
    best, ranked = scoring.pick(s, mode, "image", {"size": "1024x1024"}, family, provider)
    if best is None:
        best, ranked = scoring.pick(s, mode, "image", {"size": "1024x1024"}, None, provider)
    if best is None:
        raise AssetGenError(f"No connected provider declares {mode.replace('_', ' ')} — connect one in Settings → AI providers.")
    inputs: dict = {}
    if mode != "text_to_image":
        primary = _primary_path(s, asset)
        if primary is None:
            raise AssetGenError("Add a reference image first — it is the identity anchor for variations and edits.")
        inputs["image"] = str(primary)
        if mode == "image_to_image":
            inputs["strength"] = float(strength if strength is not None else 0.55)
    prompt, negative = build_prompt(s, asset, instruction, tool)
    params: dict = {"size": "1024x1024", "_film_asset_id": asset.id, "_film_tool": tool,
                    "_film_ref_kind": kind or ("portrait" if asset.type == "character" else "custom"),
                    "_mode": capabilities.resolve_mode(mode)}
    if inputs:
        params["_inputs"] = inputs
        params["_input_map"] = capabilities.inputs_map(best["family"], best["provider"], capabilities.resolve_mode(mode))
    if negative:
        params["_negative"] = negative
    g = Generation(provider=best["provider"], provider_model_id=best["model_id"], model_family=best["family"],
                   prompt=prompt, cost_estimate=best["estimate"], status="queued", params=params)
    s.add(g)
    s.flush()
    events.log(s, asset.project_id, f"{asset.name}: {TOOLS[tool]['label'].lower()} queued on {best['provider']} · {best['family']}",
               kind="generation", stage="assets", actor=actor, reason=scoring.decision(best, ranked)["reason"],
               entity=("asset", asset.id), data={"generation_id": g.id, "estimate_usd": best["estimate"], "tool": tool})
    s.commit()
    gen_queue.start_worker()
    gen_queue.enqueue(g.id)
    return {"generation_id": g.id, "provider": best["provider"], "family": best["family"], "mode": mode,
            "estimate_usd": best["estimate"], "prompt": prompt, "status": "queued"}


def on_generation(gid: int, status: str) -> None:
    with session_scope() as s:
        g = s.get(Generation, gid)
        if g is None:
            return
        params = g.params or {}
        asset = s.get(FilmAsset, int(params.get("_film_asset_id") or 0))
        if asset is None:
            return
        if status != "succeeded" or not g.output_post_id:
            events.log(s, asset.project_id, f"{asset.name}: generation failed", kind="generation", stage="assets",
                       actor="system", reason=g.error, entity=("asset", asset.id), data={"generation_id": gid})
            return
        post = s.get(Post, g.output_post_id)
        if post is None:
            return
        ref, deduped = ref_svc.import_from_post(s, asset, post.id, kind=params.get("_film_ref_kind") or "custom",
                                                label=f"{TOOLS.get(params.get('_film_tool'), {}).get('label', 'Generated')} · {g.model_family}",
                                                actor="system")
        if not deduped:
            ref.source = f"generation:{gid}"
            ref.provenance = {**(ref.provenance or {}), "origin": "generated", "generation_id": gid,
                              "tool": params.get("_film_tool"), "provider": g.provider, "model_family": g.model_family,
                              "prompt": (g.prompt or "")[:800],
                              "cost_usd": g.cost_actual if g.cost_actual is not None else g.cost_estimate}
        s.flush()
        events.log(s, asset.project_id,
                   f"{asset.name}: new generated reference" if not deduped else
                   f"{asset.name}: generation returned an image identical to reference {ref.id}",
                   kind="generation", stage="assets", actor="system", entity=("asset", asset.id),
                   data={"ref_id": ref.id, "generation_id": gid, "deduped": deduped,
                         "cost_usd": g.cost_actual if g.cost_actual is not None else g.cost_estimate})


def generations_of(s: Session, asset: FilmAsset, limit: int = 20) -> list[dict]:
    rows = s.execute(select(Generation).order_by(Generation.id.desc()).limit(200)).scalars()
    out = []
    for g in rows:
        if int((g.params or {}).get("_film_asset_id") or 0) != asset.id:
            continue
        ref = s.execute(select(FilmAssetRef).where(FilmAssetRef.source == f"generation:{g.id}")).scalar_one_or_none()
        if ref is None and g.output_post_id:
            ref = s.execute(select(FilmAssetRef).where(FilmAssetRef.asset_id == asset.id,
                                                       FilmAssetRef.source_post_id == g.output_post_id)).scalar_one_or_none()
        out.append({"generation_id": g.id, "status": g.status, "error": g.error, "provider": g.provider,
                    "model_family": g.model_family, "tool": (g.params or {}).get("_film_tool"),
                    "cost_estimate": g.cost_estimate, "cost_actual": g.cost_actual, "prompt": g.prompt,
                    "ref": asset_svc.ref_dict(ref) if ref else None, "post_id": g.output_post_id,
                    "created_at": g.created_at.isoformat() if g.created_at else None,
                    "finished_at": g.finished_at.isoformat() if g.finished_at else None})
        if len(out) >= limit:
            break
    return out


def sync_pending(s: Session, asset: FilmAsset) -> None:
    """Reconcile generations that finished while no hook ran."""
    for g in s.execute(select(Generation).where(Generation.status == "succeeded")).scalars():
        p = g.params or {}
        if int(p.get("_film_asset_id") or 0) != asset.id or not g.output_post_id:
            continue
        exists = s.execute(select(FilmAssetRef.id).where(FilmAssetRef.source == f"generation:{g.id}")).first()
        if exists is None:
            post = s.get(Post, g.output_post_id)
            if post is not None:
                dup = s.execute(select(FilmAssetRef).where(FilmAssetRef.asset_id == asset.id,
                                                           FilmAssetRef.source_post_id == post.id)).first()
                if dup is None:
                    on_generation(g.id, "succeeded")
