"""Inspiration Intelligence API (I5/I6) — one router, existing conventions:
creators, sources, queue, snapshots; search / clusters / similar / analytics
join in I6. Secrets never leave the server."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..intel import (clusters, creator_links, creators, dedupe, prompt_parser,
                     provenance, queue, scoring, signals, similar, snapshots, sources,
                     trends)
from ..models import Cluster, Creator, Post
from ..schemas import post_card
from .search import search as base_search

# Human labels for the prompt-source ladder (§20) — the GUI shows these, so a
# reconstructed or model-written prompt can never pass for the creator's words.
PROMPT_SOURCE_LABELS = {
    "embedded_metadata": "Embedded generation metadata",
    "structured_api": "The platform's own prompt field",
    "explicit_workflow": "An attached workflow",
    "explicit_caption": "Published in the post",
    "explicit_thread": "Published in the creator's own reply",
    "explicit_comment": "Quoted in a comment",
    "assembled": "Reconstructed from published fragments",
    "deterministic_inference": "Inferred from the post text (rules only)",
    "ai_extraction": "Quoted by an AI reading the page",
    "ai_inference": "Guessed by an AI — not the creator's words",
    "unknown": "Unknown",
    # rows written before I11 carry the coarse provenance rank
    "observed": "The platform's own prompt field",
    "metadata": "Embedded generation metadata",
    "extracted": "Mined from the post text",
    "ai": "Written by an AI — not the creator's words",
}

router = APIRouter(prefix="/api/inspiration", tags=["inspiration"])


# ------------------------------------------------------------------ search --
@router.get("/search")
def search(q: str = "", cursor: int = 0, limit: int = 40, sort: str | None = None,
           platform: str | None = None, model: str | None = None, media_type: str | None = None,
           nsfw: bool = False, favorite: bool = False, technique: str | None = None,
           collection_id: int | None = None, db: Session = Depends(get_db)):
    """The full advanced syntax (has:/creator:/technique:/camera:/after:/before:/
    engagement:/inspiration:/ai:/model_source:/sort:) through the existing
    search engine."""
    return base_search(q=q, cursor=cursor, limit=limit, platform=platform, model=model,
                       media_type=media_type, nsfw=nsfw, favorite=favorite, origin=None,
                       technique=technique, collection_id=collection_id, date_from=None,
                       date_to=None, sort=sort, db=db)


# ------------------------------------------------------------ post intel ----
def _cards(db: Session, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    posts = {p.id: p for p in db.execute(select(Post).where(Post.id.in_(ids))).scalars()}
    return [post_card(posts[i]) for i in ids if i in posts]


@router.get("/posts/{post_id}/intel")
def post_intel(post_id: int, db: Session = Depends(get_db)):
    """Everything the detail view needs: why it's inspiring (score
    breakdowns), detected fields, evidence/provenance, enrichment, links,
    clusters, creator."""
    p = db.get(Post, post_id)
    if p is None:
        raise HTTPException(404, "No such post")
    analysis = p.analysis or {}
    creator = db.get(Creator, p.creator_id) if p.creator_id else None
    return {
        "id": p.id,
        "scores": {"inspiration": p.inspiration_score, "candidate": p.candidate_score,
                   "inspiration_breakdown": scoring.explain(analysis.get("inspiration") or {}),
                   "candidate_breakdown": scoring.explain(analysis.get("candidate") or {})},
        "ai": analysis.get("ai") or {"status": p.ai_status, "confidence": p.ai_confidence},
        "detected": {
            "model": {"name": p.model_name, "family": p.model_family, "version": p.model_version,
                      "source": p.model_source},
            "techniques": p.technique_tags or [],
            "camera": provenance.canonical(p.assertions, "camera"),
            "lighting": provenance.canonical(p.assertions, "lighting"),
            "composition": provenance.canonical(p.assertions, "composition"),
            "descriptors": analysis.get("descriptors") or {},
        },
        "generation": {k: v for k, v in (p.params or {}).items() if not k.startswith("_")},
        "raw_metadata_keys": sorted((p.params or {}).get("_raw_metadata", {}).keys()),
        "evidence": provenance.evidence_list(p.assertions),
        "alternates": (p.assertions or {}).get("_alternates", {}),
        "prompt_source": p.prompt_source,
        # I11: the UI shows WHERE the prompt came from and what it was built
        # from — an assembled or inferred prompt must never read as the
        # creator's own words (§21/§121).
        "prompt_provenance": {
            "source": p.prompt_source,
            "rank": prompt_parser.coarse_source(p.prompt_source),
            "label": PROMPT_SOURCE_LABELS.get(p.prompt_source or "", "Unknown"),
            "kind": ("observed" if prompt_parser.is_explicit_source(p.prompt_source)
                     else "reconstructed" if p.prompt_source == "assembled"
                     else "inferred" if p.prompt_source else None),
            "explicit": prompt_parser.is_explicit_source(p.prompt_source),
            "ai_written": prompt_parser.is_ai_source(p.prompt_source),
            "confidence": ((p.assertions or {}).get("prompt") or {}).get("confidence"),
            "evidence": ((p.assertions or {}).get("prompt") or {}).get("evidence"),
            "fragments": (p.params or {}).get("prompt_fragments") or [],
            "notes": (p.params or {}).get("prompt_notes") or [],
        },
        "observed": p.observed or {},
        "enrichment": p.enrichment or {},
        "links": dedupe.links_for(db, p.id),
        "clusters": clusters.clusters_for_post(db, p.id),
        "pipeline_state": p.pipeline_state,
        "creator": creators.creator_dict(db, creator) if creator else None,
    }


# ------------------------------------------------------------- enrichment --
@router.get("/enrichment/{post_id}")
def get_enrichment(post_id: int, db: Session = Depends(get_db)):
    p = db.get(Post, post_id)
    if p is None:
        raise HTTPException(404, "No such post")
    return {"post_id": p.id, "pipeline_state": p.pipeline_state, "enrichment": p.enrichment or {},
            "evidence": provenance.evidence_list(p.assertions)}


@router.post("/enrichment/{post_id}/run")
def run_enrichment(post_id: int, stage: str = "enrich", db: Session = Depends(get_db)):
    if db.get(Post, post_id) is None:
        raise HTTPException(404, "No such post")
    if stage not in queue.STAGES:
        raise HTTPException(422, f"stage must be one of {queue.STAGES}")
    job = queue.enqueue(db, post_id, stage, priority=999)
    return {"job_id": job.id, "stage": job.stage, "state": job.state}


# -------------------------------------------------------------- similar ----
@router.get("/similar/{post_id}")
def get_similar(post_id: int, mode: str = "all", limit: int = 24, db: Session = Depends(get_db)):
    p = db.get(Post, post_id)
    if p is None:
        raise HTTPException(404, "No such post")
    limit = max(1, min(limit, 100))
    if mode == "visual":
        rows = similar.visual(db, p, limit)
    elif mode == "prompt":
        rows = similar.prompt_similar(db, p, limit)
    elif mode == "technique":
        rows = similar.technique_related(db, p, limit)
    else:
        rel = similar.related(db, p, limit)
        return {"mode": "all", **{k: {"rows": v, "items": _cards(db, [r["post_id"] for r in v])}
                                  for k, v in rel.items() if k != "links"}, "links": rel["links"]}
    return {"mode": mode, "rows": rows, "items": _cards(db, [r["post_id"] for r in rows])}


@router.get("/best")
def best_examples(model: str, limit: int = 24, db: Session = Depends(get_db)):
    ids = similar.best_for_model(db, model.lower(), max(1, min(limit, 100)))
    return {"model": model.lower(), "items": _cards(db, ids)}


# -------------------------------------------------------------- clusters ---
@router.get("/clusters")
def list_clusters(kind: str | None = None, db: Session = Depends(get_db)):
    return {"clusters": clusters.list_clusters(db, kind)}


@router.get("/clusters/{cluster_id}")
def get_cluster(cluster_id: int, order: str = "score", cursor: int = 0, limit: int = 40,
                db: Session = Depends(get_db)):
    c = db.get(Cluster, cluster_id)
    if c is None:
        raise HTTPException(404, "No such cluster")
    limit = max(1, min(limit, 100))
    ids = clusters.cluster_post_ids(db, c.id, order, limit + 1, cursor)
    items = _cards(db, ids[:limit])
    data = c.data or {}
    return {**clusters.cluster_dict(c), "items": items,
            "next_cursor": cursor + limit if len(ids) > limit else None,
            "top_posts": _cards(db, data.get("top_post_ids", [])[:8]),
            "newest_posts": _cards(db, data.get("newest_post_ids", [])[:8])}


@router.post("/clusters/rebuild")
def rebuild_clusters(db: Session = Depends(get_db)):
    return clusters.rebuild(db)


# ------------------------------------------------------------- analytics ---
@router.get("/analytics")
def analytics(db: Session = Depends(get_db)):
    return {**trends.overview(db), "sources": sources.all_reports(db), "queue": queue.stats(db),
            "summary": trends.last_summary(db)}


@router.get("/analytics/trends")
def analytics_trends(weeks: int = 12, db: Session = Depends(get_db)):
    return trends.weekly_series(db, max(2, min(weeks, 52)))


# --------------------------------------- cross-source signals (I14) --------
@router.get("/analytics/signals")
def analytics_signals(weeks: int = 8, limit: int = 25, db: Session = Depends(get_db)):
    """Signals ranked by how widely they travel across platforms, with
    velocity. No AI provider is involved."""
    return signals.cross_platform_signals(db, weeks=max(2, min(weeks, 52)),
                                          limit=max(1, min(100, limit)))


@router.get("/analytics/patterns")
def analytics_patterns(weeks: int = 12, limit: int = 30, db: Session = Depends(get_db)):
    """Phrase sets that keep travelling together in PUBLISHED prompts."""
    return signals.prompt_patterns(db, weeks=max(2, min(weeks, 52)),
                                   limit=max(1, min(100, limit)))


@router.get("/analytics/growth")
def analytics_growth(limit: int = 25, db: Session = Depends(get_db)):
    """Posts still gaining, straight from repeat observations."""
    return signals.engagement_growth(db, limit=max(1, min(100, limit)))


@router.get("/analytics/signals/summary")
def analytics_signal_summary(weeks: int = 8, db: Session = Depends(get_db)):
    return signals.summary(db, weeks=max(2, min(weeks, 52)))


@router.get("/discover")
def discover(mode: str = "trending", limit: int = 40, platform: str | None = None,
             media_type: str | None = None, q: str | None = None,
             db: Session = Depends(get_db)):
    """Discovery shelves — every result says why it is there (§46). With `q`,
    relevance to that question outranks the shelf's own signal (§42)."""
    out = signals.discover(db, mode=mode, limit=max(1, min(200, limit)),
                           platform=platform, media_type=media_type, query=q)
    ids = [r["post_id"] for r in out["results"]]
    posts = {p.id: p for p in db.execute(select(Post).where(Post.id.in_(ids))).scalars()} if ids else {}
    out["items"] = [{**post_card(posts[r["post_id"]]), "why": r["why"],
                     "rank_score": r["score"], "relevance": r.get("relevance")}
                    for r in out["results"] if r["post_id"] in posts]
    return out


