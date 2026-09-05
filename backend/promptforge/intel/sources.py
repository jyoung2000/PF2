"""Source efficiency metrics (I4.2): per-adapter run history → discovery /
enrichment / prompt / metadata yields, duplicate and AI-content rates, LLM
cost, reliability → an ADVISORY scrape-priority recommendation. Nothing is
ever disabled automatically."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy import func, select

from ..models import PipelineJob, Post, ScraperState

HISTORY = 20


def record_run(s, name: str, stats, duration_s: float | None = None) -> dict:
    """Append one run's counters to ScraperState.state['runs'] (rolling)."""
    st = s.get(ScraperState, name)
    if st is None:
        return {}
    state = dict(st.state or {})
    runs = list(state.get("runs") or [])
    runs.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "found": stats.found, "new": stats.new, "dupes": stats.duplicates,
        "filtered": getattr(stats, "filtered", 0), "skipped": stats.skipped,
        "errors": stats.errors, "near_dups": getattr(stats, "near_dups", 0),
        "duration_s": round(duration_s, 1) if duration_s is not None else None,
        "ok": stats.errors < max(1, stats.found),
    })
    state["runs"] = runs[-HISTORY:]
    st.state = state
    s.flush()
    return state


def _rate(n: float, d: float) -> float:
    return round(n / d, 3) if d else 0.0


def platform_yields(s, platform: str) -> dict:
    """Cheap aggregates over stored posts for one platform."""
    total = s.execute(select(func.count()).select_from(Post).where(Post.platform == platform)).scalar_one()
    if not total:
        return {"posts": 0}
    with_prompt = s.execute(select(func.count()).select_from(Post).where(
        Post.platform == platform, Post.prompt.is_not(None), Post.prompt != "")).scalar_one()
    with_meta = s.execute(select(func.count()).select_from(Post).where(
        Post.platform == platform, Post.params.like('%"metadata_format"%'))).scalar_one()
    ai = s.execute(select(func.count()).select_from(Post).where(
        Post.platform == platform, Post.ai_status.in_(("definitely_ai", "probably_ai")))).scalar_one()
    enriched = s.execute(select(func.count()).select_from(Post).where(
        Post.platform == platform, Post.pipeline_state.in_(("enriched", "analyzed")))).scalar_one()
    avg_insp = s.execute(select(func.avg(Post.inspiration_score)).where(
        Post.platform == platform)).scalar_one() or 0
    llm_jobs = s.execute(select(func.count()).select_from(PipelineJob).join(
        Post, Post.id == PipelineJob.post_id).where(
        Post.platform == platform, PipelineJob.stage == "analysis",
        PipelineJob.state == "complete")).scalar_one()
    return {"posts": total, "prompt_yield": _rate(with_prompt, total),
            "metadata_yield": _rate(with_meta, total), "ai_rate": _rate(ai, total),
            "enrichment_yield": _rate(enriched, total), "avg_inspiration": round(float(avg_insp), 1),
            "llm_calls": llm_jobs, "llm_cost_per_post": _rate(llm_jobs, total)}


def source_report(s, name: str) -> dict:
    st = s.get(ScraperState, name)
    runs = list((st.state or {}).get("runs") or []) if st else []
    found = sum(r.get("found", 0) for r in runs)
    new = sum(r.get("new", 0) for r in runs)
    dupes = sum(r.get("dupes", 0) for r in runs)
    filtered = sum(r.get("filtered", 0) for r in runs)
    errors = sum(1 for r in runs if not r.get("ok", True))
    yields = platform_yields(s, name)
    discovery_yield = _rate(new, found)
    dup_rate = _rate(dupes, found)
    reliability = _rate(len(runs) - errors, len(runs)) if runs else None
    # advisory priority: value per unit of work
    value = (yields.get("prompt_yield", 0) * 0.35 + yields.get("metadata_yield", 0) * 0.25
             + yields.get("ai_rate", 0) * 0.15 + min(1, yields.get("avg_inspiration", 0) / 100) * 0.25)
    efficiency = round(100 * value * (0.5 + 0.5 * discovery_yield) * (1 - 0.5 * dup_rate)
                       * (reliability if reliability is not None else 1), 1)
    if not runs:
        recommendation = "no data yet"
    elif efficiency >= 45 and discovery_yield >= 0.3:
        recommendation = "raise priority — high yield per run"
    elif efficiency < 12 or dup_rate > 0.85:
        recommendation = "lower priority — mostly duplicates / little new"
    else:
        recommendation = "keep"
    return {"name": name, "runs": len(runs), "discovered": found, "kept": new, "duplicates": dupes,
            "filtered": filtered, "discovery_yield": discovery_yield, "duplicate_rate": dup_rate,
            "reliability": reliability, "efficiency": efficiency, "recommendation": recommendation,
            "last_runs": runs[-5:], **yields}


def all_reports(s) -> list[dict]:
    from ..scrapers import all_adapters
    reports = [source_report(s, name) for name in all_adapters()]
    reports.sort(key=lambda r: -r["efficiency"])
    return reports
