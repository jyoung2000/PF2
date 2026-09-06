"""Intelligent model router (spec §3, §12): rank catalog families for an
intent with explainable scores. Deterministic — every score has a stated
basis, every constraint that a candidate cannot meet is listed rather than
silently dropped, and the user can override everything.

Routing policy (§12): an explicit family/provider choice is honored as
given; otherwise configured free/local offers get a preference bonus when
`forge_prefer_free` is on (default), then the ranked best configured offer
wins. Fallback-on-failure is the tool layer's job (opt-in, §12.5)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..generation import pricing
from ..generation import router as gen_router
from ..models import Generation
from . import catalog, intent as intent_mod

WEIGHTS = {"task_fit": 0.24, "capability_fit": 0.16, "quality": 0.16,
           "reliability": 0.12, "cost": 0.14, "latency": 0.08,
           "availability": 0.06, "preference": 0.04}
MIN_HISTORY = 3
LATENCY_PRIOR = {"fast": 1.0, "medium": 0.65, "slow": 0.35, None: 0.6}


def _history(s: Session, provider: str, family: str) -> dict:
    rows = list(s.execute(select(Generation).where(
        Generation.provider == provider, Generation.model_family == family,
        Generation.status.in_(["succeeded", "failed"]))).scalars())
    attempts = len(rows)
    successes = sum(1 for g in rows if g.status == "succeeded")
    secs = [(g.finished_at - g.created_at).total_seconds() for g in rows
            if g.finished_at and g.created_at and g.status == "succeeded"]
    return {"attempts": attempts, "successes": successes,
            "success_rate": (successes / attempts) if attempts else None,
            "avg_seconds": (sum(secs) / len(secs)) if secs else None}


def _needed_mode(intent: dict) -> str:
    if intent.get("modality") == "video":
        return "image_to_video" if intent.get("references_needed") else "text_to_video"
    return "reference_to_image" if intent.get("references_needed") else "text_to_image"


def recommend(s: Session, intent: dict, family: str | None = None,
              provider: str | None = None, connected_only: bool = False,
              limit: int = 6) -> dict:
    """→ {intent, recommended, alternatives, candidates, policy}. Candidates
    carry scores, reasons, unsupported constraints, parameter and prompt
    recommendations, and cost estimates."""
    modality = intent.get("modality", "image")
    if modality in ("audio", "3d"):
        # honest: no catalog family serves these yet (mirrors D76 posture)
        return {"intent": intent, "recommended": None, "alternatives": [],
                "candidates": [], "policy": "explicit" if family else "ranked",
                "unsupported": f"No provider in the catalog offers {modality} generation yet — "
                               "the tool layer reports what to configure."}

    prefer_free = settings_store.get(s, "forge_prefer_free")
    prefer_free = True if prefer_free is None else bool(prefer_free)
    prefs = settings_store.get(s, "forge_provider_prefs", None) or {}
    params = intent_mod.to_params(intent)
    entries = {e["family"]: e for e in catalog.registry(s, modality=modality)}

    cands: list[dict] = []
    for fam, entry in entries.items():
        if family and fam != family:
            continue
        for offer in entry["offers"]:
            if provider and offer["provider"] != provider:
                continue
            if connected_only and not offer["connected"]:
                continue
            check = catalog.validate_params(fam, params)
            est = pricing.estimate(fam, offer["provider"],
                                   {**params, "duration_s": check["params"].get("duration_s",
                                                                                params.get("duration_s"))})
            cands.append({
                "family": fam, "display_name": entry["display_name"],
                "provider": offer["provider"], "provider_model_id": offer["provider_model_id"],
                "connected": offer["connected"], "modes": offer["modes"],
                "estimate": est, "meta": entry, "check": check,
                "history": _history(s, offer["provider"], fam),
            })
    if not cands:
        # be specific: a model can be *known* (intelligence entry) without any
        # provider selling it — that is a different problem from a typo
        known = entries.get(family) if family else None
        if known is not None:
            detail = (f"{known['display_name']} is in the model catalog but no provider "
                      "offers it here" +
                      (f" — {known['deprecation']}" if known.get("deprecation") else
                       ". Add an offer for it under Settings → AI providers → model catalog, "
                       "or pick a model with a connected provider."))
        elif family:
            detail = (f"'{family}' is not in the model catalog — check the name, or add it "
                      "under Settings → AI providers.")
        else:
            detail = "No catalog offer matches — check the model catalog in Settings."
        return {"intent": intent, "recommended": None, "alternatives": [], "candidates": [],
                "policy": "explicit" if family or provider else "ranked",
                "unsupported": detail}

    ests = [c["estimate"] for c in cands if c["estimate"] is not None]
    lo, hi = (min(ests), max(ests)) if ests else (0.0, 0.0)
    weights = dict(WEIGHTS)
    if intent.get("budget_sensitive"):
        weights["cost"] += 0.10
        weights["quality"] -= 0.05
        weights["latency"] -= 0.05

    for c in cands:
        meta, sc, reasons, unsupported = c["meta"], {}, [], []

        needed = _needed_mode(intent)
        fit = 1.0
        if intent.get("character_consistency"):
            if meta["supports"].get("character_consistency"):
                reasons.append("declares character consistency")
            else:
                fit -= 0.35
                unsupported.append("character consistency is not declared")
        if intent.get("references_needed"):
            base = needed.split("_to_")[-1]
            served = needed in c["modes"] or f"image_to_{base}" in c["modes"]
            if served:
                reasons.append("accepts reference/image inputs")
            else:
                fit -= 0.3
                unsupported.append("no reference/image input mode declared")
        if intent.get("needs_typography"):
            texty = any("typo" in x or "text" in x for x in meta.get("strengths", []))
            if texty:
                reasons.append("strong typography")
            else:
                fit -= 0.2
        sc["task_fit"] = max(0.0, fit)

        violations = c["check"]["violations"]
        sc["capability_fit"] = max(0.0, 1.0 - 0.4 * len(violations))
        for v in violations:
            unsupported.append(v["message"])

        sc["quality"] = float(meta.get("quality_prior") or 0.6)
        if meta.get("deprecation"):
            unsupported.append(meta["deprecation"])
            sc["quality"] *= 0.6            # ranked down, never hidden
        if meta.get("api_available") is False:
            unsupported.append("this model has no public API — shown for comparison only")
        h = c["history"]
        if h["attempts"] >= MIN_HISTORY:
            sc["reliability"] = float(h["success_rate"])
            reasons.append(f"{h['successes']}/{h['attempts']} past generations succeeded here")
            basis = "history"
        else:
            sc["reliability"] = 0.8
            basis = "priors (no generation history yet)"

        if c["estimate"] is None:
            sc["cost"] = 0.5
        elif hi > lo:
            sc["cost"] = 1.0 - (c["estimate"] - lo) / (hi - lo)
            if c["estimate"] == lo:
                reasons.append(f"cheapest option at ${c['estimate']:.3f}")
        else:
            sc["cost"] = 1.0
        if intent.get("budget_cap_usd") is not None and c["estimate"] is not None \
                and c["estimate"] > intent["budget_cap_usd"]:
            unsupported.append(f"estimated ${c['estimate']:.2f} exceeds the "
                               f"${intent['budget_cap_usd']:.2f} budget cap")
            sc["cost"] = 0.0

        if h["avg_seconds"]:
            sc["latency"] = max(0.0, 1.0 - min(h["avg_seconds"] / 300.0, 1.0))
        else:
            sc["latency"] = LATENCY_PRIOR.get(meta.get("latency_class"), 0.6)

        sc["availability"] = 1.0 if c["connected"] else 0.0
        if not c["connected"]:
            reasons.append("provider not connected — shown for comparison")

        pref = 0.5
        if prefs.get(c["provider"]) == "prefer":
            pref = 1.0
            reasons.append("you prefer this provider")
        elif prefs.get(c["provider"]) == "avoid":
            pref = 0.0
        if prefer_free and meta.get("availability") == "both":
            reasons.append("open weights — local execution possible")
        sc["preference"] = pref

        c["scores"] = {k: round(v, 3) for k, v in sc.items()}
        c["total"] = round(sum(weights[k] * sc[k] for k in weights), 4)
        c["reasons"] = reasons
        c["basis"] = basis
        c["unsupported_constraints"] = unsupported
        c["prompt_recommendation"] = meta["prompt"]
        c["provenance"] = {"confidence": meta.get("confidence"),
                           "source_urls": meta.get("source_urls") or [],
                           "evidence": meta.get("evidence"),
                           "last_verified": meta.get("last_verified")}
        c["parameter_recommendations"] = {
            **{v["param"]: v.get("nearest") or v.get("supported") for v in violations},
            **({"duration_s": c["check"]["params"]["duration_s"]}
               if c["check"]["params"].get("duration_s") != params.get("duration_s") else {}),
        }
        c.pop("meta", None)
        c.pop("check", None)

    cands.sort(key=lambda c: (-c["connected"], -c["total"],
                              c["estimate"] if c["estimate"] is not None else 9e9))
    top = cands[:limit]
    return {"intent": intent, "recommended": top[0] if top else None,
            "alternatives": top[1:], "candidates": top,
            "policy": "explicit" if family or provider else
                      ("prefer_free" if prefer_free else "ranked"),
            "weights": {k: round(v, 3) for k, v in weights.items()}}
