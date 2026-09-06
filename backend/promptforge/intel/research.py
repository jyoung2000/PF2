"""Inspiration research jobs (Inspiration 2.0, I13; spec §27–§33, §125–§130).

One orchestrator turns a plain-language request into stored, ranked
Inspiration:

    interpret (deterministic)  →  route to capable sources  →  crawl each
    within its budget  →  ingest through the EXISTING pipeline  →  rank
    against the query  →  store the job with per-source outcomes

Design rules that matter:
- one failing source never fails the job (§128): each source's outcome is
  recorded and the job completes as `partial` with reasons (§129/§130);
- discovery is cheap, enrichment/analysis stay on the existing queue (§167);
- no AI provider is required anywhere — an LLM can only refine ranking or
  summarise afterwards;
- results carry research provenance (§33): which job, source, strategy and
  query found them.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..db import session_scope
from ..logbus import bus
from ..models import Post, ResearchJob
from ..pipeline.ingest import ingest_batch
from ..scrapers import all_adapters, get_adapter
from . import query_intent, scoring

PRESETS: dict[str, dict] = {
    "ai_image_discovery": {"label": "AI image discovery",
                           "query": "ai image prompt", "media_type": "image"},
    "ai_video_discovery": {"label": "AI video discovery",
                           "query": "ai video prompt", "media_type": "video"},
    "prompt_discovery": {"label": "Prompt discovery",
                         "query": "full prompt", "wants_prompt": True},
    "creator_discovery": {"label": "Creator discovery",
                          "query": "ai creators", "mode": "creator"},
    "trend_discovery": {"label": "Trend discovery",
                        "query": "emerging ai video trends", "rank": "trending"},
    "workflow_discovery": {"label": "Workflow discovery",
                           "query": "comfyui workflow", "wants_workflow": True},
    "model_discovery": {"label": "Model discovery",
                        "query": "new ai model release", "rank": "trending"},
}

# how well each source tends to answer each kind of ask (§166 seeds; the
# learned yields in intel/sources.py adjust this at runtime)
SOURCE_AFFINITY: dict[str, dict[str, float]] = {
    "civitai":   {"prompt": 1.0, "workflow": 0.9, "image": 1.0, "video": 0.5, "creator": 0.6, "trend": 0.6},
    "reddit":    {"prompt": 0.9, "workflow": 0.9, "image": 0.8, "video": 0.8, "creator": 0.8, "trend": 0.9},
    "bluesky":   {"prompt": 0.6, "workflow": 0.3, "image": 0.7, "video": 0.7, "creator": 0.9, "trend": 0.8},
    "youtube":   {"prompt": 0.7, "workflow": 1.0, "image": 0.3, "video": 1.0, "creator": 0.8, "trend": 0.7},
    "x":         {"prompt": 0.6, "workflow": 0.4, "image": 0.8, "video": 0.9, "creator": 0.9, "trend": 1.0},
    "lexica":    {"prompt": 0.9, "workflow": 0.2, "image": 0.9, "video": 0.0, "creator": 0.3, "trend": 0.4},
    "tiktok":    {"prompt": 0.3, "workflow": 0.2, "image": 0.3, "video": 0.9, "creator": 0.8, "trend": 0.9},
    "instagram": {"prompt": 0.3, "workflow": 0.1, "image": 0.8, "video": 0.7, "creator": 0.8, "trend": 0.7},
    "pinterest": {"prompt": 0.4, "workflow": 0.1, "image": 0.9, "video": 0.2, "creator": 0.4, "trend": 0.5},
}


# ------------------------------------------------------------- routing -----
def route_sources(s: Session, intent: query_intent.ResearchIntent,
                  requested: list[str] | None = None) -> tuple[list[str], dict]:
    """Pick the sources most likely to answer THIS ask (§28/§165/§166).
    Returns (ordered source names, why-per-source)."""
    reasons: dict[str, dict] = {}
    chosen: list[tuple[float, str]] = []
    from . import sources as source_metrics
    for name, adapter in all_adapters().items():
        if requested and name not in requested:
            continue
        if not hasattr(adapter, "search"):
            reasons[name] = {"skipped": "this source cannot run a query"}
            continue
        try:
            configured = adapter.is_configured(s)
        except Exception:  # noqa: BLE001
            configured = False
        if not configured:
            reasons[name] = {"skipped": (adapter.needs_setup_reason(s)
                                         if hasattr(adapter, "needs_setup_reason") else None)
                             or "not configured"}
            continue
        affinity = SOURCE_AFFINITY.get(name, {})
        score = 0.5
        bits = []
        if intent.wants_workflow:
            score += affinity.get("workflow", 0.4)
            bits.append(f"workflow affinity {affinity.get('workflow', 0.4):.1f}")
        if intent.wants_prompt:
            score += affinity.get("prompt", 0.4)
            bits.append(f"prompt affinity {affinity.get('prompt', 0.4):.1f}")
        if intent.media_type:
            score += affinity.get(intent.media_type, 0.4)
            bits.append(f"{intent.media_type} affinity {affinity.get(intent.media_type, 0.4):.1f}")
        if intent.mode == "creator":
            score += affinity.get("creator", 0.4)
            bits.append("creator source")
        if intent.rank == "trending":
            score += affinity.get("trend", 0.4)
            bits.append("trend source")
        # learned yield nudges the seed affinities (§40/§166)
        try:
            report = source_metrics.source_report(s, name)
            yields = report.get("yields") or {}
            observed = float(yields.get("prompt_yield") or 0)
            if observed:
                score += min(0.5, observed)
                bits.append(f"observed prompt yield {observed:.0%}")
        except Exception:  # noqa: BLE001 — metrics are advisory only
            pass
        if adapter.tier <= 1:
            score += 0.25
            bits.append("no browser needed")
        chosen.append((score, name))
        reasons[name] = {"score": round(score, 2), "why": bits}
    chosen.sort(key=lambda x: (-x[0], x[1]))
    return [name for _s, name in chosen], reasons


# ------------------------------------------------------------ ranking ------
def query_relevance(post_like, intent: query_intent.ResearchIntent) -> tuple[float, list[str]]:
    """0–1 relevance of one result to THIS research query (§42/§124), with
    the reasons that produced it."""
    reasons: list[str] = []
    score = 0.3
    params = getattr(post_like, "params", None) or {}
    text = " ".join(str(x) for x in (
        getattr(post_like, "prompt", None),
        ((getattr(post_like, "observed", None) or {}).get("text") or {}).get("title"),
        ((getattr(post_like, "observed", None) or {}).get("text") or {}).get("body")) if x).lower()

    if intent.wants_prompt:
        source = str(params.get("prompt_source", ""))
        if source.startswith(("explicit", "embedded", "structured")):
            score += 0.35
            reasons.append("carries a published prompt")
        elif getattr(post_like, "prompt", None):
            score += 0.1
            reasons.append("prompt-shaped text only")
    if intent.wants_workflow and (params.get("workflow") or "workflow" in text):
        score += 0.2
        reasons.append("mentions a workflow")
    if intent.models:
        model = (getattr(post_like, "model_name", None) or "").lower()
        if any(m.lower() in model or m.lower() in text for m in intent.models):
            score += 0.25
            reasons.append(f"matches {intent.models[0]}")
    if intent.techniques:
        tags = set(params.get("technique_tags") or
                   (params.get("prompt_components") or {}).get("techniques") or [])
        hit = [t for t in intent.techniques if t in tags or t.replace("-", " ") in text]
        if hit:
            score += 0.2
            reasons.append("technique match: " + ", ".join(hit[:2]))
    if intent.media_type:
        if getattr(post_like, "media_type", None) == intent.media_type:
            score += 0.15
            reasons.append(f"is {intent.media_type}")
        elif intent.media_type == "video" and (params.get("youtube_video_id")
                                               or "video" in text):
            score += 0.08
            reasons.append("video-related")
    hits = [k for k in intent.keywords if k in text]
    if hits:
        score += min(0.2, 0.06 * len(hits))
        reasons.append("mentions " + ", ".join(hits[:3]))
    return min(1.0, round(score, 3)), reasons


def rank_results(rows: list[dict], intent: query_intent.ResearchIntent) -> list[dict]:
    """Final ordering by the requested mode (§171–§175)."""
    def engagement(r):
        return r.get("engagement") or 0

    def inspiration(r):
        return r.get("inspiration_score") or 0

    if intent.rank == "latest":
        rows.sort(key=lambda r: (r.get("posted_at") or ""), reverse=True)
    elif intent.rank == "trending":
        rows.sort(key=lambda r: (engagement(r) * (r.get("relevance") or 0)), reverse=True)
    elif intent.rank == "best":
        rows.sort(key=lambda r: (inspiration(r) * 0.6 + (r.get("relevance") or 0) * 40),
                  reverse=True)
    elif intent.rank == "hidden_gems":
        # strong evidence + real relevance, but NOT already popular (§63/§174)
        rows.sort(key=lambda r: ((r.get("relevance") or 0) * 60
                                 + inspiration(r) * 0.4
                                 - min(30, engagement(r) / 200)), reverse=True)
    else:
        rows.sort(key=lambda r: ((r.get("relevance") or 0) * 70 + inspiration(r) * 0.3),
                  reverse=True)
    return rows


# --------------------------------------------------------------- the job ---
def create_job(s: Session, query: str, *, sources: list[str] | None = None,
               preset: str | None = None, limit: int | None = None,
               per_source: int | None = None, label: str | None = None,
               extra: dict | None = None) -> ResearchJob:
    if preset and preset in PRESETS:
        query = query or PRESETS[preset]["query"]
    intent = query_intent.interpret(query)
    for key, value in (PRESETS.get(preset or "", {}) or {}).items():
        if key in ("media_type", "rank", "mode") and value:
            setattr(intent, key, value)
        if key == "wants_prompt" and value:
            intent.wants_prompt = True
        if key == "wants_workflow" and value:
            intent.wants_workflow = True
    limit = int(limit or settings_store.get(s, "research_default_limit") or 120)
    per_source = int(per_source or settings_store.get(s, "research_per_source_limit") or 60)
    routed, why = route_sources(s, intent, sources)
    job = ResearchJob(
        query=query, label=label or (PRESETS.get(preset or "", {}).get("label")),
        params={"intent": intent.as_dict(), "preset": preset, "limit": limit,
                "per_source": per_source, "routing": why,
                "terms": query_intent.search_terms(intent), **(extra or {})},
        sources=routed,
        progress={name: {"state": "queued"} for name in routed},
        status="queued")
    s.add(job)
    s.flush()
    bus.info("research", f"job {job.id}: “{query}” → {', '.join(routed) or 'no source'}")
    return job


def _set(job_id: int, **fields) -> None:
    with session_scope() as s:
        job = s.get(ResearchJob, job_id)
        if job is None:
            return
        for k, v in fields.items():
            setattr(job, k, v)
        s.flush()


def _progress(job_id: int, source: str, **fields) -> None:
    with session_scope() as s:
        job = s.get(ResearchJob, job_id)
        if job is None:
            return
        progress = dict(job.progress or {})
        progress[source] = {**progress.get(source, {}), **fields}
        job.progress = progress
        s.flush()


def run_job(job_id: int) -> dict:
    """Execute one research job. Never raises: every failure lands on the
    job (or its per-source progress) so the UI can explain it (§130)."""
    with session_scope() as s:
        job = s.get(ResearchJob, job_id)
        if job is None:
            return {"error": "no such job"}
        if job.status == "cancelled":
            return {"status": "cancelled"}
        params = dict(job.params or {})
        sources = list(job.sources or [])
        query = job.query
        cursors = dict(job.cursor_state or {})
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        s.flush()
    intent = query_intent.ResearchIntent(**{
        k: v for k, v in (params.get("intent") or {}).items()
        if k in query_intent.ResearchIntent.__dataclass_fields__})
    terms = params.get("terms") or query_intent.search_terms(intent)
    per_source = int(params.get("per_source") or 60)
    limit = int(params.get("limit") or 120)

    collected: list[tuple[str, object]] = []
    failures = 0
    for name in sources:
        adapter = get_adapter(name)
        if adapter is None:
            _progress(job_id, name, state="failed", error="adapter missing")
            failures += 1
            continue
        with session_scope() as s:
            if s.get(ResearchJob, job_id).status in ("cancelled", "paused"):
                return {"status": "stopped"}
        _progress(job_id, name, state="running")
        client = None
        found = 0
        try:
            with session_scope() as s:
                client = adapter.make_client(s)
                for term in terms:
                    if found >= per_source:
                        break
                    kwargs = {"limit": min(per_source - found, per_source)}
                    posts = adapter.search(s, client, term, **kwargs)
                    for sp in posts:
                        collected.append((name, sp))
                    found += len(posts)
            _progress(job_id, name, state="ok", found=found, terms=terms)
        except Exception as e:  # noqa: BLE001 — isolation is the point (§128)
            failures += 1
            _progress(job_id, name, state="failed",
                      error=f"{type(e).__name__}: {e}"[:300], found=found)
            bus.warn("research", f"job {job_id}: {name} failed — {e}")
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass

    # ingest through the EXISTING pipeline, per source, with provenance
    ingested: dict[str, int] = {}
    by_source: dict[str, list] = {}
    for name, sp in collected:
        params_ = sp.params if isinstance(sp.params, dict) else {}
        params_["research"] = {"job_id": job_id, "query": query,
                               "source": name, "strategy": "search",
                               "found_at": datetime.now(timezone.utc).isoformat()}
        sp.params = params_
        by_source.setdefault(name, []).append(sp)
    for name, posts in by_source.items():
        adapter = get_adapter(name)
        client = None
        try:
            with session_scope() as s:
                client = adapter.make_client(s)
            stats = ingest_batch(name, posts, client, gate=True)
            ingested[name] = stats.new
            _progress(job_id, name, ingested=stats.new, duplicates=stats.duplicates,
                      filtered=getattr(stats, "filtered", 0))
        except Exception as e:  # noqa: BLE001
            _progress(job_id, name, state="failed", error=f"ingest: {e}"[:300])
            failures += 1
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass

    rows = _collect_results(job_id, intent, [sp for _n, sp in collected], limit)
    status = ("completed" if failures == 0 and collected else
              "partial" if collected else "failed")
    with session_scope() as s:
        job = s.get(ResearchJob, job_id)
        if job is None:
            return {"error": "job vanished"}
        job.status = status
        job.finished_at = datetime.now(timezone.utc)
        job.result_post_ids = [r["post_id"] for r in rows if r.get("post_id")][:200]
        job.stats = {"candidates": len(collected), "ingested": sum(ingested.values()),
                     "per_source": ingested, "failures": failures,
                     "ranked": len(rows), "terms": terms}
        job.cursor_state = {**cursors,
                            "last_run": datetime.now(timezone.utc).isoformat(),
                            "seen_ids": [r.get("platform_post_id") for r in rows][:400]}
        if status == "failed":
            job.error = "No source returned results — see per-source errors."
        out = job_dict(s, job)
    bus.info("research", f"job {job_id}: {status} — {len(collected)} candidates, "
                         f"{sum(ingested.values())} stored")
    return out


def _collect_results(job_id: int, intent, scraped: list, limit: int) -> list[dict]:
    """Rank what the job found, preferring the STORED post (it has scores and
    dedupe applied) and falling back to the scraped record."""
    rows: list[dict] = []
    with session_scope() as s:
        for sp in scraped:
            post = s.execute(select(Post).where(
                Post.platform == sp.platform,
                Post.platform_post_id == str(sp.platform_post_id))).scalar_one_or_none()
            target = post or sp
            relevance, why = query_relevance(target, intent)
            engagement = scoring.engagement_total(
                ((getattr(target, "observed", None) or {}).get("engagement"))
                or (getattr(target, "params", None) or {}).get("engagement") or {}) or 0
            rows.append({
                "post_id": getattr(post, "id", None),
                "platform": sp.platform,
                "platform_post_id": str(sp.platform_post_id),
                "title": ((sp.observed or {}).get("text") or {}).get("title"),
                "author": sp.author, "source_url": sp.source_url,
                "media_type": sp.media_type,
                "prompt_source": (sp.params or {}).get("prompt_source"),
                "has_prompt": bool(sp.prompt),
                "model": sp.model_name,
                "engagement": engagement,
                "inspiration_score": getattr(post, "inspiration_score", None),
                "posted_at": sp.posted_at.isoformat() if sp.posted_at else None,
                "relevance": relevance, "why": why,
                "stored": post is not None,
            })
    return rank_results(rows, intent)[:limit]


def job_dict(s: Session, job: ResearchJob) -> dict:
    return {"id": job.id, "query": job.query, "label": job.label,
            "status": job.status, "sources": job.sources or [],
            "params": job.params or {}, "progress": job.progress or {},
            "stats": job.stats or {}, "error": job.error,
            "result_post_ids": job.result_post_ids or [],
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None}


def start_async(job_id: int) -> None:
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()


def list_jobs(s: Session, limit: int = 25) -> list[dict]:
    rows = s.execute(select(ResearchJob).order_by(ResearchJob.id.desc())
                     .limit(max(1, min(100, limit)))).scalars()
    return [job_dict(s, j) for j in rows]


def rerun(s: Session, job: ResearchJob, *, refresh: bool = True) -> ResearchJob:
    """Run the same research again (§125/§126): a refresh keeps the cursors
    so mostly-new material comes back."""
    params = dict(job.params or {})
    new = ResearchJob(query=job.query, label=job.label, params=params,
                      sources=list(job.sources or []),
                      progress={n: {"state": "queued"} for n in (job.sources or [])},
                      cursor_state=dict(job.cursor_state or {}) if refresh else {},
                      status="queued")
    s.add(new)
    s.flush()
    return new
