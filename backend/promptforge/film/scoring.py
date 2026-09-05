"""Provider scoring (spec R): rank connected provider offers for a task by
task fit, quality prior, controllability, consistency (frame control),
reliability (this installation's take history), cost and latency. Every
score carries its basis; priors are labelled priors and history is only
used when it exists."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..generation import pricing
from . import capabilities
from .models import FilmTake

WEIGHTS = {"task_fit": 0.25, "quality": 0.15, "controllability": 0.10, "consistency": 0.15,
           "reliability": 0.15, "cost": 0.15, "latency": 0.05}
# static quality priors per family (0–1) — editable via settings film_provider_quality {family: score}
QUALITY_PRIOR = {"veo": 0.95, "kling": 0.85, "seedream": 0.85, "flux-pro": 0.9, "flux": 0.8,
                 "ideogram": 0.8, "recraft": 0.8, "hailuo": 0.75, "seedance": 0.75, "qwen-image": 0.75,
                 "wan": 0.7, "hunyuan": 0.7, "sd3": 0.7, "sdxl": 0.6, "ltx-video": 0.5}
MIN_HISTORY = 3


def history(s: Session, provider: str, family: str) -> dict:
    rows = list(s.execute(select(FilmTake).where(FilmTake.provider == provider,
                                                 FilmTake.model_family == family,
                                                 FilmTake.status.in_(["succeeded", "failed"]))).scalars())
    attempts = len(rows)
    successes = sum(1 for t in rows if t.status == "succeeded")
    secs = [(t.finished_at - t.created_at).total_seconds() for t in rows
            if t.finished_at and t.created_at and t.status == "succeeded"]
    return {"attempts": attempts, "successes": successes,
            "success_rate": (successes / attempts) if attempts else None,
            "avg_seconds": (sum(secs) / len(secs)) if secs else None}


def score_candidates(s: Session, mode: str, kind: str, params: dict | None = None,
                     family: str | None = None, provider: str | None = None,
                     connected_only: bool = True) -> list[dict]:
    real = capabilities.resolve_mode(mode)
    aliased = real != mode
    quality_over = settings_store.get(s, "film_provider_quality", None) or {}
    cands = []
    for o in capabilities.offers(s, kind):
        if connected_only and not o["connected"]:
            continue
        if family and o["family"] != family:
            continue
        if provider and o["provider"] != provider:
            continue
        model_id = o["modes"].get(real)
        if not model_id:
            continue
        est = pricing.estimate_mode(o["family"], o["provider"], real, params)
        h = history(s, o["provider"], o["family"])
        kind_modes = [m["key"] for m in capabilities.MODES if m["kind"] == kind and m["key"] not in capabilities.ALIASES]
        declared = [m for m in kind_modes if m in o["modes"]]
        cands.append({"family": o["family"], "label": o["label"], "provider": o["provider"],
                      "model_id": model_id, "mode": real, "requested_mode": mode, "estimate": est,
                      "history": h, "declared_modes": declared,
                      "quality_prior": float(quality_over.get(o["family"], QUALITY_PRIOR.get(o["family"], 0.65))),
                      "_aliased": aliased, "_kind_modes": len(kind_modes)})
    if not cands:
        return []
    ests = [c["estimate"] for c in cands if c["estimate"] is not None]
    lo, hi = (min(ests), max(ests)) if ests else (0.0, 0.0)
    for c in cands:
        sc = {}
        reasons = []
        sc["task_fit"] = 0.6 if c["_aliased"] else 1.0
        reasons.append(f"declares {c['requested_mode'].replace('_', ' ')}" if not c["_aliased"]
                       else f"serves {c['requested_mode'].replace('_', ' ')} through {c['mode'].replace('_', ' ')}")
        sc["quality"] = c["quality_prior"]
        sc["controllability"] = len(c["declared_modes"]) / max(1, c["_kind_modes"])
        if kind == "video":
            sc["consistency"] = 1.0 if "start_end_to_video" in c["declared_modes"] else (
                0.6 if "image_to_video" in c["declared_modes"] else 0.4)
            if "start_end_to_video" in c["declared_modes"]:
                reasons.append("supports start + end frames")
        else:
            sc["consistency"] = 1.0 if "reference_to_image" in c["declared_modes"] else (
                0.6 if "image_to_image" in c["declared_modes"] else 0.4)
            if "reference_to_image" in c["declared_modes"]:
                reasons.append("supports reference images")
        h = c["history"]
        if h["attempts"] >= MIN_HISTORY:
            sc["reliability"] = float(h["success_rate"])
            reasons.append(f"{h['successes']}/{h['attempts']} past takes succeeded")
            basis = "history"
        else:
            sc["reliability"] = 0.8
            basis = "priors (no take history yet)"
        if c["estimate"] is None:
            sc["cost"] = 0.5
            reasons.append("price unknown")
        elif hi > lo:
            sc["cost"] = 1.0 - (c["estimate"] - lo) / (hi - lo)
            if c["estimate"] == lo:
                reasons.append(f"cheapest option at ${c['estimate']:.3f}")
        else:
            sc["cost"] = 1.0
            reasons.append(f"${c['estimate']:.3f}")
        if h["avg_seconds"]:
            sc["latency"] = max(0.0, 1.0 - min(h["avg_seconds"] / 300.0, 1.0))
        else:
            sc["latency"] = 0.7
        c["scores"] = {k: round(v, 3) for k, v in sc.items()}
        c["total"] = round(sum(WEIGHTS[k] * sc[k] for k in WEIGHTS), 4)
        c["reasons"] = reasons
        c["basis"] = basis
        c.pop("_aliased", None)
        c.pop("_kind_modes", None)
    cands.sort(key=lambda c: (-c["total"], c["estimate"] if c["estimate"] is not None else 9e9))
    return cands


def pick(s: Session, mode: str, kind: str, params: dict | None = None,
         family: str | None = None, provider: str | None = None) -> tuple[dict | None, list[dict]]:
    ranked = score_candidates(s, mode, kind, params, family, provider)
    return (ranked[0] if ranked else None), ranked


def decision(best: dict, ranked: list[dict], user_override: bool = False) -> dict:
    """What gets logged with a take (spec R/X): selection, alternatives,
    reasons, basis, cost."""
    return {"selected": {k: best[k] for k in ("family", "provider", "model_id", "mode", "estimate", "total")},
            "reason": "; ".join(best["reasons"]), "basis": best["basis"], "scores": best["scores"],
            "alternatives": [{k: c[k] for k in ("family", "provider", "model_id", "estimate", "total")}
                             for c in ranked[1:4]],
            "user_override": user_override}
