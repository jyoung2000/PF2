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
from ..intel import creators, queue, snapshots, sources
from ..models import Creator, Post
from ..schemas import post_card

router = APIRouter(prefix="/api/inspiration", tags=["inspiration"])


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