@router.post("/analytics/summary")
def analytics_summary(weeks: int = 12, db: Session = Depends(get_db)):
    data = trends.weekly_series(db, max(2, min(weeks, 52)))
    out = trends.summarize(db, data)
    if out is None:
        raise HTTPException(409, {"code": "llm_not_available",
                                  "message": "No AI provider configured (or the daily budget is spent) — "
                                             "the deterministic trends above stay available."})
    return out


# ---------------------------------------------------------------- creators --
@router.get("/creators")
def list_creators(platform: str | None = None, sort: str = "posts", q: str | None = None,
                  limit: int = 60, db: Session = Depends(get_db)):
    return {"creators": creators.list_creators(db, platform, sort, min(200, max(1, limit)), q)}


@router.get("/creators/{creator_id}")
def get_creator(creator_id: int, db: Session = Depends(get_db)):
    c = db.get(Creator, creator_id)
    if c is None:
        raise HTTPException(404, "No such creator")
    data = creators.creator_dict(db, c)
    st = data["stats"]
    ids = list(dict.fromkeys((st.get("top_post_ids") or []) + (st.get("recent_post_ids") or [])))
    posts = {p.id: p for p in db.execute(select(Post).where(Post.id.in_(ids))).scalars()} if ids else {}
    data["top_posts"] = [post_card(posts[i]) for i in st.get("top_post_ids", []) if i in posts]
    data["recent_posts"] = [post_card(posts[i]) for i in st.get("recent_post_ids", []) if i in posts]
    return data


