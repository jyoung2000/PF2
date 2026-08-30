"""User tag management: add/remove on posts, global autocomplete. Tag writes
reindex the post in FTS so `tag:` search and free text stay in sync."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import fts
from ..db import get_db
from ..models import Post, PostTag, Tag

router = APIRouter(prefix="/api", tags=["tags"])


def _reindex(db: Session, post: Post) -> list[str]:
    names = [t.name for t in db.execute(
        select(Tag).join(PostTag, PostTag.tag_id == Tag.id)
        .where(PostTag.post_id == post.id)).scalars()]
    fts.index_post(db, post.id, post.prompt, post.model_name, names)
    return names


class TagBody(BaseModel):
    name: str


@router.post("/posts/{post_id}/tags")
def add_tag(post_id: int, body: TagBody, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(404, "Post not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Tag name is empty")
    if len(name) > 80:
        raise HTTPException(422, "Tag name too long (80 chars max)")
    tag = db.execute(select(Tag).where(
        func.lower(Tag.name) == name.lower())).scalar_one_or_none()
    if tag is None:
        tag = Tag(name=name)
        db.add(tag)
        db.flush()
    exists = db.execute(select(PostTag).where(
        PostTag.post_id == post_id, PostTag.tag_id == tag.id)).first()
    if not exists:
        db.add(PostTag(post_id=post_id, tag_id=tag.id))
        db.flush()
    return {"tags": _reindex(db, post)}


@router.delete("/posts/{post_id}/tags/{name}")
def remove_tag(post_id: int, name: str, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(404, "Post not found")
    tag = db.execute(select(Tag).where(
        func.lower(Tag.name) == name.lower())).scalar_one_or_none()
    if tag is not None:
        db.execute(delete(PostTag).where(
            PostTag.post_id == post_id, PostTag.tag_id == tag.id))
        remaining = db.execute(select(PostTag).where(
            PostTag.tag_id == tag.id)).first()
        if remaining is None:
            db.delete(tag)  # garbage-collect unused tags
        db.flush()
    return {"tags": _reindex(db, post)}


@router.get("/tags")
def list_tags(q: str = "", db: Session = Depends(get_db)):
    stmt = (select(Tag.name, func.count(PostTag.post_id))
            .join(PostTag, PostTag.tag_id == Tag.id, isouter=True)
            .group_by(Tag.id))
    if q:
        stmt = stmt.where(Tag.name.like(f"{q}%"))
    stmt = stmt.order_by(func.count(PostTag.post_id).desc()).limit(25)
    return {"tags": [{"name": n, "count": c} for n, c in db.execute(stmt)]}
