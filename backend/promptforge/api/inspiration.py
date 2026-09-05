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
from ..intel import clusters, creators, dedupe, provenance, queue, scoring, similar, snapshots, sources, trends
from ..models import Cluster, Creator, Post
from ..schemas import post_card
from .search import search as base_search

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
