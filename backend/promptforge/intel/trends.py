"""Trend intelligence (I6.4): weekly time series over stored posts for
models, techniques, styles, prompt terms, creators, topics and formats —
deterministic first; an optional LLM summary is grounded ONLY in these
numbers (the JSON is the prompt) and stored with its timestamp."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .. import settings_store
from ..knowledge import stats as kstats
from ..models import Creator, PipelineJob, Post
from . import clusters, provenance

KINDS = ("models", "techniques", "styles", "terms", "creators", "topics", "formats")


def _week(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%G-W%V")


def _weeks_back(n: int, now: datetime) -> list[str]:
    out = []
    for i in range(n - 1, -1, -1):
        out.append(_week(now - timedelta(weeks=i)))
    return out


def weekly_series(s, weeks: int = 12, now: datetime | None = None, top: int = 8) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(weeks=weeks)
    when = func.coalesce(Post.posted_at, Post.scraped_at)
    posts = s.execute(select(Post).where(when >= since).order_by(Post.id.desc()).limit(20_000)).scalars().all()
    creators = {c.id: c.handle for c in s.execute(select(Creator)).scalars()}
    labels = _weeks_back(weeks, now)
    counts: dict[str, dict[str, Counter]] = {k: defaultdict(Counter) for k in KINDS}
    for p in posts:
        dt = p.posted_at or p.scraped_at
        if not dt:
            continue
        w = _week(dt)
        if w not in labels:
            continue
        if p.model_family and p.model_source in ("explicit", "metadata"):
            counts["models"][p.model_family][w] += 1
        for t in p.technique_tags or []:
            counts["techniques"][t][w] += 1
        assigned = clusters.assign(clusters._view(p, creators))
        for key, _ in assigned.get("style", []):
            counts["styles"][key][w] += 1
        for key, _ in assigned.get("topic", []):
            counts["topics"][key][w] += 1
        if p.creator_id and creators.get(p.creator_id):
            counts["creators"][creators[p.creator_id]][w] += 1
        if p.prompt and (not p.assertions or provenance.is_high_confidence(p.assertions, "prompt")):
            for phrase in set(kstats.extract_phrases(p.prompt)):
                counts["terms"][phrase][w] += 1
        fmt = kstats.aspect_bucket(p.media_width, p.media_height)
        if fmt:
            counts["formats"][f"{p.media_type}:{fmt}"][w] += 1
        if p.media_type == "video" and p.duration_s:
            d = p.duration_s
            bucket = "<5s" if d < 5 else "5-10s" if d < 10 else "10-30s" if d < 30 else "30s+"
            counts["formats"][f"video:{bucket}"][w] += 1

    series: dict[str, dict[str, list[int]]] = {}
    rising: list[dict] = []
    recent, prior = labels[-2:], labels[:-2]
    for kind, table in counts.items():
        totals = {key: sum(c.values()) for key, c in table.items()}
        keys = [k for k, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:top]]
        series[kind] = {k: [table[k].get(w, 0) for w in labels] for k in keys}
        for key, c in table.items():
            r = sum(c.get(w, 0) for w in recent)
            pr = sum(c.get(w, 0) for w in prior)
            if r >= 3 and prior:
                base = pr / max(1, len(prior)) * len(recent)
                ratio = (r + 1) / (base + 1)
                if ratio >= 1.5:
                    rising.append({"kind": kind, "key": key, "recent": r, "prior_avg": round(base, 1),
                                   "ratio": round(ratio, 2)})
    rising.sort(key=lambda r: (-r["ratio"], -r["recent"]))
    return {"weeks": labels, "series": series, "rising": rising[:15],
            "posts_considered": len(posts), "computed_at": now.isoformat()}


def overview(s) -> dict:
    total = s.execute(select(func.count()).select_from(Post)).scalar_one()
    by_platform = dict(s.execute(select(Post.platform, func.count()).group_by(Post.platform)).all())
    by_ai = dict(s.execute(select(Post.ai_status, func.count()).group_by(Post.ai_status)).all())
    by_state = dict(s.execute(select(Post.pipeline_state, func.count()).group_by(Post.pipeline_state)).all())
    with_prompt = s.execute(select(func.count()).select_from(Post).where(Post.prompt.is_not(None), Post.prompt != "")).scalar_one()
    with_meta = s.execute(select(func.count()).select_from(Post).where(Post.params.like('%"metadata_format"%'))).scalar_one()
    with_workflow = s.execute(select(func.count()).select_from(Post).where(Post.has_workflow.is_(True))).scalar_one()
    buckets = Counter()
    for (score,) in s.execute(select(Post.inspiration_score).where(Post.inspiration_score.is_not(None))):
        buckets[min(4, int(score // 20))] += 1
    hist = [{"range": f"{i * 20}-{i * 20 + 19 if i < 4 else 100}", "count": buckets.get(i, 0)} for i in range(5)]
    pending = s.execute(select(func.count()).select_from(PipelineJob).where(
        PipelineJob.state.in_(("queued", "retryable", "processing")))).scalar_one()
    by_source = {k: v for k, v in dict(s.execute(select(Post.prompt_source, func.count()).group_by(Post.prompt_source)).all()).items()}
    model_sources = dict(s.execute(select(Post.model_source, func.count()).group_by(Post.model_source)).all())
    return {"posts": total, "by_platform": by_platform, "by_ai_status": {k or "unclassified": v for k, v in by_ai.items()},
            "by_pipeline_state": {k or "stored": v for k, v in by_state.items()},
            "with_prompt": with_prompt, "with_metadata": with_meta, "with_workflow": with_workflow,
            "prompt_sources": {k or "none": v for k, v in by_source.items()},
            "model_sources": {k or "none": v for k, v in model_sources.items()},
            "inspiration_histogram": hist, "queue_pending": pending}


SUMMARY_SYSTEM = (
    "You write a short trend brief for a self-hosted AI-art research library. You "
    "receive weekly counts computed from stored posts. Cite ONLY numbers present in "
    "the data, name the exact keys, never speculate about causes or the outside "
    "world. Five sentences maximum, plain text.")


def summarize(s, trends: dict) -> dict | None:
    """Grounded LLM summary; None when no provider / over budget."""
    from ..llm import client as llm_client
    try:
        client = llm_client.build_client(s)
        llm_client.check_budget(s, client)
    except llm_client.LLMError:
        return None
    payload = {"weeks": trends["weeks"], "series": trends["series"], "rising": trends["rising"]}
    try:
        text = llm_client.run_llm("trend-summary", SUMMARY_SYSTEM, json.dumps(payload)[:6000], max_tokens=350)
    except llm_client.LLMError:
        return None
    out = {"at": datetime.now(timezone.utc).isoformat(), "text": text.strip()[:1500],
           "grounded_in": {"weeks": trends["weeks"], "posts_considered": trends["posts_considered"]}}
    settings_store.put(s, "intel_trend_summary", out)
    return out


def last_summary(s) -> dict | None:
    return settings_store.get(s, "intel_trend_summary", None)