@router.post("/creators/{creator_id}/refresh")
def refresh_creator(creator_id: int, db: Session = Depends(get_db)):
    c = db.get(Creator, creator_id)
    if c is None:
        raise HTTPException(404, "No such creator")
    return creators.creator_dict(db, c, force=True)


# ----------------------------------------------------------------- sources --
@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    return {"sources": sources.all_reports(db)}


# ------------------------------------------------------------------- queue --
@router.get("/queue")
def queue_stats(db: Session = Depends(get_db)):
    return queue.stats(db)


class QueueIds(BaseModel):
    ids: list[int] | None = None


@router.post("/queue/retry")
def queue_retry(body: QueueIds | None = None, db: Session = Depends(get_db)):
    return {"retried": queue.retry(db, body.ids if body else None)}


@router.post("/queue/clear")
def queue_clear(db: Session = Depends(get_db)):
    return {"cleared": queue.clear(db)}


@router.post("/queue/tick")
def queue_tick(max_jobs: int = 10):
    """Process pending jobs now (background thread; the scheduler does this
    every minute anyway)."""
    threading.Thread(target=queue.tick, args=(max(1, min(100, max_jobs)),), daemon=True).start()
    return {"started": True}


# --------------------------------------------------------------- snapshots --
@router.get("/snapshots")
def list_snapshots(platform: str | None = None):
    return {"snapshots": snapshots.list_snapshots(platform)}


