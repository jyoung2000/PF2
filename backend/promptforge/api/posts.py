"""Posts API: listing (cursor pagination + filters), detail, favorite, delete."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import fts
from ..config import get_config
from ..db import get_db
from ..models import Collection, CollectionPost, Post, Tag
from ..schemas import post_card, post_detail

router = APIRouter(prefix="/api/posts", tags=["posts"])


def apply_post_filters(stmt, *, platform: str | None = None, model: str | None = None,
                       media_type: str | None = None, nsfw: bool | None = None,
                       favorite: bool | None = None, origin: str | None = None,
                       technique: str | None = None, collection_id: int | None = None,
                       date_from: str | None = None, date_to: str | None = None):
    if platform:
        stmt = stmt.where(Post.platform == platform)
    if model:
        stmt = stmt.where(Post.model_family == model.lower())
    if media_type in ("image", "video"):
        stmt = stmt.where(Post.media_type == media_type)
    if nsfw is not None and not nsfw:
        stmt = stmt.where(Post.nsfw.is_(False))
    if favorite:
        stmt = stmt.where(Post.favorite.is_(True))
    if origin in ("scraped", "generated"):
        stmt = stmt.where(Post.origin == origin)
    if technique:
        # technique_tags is a JSON list stored as text in SQLite
        stmt = stmt.where(Post.technique_tags.like(f'%"{technique}"%'))
    if collection_id:
        stmt = stmt.where(Post.id.in_(
            select(CollectionPost.post_id).where(
                CollectionPost.collection_id == collection_id)))
    if date_from:
        try:
            stmt = stmt.where(Post.scraped_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            stmt = stmt.where(Post.scraped_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass
    return stmt


@router.get("")
def list_posts(cursor: int | None = None, limit: int = 40,
               platform: str | None = None, model: str | None = None,
               media_type: str | None = None, nsfw: bool = False,
               favorite: bool = False, origin: str | None = None,
               technique: str | None = None, collection_id: int | None = None,
               date_from: str | None = None, date_to: str | None = None,
               db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    stmt = select(Post).order_by(Post.id.desc())
    stmt = apply_post_filters(
        stmt, platform=platform, model=model, media_type=media_type,
        nsfw=nsfw, favorite=favorite, origin=origin, technique=technique,
        collection_id=collection_id, date_from=date_from, date_to=date_to)
    if cursor:
        stmt = stmt.where(Post.id < cursor)
    rows = db.execute(stmt.limit(limit + 1)).scalars().all()
    items = [post_card(p) for p in rows[:limit]]
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return {"items": items, "next_cursor": next_cursor}


def _load_detail(db: Session, post: Post) -> dict:
    tag_names = [t.name for t in post.tags]
    coll_rows = db.execute(
        select(Collection).join(CollectionPost,
                                CollectionPost.collection_id == Collection.id)
        .where(CollectionPost.post_id == post.id)).scalars().all()
    collections = [{"id": c.id, "name": c.name} for c in coll_rows]
    return post_detail(post, tag_names, collections)


@router.get("/{post_id}")
def get_post(post_id: int, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(404, "Post not found")
    return _load_detail(db, post)


class PostPatch(BaseModel):
    favorite: bool | None = None
    nsfw: bool | None = None


@router.patch("/{post_id}")
def patch_post(post_id: int, body: PostPatch, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(404, "Post not found")
    if body.favorite is not None:
        post.favorite = body.favorite
    if body.nsfw is not None:
        post.nsfw = body.nsfw
    db.flush()
    return _load_detail(db, post)


@router.delete("/{post_id}")
def delete_post(post_id: int, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(404, "Post not found")
    cfg = get_config()
    for rel in (post.media_path, post.thumb_path):
        if rel:
            (cfg.data_dir / rel).unlink(missing_ok=True)
    # collections whose cover was this post fall back to newest member (D45)
    fts.deindex_post(db, post_id)
    db.delete(post)
    db.flush()
    for c in db.execute(select(Collection).where(
            Collection.cover_post_id == post_id)).scalars():
        nxt = db.execute(
            select(CollectionPost.post_id)
            .where(CollectionPost.collection_id == c.id)
            .order_by(CollectionPost.post_id.desc()).limit(1)).first()
        c.cover_post_id = nxt[0] if nxt else None
    db.flush()
    return {"deleted": post_id}


@router.get("/{post_id}/tags/autocomplete")
def tag_autocomplete(post_id: int, q: str = "", db: Session = Depends(get_db)):
    stmt = select(Tag.name).order_by(Tag.name).limit(15)
    if q:
        stmt = stmt.where(Tag.name.like(f"{q}%"))
    return {"tags": [r[0] for r in db.execute(stmt)]}
