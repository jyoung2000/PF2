"""Usage + cost transparency (spec §13): aggregate what actually happened
across generations and lab runs. Answers, from real rows only: which model
is cheapest, which fails most, which prompts scored best per dollar."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..models import Generation
from .models import VariantRun


def report(s: Session, limit_recent: int = 20) -> dict:
    gens = list(s.execute(select(Generation)).scalars())
    rows: dict[tuple, dict] = {}
    fallbacks = 0
    for g in gens:
        params = g.params or {}
        if params.get("_fallback_of"):
            fallbacks += 1
        key = (g.provider, g.model_family or "?")
        r = rows.setdefault(key, {"provider": key[0], "family": key[1],
                                  "attempts": 0, "succeeded": 0, "failed": 0,
                                  "est_cost": 0.0, "actual_cost": 0.0,
                                  "latencies": [], "fallbacks_in": 0})
        r["attempts"] += 1
        if g.status == "succeeded":
            r["succeeded"] += 1
            r["actual_cost"] += float(g.cost_actual or g.cost_estimate or 0)
        elif g.status == "failed":
            r["failed"] += 1
        r["est_cost"] += float(g.cost_estimate or 0)
        if params.get("_fallback_of"):
            r["fallbacks_in"] += 1
        if g.finished_at and g.created_at and g.status == "succeeded":
            r["latencies"].append((g.finished_at - g.created_at).total_seconds())

    # user scores per family (lab runs) → results per dollar
    scores: dict[str, dict] = {}
    for run in s.execute(select(VariantRun).where(VariantRun.user_score.is_not(None))).scalars():
        fam = run.family or "?"
        sc = scores.setdefault(fam, {"scores": [], "cost": 0.0})
        sc["scores"].append(run.user_score)
        sc["cost"] += float(run.cost or 0)

    models = []
    for r in rows.values():
        lat = r.pop("latencies")
        done = r["succeeded"] + r["failed"]
        fam_scores = scores.get(r["family"])
        models.append({**r,
                       "est_cost": round(r["est_cost"], 4),
                       "actual_cost": round(r["actual_cost"], 4),
                       "success_rate": round(r["succeeded"] / done, 3) if done else None,
                       "avg_latency_s": round(sum(lat) / len(lat), 1) if lat else None,
                       "avg_score": (round(sum(fam_scores["scores"]) / len(fam_scores["scores"]), 2)
                                     if fam_scores else None),
                       "score_per_dollar": (round(sum(fam_scores["scores"]) / fam_scores["cost"], 2)
                                            if fam_scores and fam_scores["cost"] > 0 else None)})
    models.sort(key=lambda m: -m["attempts"])

    recent = [{"id": g.id, "provider": g.provider, "family": g.model_family,
               "status": g.status, "cost": g.cost_actual or g.cost_estimate,
               "tool": (g.params or {}).get("_tool"),
               "fallback_of": (g.params or {}).get("_fallback_of"),
               "created_at": g.created_at.isoformat() if g.created_at else None}
              for g in sorted(gens, key=lambda g: g.id, reverse=True)[:limit_recent]]

    spend = settings_store.get(s, "gen_spend", None) or {}
    return {"totals": {"generations": len(gens),
                       "succeeded": sum(1 for g in gens if g.status == "succeeded"),
                       "failed": sum(1 for g in gens if g.status == "failed"),
                       "fallbacks": fallbacks,
                       "estimated_spend": round(sum(float(g.cost_estimate or 0) for g in gens), 4),
                       "recorded_spend": round(sum(float(v) for v in spend.values()), 4)},
            "by_provider_spend": spend, "models": models, "recent": recent}