@router.get("/snapshots/{platform}/{file}")
def get_snapshot(platform: str, file: str):
    data = snapshots.load_snapshot(platform, file)
    if data is None:
        raise HTTPException(404, "No such snapshot")
    return data


# ------------------------------------------- discovery (Grok-free, I10) -----
class DiscoverBody(BaseModel):
    query: str
    sources: list[str] | None = None
    limit: int = 20
    per_source: int = 40


@router.get("/discovery/status")
def discovery_status(db: Session = Depends(get_db)):
    """What creator/source discovery can do right now — and proof that it
    does not need Grok (§29)."""
    from ..intel import discovery
    return discovery.discovery_status(db)


@router.post("/creators/discover")
def discover_creators(body: DiscoverBody, db: Session = Depends(get_db)):
    """Find creators worth following by searching PF2's own sources. No AI
    provider is used; nothing is followed automatically (§30)."""
    from ..intel import discovery
    if not body.query.strip():
        raise HTTPException(422, "A query is required.")
    return discovery.discover_creators(
        db, body.query.strip(), sources=body.sources,
        limit=max(1, min(100, body.limit)),
        per_source=max(1, min(100, body.per_source)))


@router.get("/creators/{creator_id}/similar")
def creator_similar(creator_id: int, limit: int = 12, db: Session = Depends(get_db)):
    from ..intel import discovery
    if db.get(Creator, creator_id) is None:
        raise HTTPException(404, "No such creator")
    return discovery.similar_creators(db, creator_id, max(1, min(50, limit)))


# ------------------------------------ cross-source creator identity (I12) ---
class LinkBody(BaseModel):
    creator_a: int
    creator_b: int
    kind: str = "user"
    detail: str | None = None


