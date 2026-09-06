"""Provider-neutral tool layer (spec §7, §11): typed JSON in/out operations
that validate capability and parameters BEFORE execution, then ride the
existing generation queue. Every call returns a structured job; every
unsupported operation says exactly why and what to configure — nothing is
faked. The shapes are MCP-compatible (name + JSON schema-ish inputs) but
nothing here requires MCP.

Capability truth lives in the pricing catalog's declared `modes` (D76): the
moment a provider offer declares e.g. an `upscale` or `tts` mode with a
model id, the matching tool starts working with zero code changes here."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..film import capabilities
from ..generation import pricing, queue as gen_queue
from ..generation import router as gen_router
from ..models import Generation
from . import catalog

# mode → media kind for modes beyond the film matrix
EXTRA_MODE_KINDS = {"upscale": "image", "remove_background": "image",
                    "tts": "audio", "music": "audio", "sfx": "audio",
                    "transcription": "audio", "video_to_audio": "audio",
                    "text_to_3d": "3d", "image_to_3d": "3d"}

TOOLS: dict[str, dict] = {
    "generate_image":   {"mode": "text_to_image",   "label": "Generate image",
                         "required": {"prompt": str}, "optional": {"negative": str, "params": dict}},
    "edit_image":       {"mode": "image_to_image",  "label": "Edit image",
                         "required": {"prompt": str, "image": str},
                         "optional": {"strength": float, "params": dict}},
    "generate_video":   {"mode": "text_to_video",   "label": "Generate video",
                         "required": {"prompt": str}, "optional": {"negative": str, "params": dict}},
    "image_to_video":   {"mode": "image_to_video",  "label": "Image → video",
                         "required": {"prompt": str, "image": str}, "optional": {"params": dict}},
    "upscale_image":    {"mode": "upscale",         "label": "Upscale image",
                         "required": {"image": str}, "optional": {"params": dict}},
    "remove_background": {"mode": "remove_background", "label": "Remove background",
                          "required": {"image": str}, "optional": {"params": dict}},
    "generate_speech":  {"mode": "tts",             "label": "Text → speech",
                         "required": {"prompt": str}, "optional": {"params": dict}},
    "generate_music":   {"mode": "music",           "label": "Generate music",
                         "required": {"prompt": str}, "optional": {"params": dict}},
    "transcribe_audio": {"mode": "transcription",   "label": "Speech → text",
                         "required": {"audio": str}, "optional": {"params": dict}},
    "generate_3d":      {"mode": "text_to_3d",      "label": "Generate 3D",
                         "required": {"prompt": str}, "optional": {"params": dict}},
    "video_to_audio":   {"mode": "video_to_audio",  "label": "Video → audio",
                         "required": {"video": str}, "optional": {"params": dict}},
}


class ToolError(Exception):
    """Structured, user-fixable tool failure (§20)."""

    def __init__(self, message: str, *, recoverable: bool = True,
                 next_action: str | None = None, provider: str | None = None,
                 model: str | None = None):
        super().__init__(message)
        self.detail = {"message": message, "recoverable": recoverable,
                       "next_action": next_action, "provider": provider, "model": model}


def _mode_kind(mode: str) -> str:
    return EXTRA_MODE_KINDS.get(mode) or capabilities.MODE_KINDS.get(mode, "image")


def _offers_for_mode(s: Session, mode: str, family: str | None = None,
                     provider: str | None = None) -> list[dict]:
    """Connected offers declaring the mode (base modes come from the family
    kind; extra modes only exist when explicitly declared in the catalog)."""
    real = capabilities.resolve_mode(mode)
    out = []
    for o in capabilities.offers(s):
        if not o["connected"]:
            continue
        if family and o["family"] != family:
            continue
        if provider and o["provider"] != provider:
            continue
        model_id = o["modes"].get(real)
        if not model_id and real in EXTRA_MODE_KINDS:
            declared = pricing.modes_for(o["family"], o["provider"]).get(real) or {}
            model_id = declared.get("model_id")
        if model_id:
            out.append({**o, "mode_model_id": model_id})
    return out


def availability(s: Session) -> list[dict]:
    """Every tool with supported/why — the honest capability report (§7)."""
    out = []
    for name, spec in TOOLS.items():
        offers = _offers_for_mode(s, spec["mode"])
        entry = {"name": name, "label": spec["label"], "mode": spec["mode"],
                 "kind": _mode_kind(spec["mode"]),
                 "input_schema": {"required": {k: t.__name__ for k, t in spec["required"].items()},
                                  "optional": {k: t.__name__ for k, t in spec["optional"].items()}},
                 "supported": bool(offers),
                 "families": sorted({o["family"] for o in offers})}
        if not offers:
            entry["reason"] = capabilities.EXTRA_CAPABILITIES.get(
                spec["mode"],
                "No connected provider declares this mode — connect a provider in "
                "Settings → AI providers, or declare the mode for one in the pricing catalog.")
        out.append(entry)
    return out


def _validate_args(name: str, args: dict) -> dict:
    spec = TOOLS[name]
    clean: dict = {}
    for key, typ in spec["required"].items():
        if key not in args or args[key] in (None, ""):
            raise ToolError(f"'{key}' is required for {name}",
                            next_action=f"pass {key} ({typ.__name__})")
        if not isinstance(args[key], typ):
            raise ToolError(f"'{key}' must be {typ.__name__}", next_action="fix the argument type")
        clean[key] = args[key]
    for key, typ in spec["optional"].items():
        if key in args and args[key] is not None:
            if not isinstance(args[key], typ):
                raise ToolError(f"'{key}' must be {typ.__name__}", next_action="fix the argument type")
            clean[key] = args[key]
    return clean


def invoke(s: Session, name: str, args: dict, allow_fallback: bool = False) -> dict:
    """Validate → pick the offer → create the job → enqueue. → structured
    {job_id, status, tool, family, provider, mode, estimate}."""
    if name not in TOOLS:
        raise ToolError(f"unknown tool '{name}'", recoverable=False,
                        next_action=f"one of: {', '.join(sorted(TOOLS))}")
    spec = TOOLS[name]
    clean = _validate_args(name, args)
    mode = spec["mode"]
    kind = _mode_kind(mode)
    if kind in ("audio", "3d"):
        # honest: the queue ingests image/video outputs; audio/3d land the
        # moment an adapter declares them AND the ingest path learns the type
        offers = _offers_for_mode(s, mode, args.get("family"), args.get("provider"))
        if not offers:
            raise ToolError(capabilities.EXTRA_CAPABILITIES.get(
                mode, f"no connected provider declares {mode}"),
                next_action="declare the mode for a connected provider in the pricing catalog")

    offers = _offers_for_mode(s, mode, args.get("family"), args.get("provider"))
    if not offers:
        raise ToolError(
            f"{spec['label']} is not available: no connected provider declares "
            f"{mode.replace('_', ' ')}"
            + (f" for {args['family']}" if args.get("family") else ""),
            next_action="connect a provider under Settings → AI providers")

    params = dict(clean.get("params") or {})
    fam_order = sorted(offers, key=lambda o: (
        pricing.estimate_mode(o["family"], o["provider"], capabilities.resolve_mode(mode), params) or 9e9))
    chosen = fam_order[0]
    family = chosen["family"]

    check = catalog.validate_params(family, {**params, **(
        {"_inputs": {"references": args.get("references") or []}} if args.get("references") else {})},
        mode=mode)
    params = {k: v for k, v in check["params"].items() if k != "_inputs"}

    real = capabilities.resolve_mode(mode)
    gen_params = dict(params)
    gen_params["_tool"] = name
    gen_params["_mode"] = real
    if allow_fallback:
        gen_params["_allow_fallback"] = True
    inputs = {k: clean[k] for k in ("image", "audio", "video") if clean.get(k)}
    if args.get("references"):
        inputs["references"] = list(args["references"])[:6]
    if clean.get("strength") is not None:
        inputs["strength"] = clean["strength"]
    if inputs:
        gen_params["_inputs"] = inputs
        gen_params["_input_map"] = capabilities.inputs_map(family, chosen["provider"], real)
    if clean.get("negative"):
        gen_params["_negative"] = clean["negative"]

    est = pricing.estimate_mode(family, chosen["provider"], real, params)
    g = Generation(provider=chosen["provider"], provider_model_id=chosen["mode_model_id"],
                   model_family=family, prompt=clean.get("prompt") or "",
                   cost_estimate=est, status="queued", params=gen_params)
    s.add(g)
    s.commit()
    gen_queue.start_worker()
    gen_queue.enqueue(g.id)
    return {"job_id": g.id, "status": "queued", "tool": name, "family": family,
            "provider": chosen["provider"], "provider_model_id": chosen["mode_model_id"],
            "mode": real, "estimate": est,
            "warnings": check["warnings"] + [v["message"] for v in check["violations"]]}


def job_status(s: Session, job_id: int) -> dict:
    """§20 structured status for one job, fallback lineage included."""
    g = s.get(Generation, job_id)
    if g is None:
        raise ToolError(f"job {job_id} not found", recoverable=False)
    out = {"job_id": g.id, "status": g.status, "tool": (g.params or {}).get("_tool"),
           "provider": g.provider, "family": g.model_family,
           "provider_model_id": g.provider_model_id,
           "estimate": g.cost_estimate, "cost_actual": g.cost_actual,
           "output_post_id": g.output_post_id,
           "created_at": g.created_at.isoformat() if g.created_at else None,
           "finished_at": g.finished_at.isoformat() if g.finished_at else None}
    if g.status == "failed":
        offers = _offers_for_mode(s, (g.params or {}).get("_mode") or "text_to_image")
        others = [o["provider"] for o in offers if o["provider"] != g.provider]
        out["error"] = {"message": g.error, "provider": g.provider,
                        "model": g.provider_model_id,
                        "recoverable": bool(others),
                        "fallback_options": others,
                        "next_action": (f"retry on {others[0]}" if others else
                                        "check the provider key / status in Settings")}
    fb = (g.params or {}).get("_fallback_of")
    if fb:
        out["fallback_of"] = fb
    return out


def attempt_fallback(gid: int) -> int | None:
    """§12.5: after a provider failure, retry ONCE on the next eligible
    connected offer — only when the job opted in, always as a NEW visible
    generation linked to the failed one, never silently."""
    from ..db import session_scope
    from ..logbus import bus
    with session_scope() as s:
        g = s.get(Generation, gid)
        if g is None or not (g.params or {}).get("_allow_fallback") \
                or (g.params or {}).get("_fallback_of"):
            return None
        mode = (g.params or {}).get("_mode") or (
            "text_to_video" if gen_router.kind_of(g.model_family or "") == "video" else "text_to_image")
        offers = [o for o in _offers_for_mode(s, mode, family=g.model_family)
                  if o["provider"] != g.provider]
        if not offers:
            offers = [o for o in _offers_for_mode(s, mode) if o["provider"] != g.provider]
        if not offers:
            return None
        nxt = offers[0]
        params = {k: v for k, v in (g.params or {}).items() if k != "_allow_fallback"}
        params["_fallback_of"] = g.id
        if params.get("_inputs"):
            params["_input_map"] = capabilities.inputs_map(nxt["family"], nxt["provider"],
                                                           capabilities.resolve_mode(mode))
        est = pricing.estimate_mode(nxt["family"], nxt["provider"],
                                    capabilities.resolve_mode(mode), params)
        g2 = Generation(provider=nxt["provider"], provider_model_id=nxt["mode_model_id"],
                        model_family=nxt["family"], prompt=g.prompt,
                        cost_estimate=est, status="queued", params=params)
        s.add(g2)
        s.flush()
        new_id = g2.id
        bus.warn("generation",
                 f"#{gid} failed on {g.provider} — falling back to {nxt['provider']} as #{new_id} "
                 "(opted in)")
    gen_queue.enqueue(new_id)
    return new_id