@router.get("/creators/{creator_id}/identity")
def creator_identity(creator_id: int, db: Session = Depends(get_db)):
    """Every platform identity linked to this one — shown together, stored
    apart. Nothing here merges rows or moves posts."""
    if db.get(Creator, creator_id) is None:
        raise HTTPException(404, "No such creator")
    return creator_links.identity(db, creator_id)


@router.get("/creators/links/suggestions")
def link_suggestions(creator_id: int | None = None, limit: int = 50,
                     db: Session = Depends(get_db)):
    """Evidence-backed candidates only. A shared name is never evidence."""
    return {"suggestions": creator_links.suggest_links(db, creator_id,
                                                       max(1, min(200, limit))),
            "evidence_kinds": list(creator_links.EVIDENCE_CONFIDENCE),
            "note": "Two handles spelled the same are two strangers until "
                    "something observable ties them together."}


@router.post("/creators/links")
def create_link(body: LinkBody, db: Session = Depends(get_db)):
    row = creator_links.record_link(
        db, body.creator_a, body.creator_b, body.kind, body.detail,
        created_by="user" if body.kind == "user" else "system")
    if row is None:
        raise HTTPException(422, f"Cannot link those creators with evidence kind "
                                 f"'{body.kind}' (known kinds: "
                                 f"{', '.join(creator_links.EVIDENCE_CONFIDENCE)}).")
    return {"link_id": row.id, "confidence": row.confidence, "evidence": row.evidence}


@router.delete("/creators/links/{link_id}")
def delete_link(link_id: int, db: Session = Depends(get_db)):
    if not creator_links.unlink(db, link_id):
        raise HTTPException(404, "No such link")
    return {"ok": True}


@router.post("/creators/links/scan")
def scan_links(db: Session = Depends(get_db)):
    return creator_links.scan(db)


# ------------------------------------------------ browser intelligence ------
@router.get("/browser")
def browser_status(db: Session = Depends(get_db)):
    """Engine availability + today's AI/browser budget use + workflow health."""
    from .. import browserintel as bi
    from ..browserintel import diagnostics, workflows as wf_store
    return {**bi.availability(),
            "usage": bi.get_usage(db),
            "workflows": [wf_store.workflow_dict(w) for w in wf_store.list_workflows(db)],
            "diagnostics": diagnostics.list_diagnostics(limit=10)}


@router.post("/workflows/{workflow_id}/repair")
def repair_workflow(workflow_id: int, db: Session = Depends(get_db)):
    from .. import browserintel as bi
    from ..models import BrowserWorkflow
    wf = db.get(BrowserWorkflow, workflow_id)
    if wf is None:
        raise HTTPException(404, "No such workflow")
    try:
        return bi.repair_workflow(wf.source, wf.task)
    except bi.BudgetExhausted as e:
        raise HTTPException(429, str(e))
    except bi.EngineUnavailable as e:
        raise HTTPException(409, {"code": "engine_unavailable", "message": str(e)})
    except bi.PolicyViolation as e:
        raise HTTPException(422, str(e))


@router.post("/workflows/{workflow_id}/disable")
def disable_workflow(workflow_id: int, db: Session = Depends(get_db)):
    from ..models import BrowserWorkflow
    wf = db.get(BrowserWorkflow, workflow_id)
    if wf is None:
        raise HTTPException(404, "No such workflow")
    wf.status = "disabled"
    db.flush()
    from ..browserintel import workflows as wf_store
    return wf_store.workflow_dict(wf)


# ---------------------------------------------------- research jobs (I13) ---
class ResearchBody(BaseModel):
    query: str = ""
    sources: list[str] | None = None
    preset: str | None = None
    limit: int | None = None
    per_source: int | None = None
    label: str | None = None
    run: bool = True          # False → create the job without running it


@router.get("/research/presets")
def research_presets():
    from ..intel import research
    return {"presets": [{"key": k, **v} for k, v in research.PRESETS.items()]}


@router.post("/research")
def start_research(body: ResearchBody, db: Session = Depends(get_db)):
    """Interpret the request, route it to the capable sources and start the
    crawl. Deterministic end to end — no AI provider needed (§29)."""
    from ..intel import research
    if not (body.query or "").strip() and not body.preset:
        raise HTTPException(422, "Give a research query (or pick a preset).")
    job = research.create_job(db, (body.query or "").strip(), sources=body.sources,
                              preset=body.preset, limit=body.limit,
                              per_source=body.per_source, label=body.label)
    out = research.job_dict(db, job)
    if not job.sources:
        out["warning"] = ("No source can answer this yet — connect one under "
                          "Inspiration → Sources (Reddit and Bluesky need no login).")
    elif body.run:
        db.commit()
        research.start_async(job.id)
    return out


@router.get("/research")
def list_research(limit: int = 25, db: Session = Depends(get_db)):
    from ..intel import research
    return {"jobs": research.list_jobs(db, limit)}


@router.get("/research/{job_id}")
def get_research(job_id: int, include_results: bool = True, db: Session = Depends(get_db)):
    from ..intel import research
    from ..models import ResearchJob
    job = db.get(ResearchJob, job_id)
    if job is None:
        raise HTTPException(404, "No such research job")
    out = research.job_dict(db, job)
    if include_results:
        out["items"] = _cards(db, (job.result_post_ids or [])[:60])
    return out


@router.post("/research/{job_id}/{action}")
def control_research(job_id: int, action: str, db: Session = Depends(get_db)):
    from ..intel import research
    from ..models import ResearchJob
    job = db.get(ResearchJob, job_id)
    if job is None:
        raise HTTPException(404, "No such research job")
    if action == "pause":
        job.status = "paused"
    elif action == "cancel":
        job.status = "cancelled"
    elif action in ("resume", "run"):
        job.status = "queued"
        db.commit()
        research.start_async(job.id)
    elif action in ("rerun", "refresh"):
        new = research.rerun(db, job, refresh=(action == "refresh"))
        db.commit()
        research.start_async(new.id)
        return research.job_dict(db, new)
    else:
        raise HTTPException(422, "action must be pause|resume|cancel|rerun|refresh")
    db.flush()
    return research.job_dict(db, job)


@router.get("/research/{job_id}/export.{fmt}")
def export_research(job_id: int, fmt: str, db: Session = Depends(get_db)):
    """JSON / CSV / Markdown export of a job's prompt records (§101)."""
    from fastapi.responses import PlainTextResponse

    from ..intel import research
    from ..models import ResearchJob
    job = db.get(ResearchJob, job_id)
    if job is None:
        raise HTTPException(404, "No such research job")
    if fmt not in ("json", "csv", "md"):
        raise HTTPException(422, "format must be json, csv or md")
    posts = db.execute(select(Post).where(
        Post.id.in_(job.result_post_ids or []))).scalars().all()
    rows = [{
        "prompt": p.prompt, "negative": p.negative_prompt,
        "model": p.model_name, "model_family": p.model_family,
        "techniques": ", ".join(p.technique_tags or []),
        "platform": p.platform, "creator": p.author, "url": p.source_url,
        "prompt_source": p.prompt_source,
        "confidence": ((p.assertions or {}).get("prompt") or {}).get("confidence"),
        "inspiration_score": p.inspiration_score,
    } for p in posts]
    if fmt == "json":
        return {"job": research.job_dict(db, job), "records": rows}
    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0]) if rows else
                           ["prompt", "model", "platform", "url"])
        w.writeheader()
        w.writerows(rows)
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")
    lines = [f"# Inspiration research — {job.query}", "",
             f"*{len(rows)} records · sources: {', '.join(job.sources or [])}*", ""]
    for r in rows:
        lines += [f"## {r['creator'] or 'unknown'} · {r['platform']}",
                  f"- **Model:** {r['model'] or '—'}",
                  f"- **Prompt source:** {r['prompt_source'] or 'unknown'}",
                  f"- **Source:** {r['url'] or '—'}", "",
                  "```", (r["prompt"] or "(no published prompt)"), "```", ""]
    return PlainTextResponse("\n".join(lines), media_type="text/markdown")
