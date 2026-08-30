"""Collections API: user collections (CRUD + model-family scoping) and
automatic model collections derived live from the alias map (3.1, 3.2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..aliases import display_family
from ..db import get_db
from ..models import Collection, CollectionPost, Post
from ..schemas import collection_summary

router = APIRouter(prefix="/api/collections", tags=["collections"])


def _counts(db: Session, collection_id: int) -> tuple[int, int, int]:
    rows = db.execute(
        select(Post.media_type, func.count(Post.id))
        .join(CollectionPost, CollectionPost.post_id == Post.id)
        .where(CollectionPost.collection_id == collection_id)
        .group_by(Post.media_type)).all()
    by = dict(rows)
    img, vid = by.get("image", 0), by.get("video", 0)
    return img + vid, img, vid


def _cover_urls(db: Session, collection_id: int, limit: int = 4) -> list[str]:
    rows = db.execute(
        select(Post.thumb_path)
        .join(CollectionPost, CollectionPost.post_id == Post.id)
        .where(CollectionPost.collection_id == collection_id,
               Post.thumb_path.is_not(None))
        .order_by(CollectionPost.added_at.desc(), Post.id.desc())
        .limit(limit)).all()
    return [f"/{r[0]}" for r in rows]


def _summary(db: Session, c: Collection) -> dict:
    total, img, vid = _counts(db, c.id)
    d = collection_summary(c, total, _cover_urls(db, c.id))
    d["image_count"] = img
    d["video_count"] = vid
    return d


def model_collections(db: Session) -> list[dict]:
    """Automatic per-model-family collections, straight from post data."""
    fams = db.execute(
        select(Post.model_family,
               func.count(Post.id),
               func.sum(func.iif(Post.media_type == "video", 1, 0)))
        .where(Post.model_family.is_not(None))
        .group_by(Post.model_family)
        .order_by(func.count(Post.id).desc())).all()
    out = []
    for family, total, videos in fams:
        videos = videos or 0
        covers = db.execute(
            select(Post.thumb_path).where(Post.model_family == family,
                                          Post.thumb_path.is_not(None))
            .order_by(Post.id.desc()).limit(4)).all()
        versions = [r[0] for r in db.execute(
            select(Post.model_name).where(Post.model_family == family,
                                          Post.model_name.is_not(None))
            .group_by(Post.model_name)
            .order_by(func.count(Post.id).desc()).limit(6))]
        out.append({
            "family": family,
            "label": display_family(family),
            "count": total,
            "image_count": total - videos,
            "video_count": videos,
            "versions": versions,
            "cover_urls": [f"/{r[0]}" for r in covers],
        })
    return out


@router.get("")
def index(db: Session = Depends(get_db)):
    user = [ _summary(db, c) for c in db.execute(
        select(Collection).order_by(Collection.created_at.desc())).scalars()]
    return {"model_collections": model_collections(db), "user_collections": user}


class CollectionCreate(BaseModel):
    name: str
    description: str | None = None


@router.post("")
def create(body: CollectionCreate, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Collection name is empty")
    exists = db.execute(select(Collection).where(
        func.lower(Collection.name) == name.lower())).first()
    if exists:
        raise HTTPException(409, f"A collection named “{name}” already exists")
    c = Collection(name=name, description=body.description)
    db.add(c)
    db.flush()
    return _summary(db, c)


@router.get("/{collection_id}")
def get_one(collection_id: int, db: Session = Depends(get_db)):
    c = db.get(Collection, collection_id)
    if c is None:
        raise HTTPException(404, "Collection not found")
    return _summary(db, c)


class CollectionPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    allow_mixed_models: bool | None = None
    cover_post_id: int | None = None


@router.patch("/{collection_id}")
def patch(collection_id: int, body: CollectionPatch, db: Session = Depends(get_db)):
    c = db.get(Collection, collection_id)
    if c is None:
        raise HTTPException(404, "Collection not found")
    if body.name is not None and body.name.strip():
        c.name = body.name.strip()
    if body.description is not None:
        c.description = body.description
    if body.allow_mixed_models is not None:
        c.allow_mixed_models = body.allow_mixed_models
    if body.cover_post_id is not None:
        c.cover_post_id = body.cover_post_id
    db.flush()
    return _summary(db, c)


@router.delete("/{collection_id}")
def remove(collection_id: int, db: Session = Depends(get_db)):
    c = db.get(Collection, collection_id)
    if c is None:
        raise HTTPException(404, "Collection not found")
    db.delete(c)  # collection_posts cascade; posts themselves stay
    db.flush()
    return {"deleted": collection_id}


@router.post("/{collection_id}/posts/{post_id}")
def save_post(collection_id: int, post_id: int, db: Session = Depends(get_db)):
    c = db.get(Collection, collection_id)
    if c is None:
        raise HTTPException(404, "Collection not found")
    p = db.get(Post, post_id)
    if p is None:
        raise HTTPException(404, "Post not found")

    # model-family scoping: the collection adopts the family of the first post;
    # cross-family saves are blocked unless allow_mixed_models
    if p.model_family:
        if c.model_family is None:
            members = db.execute(select(func.count(CollectionPost.post_id)).where(
                CollectionPost.collection_id == c.id)).scalar_one()
            if members == 0:
                c.model_family = p.model_family
        elif p.model_family != c.model_family and not c.allow_mixed_models:
            fam = display_family(c.model_family)
            raise HTTPException(
                409,
                f"This collection holds {fam} posts — save to a {fam} collection "
                f"or enable “Allow mixed models” on “{c.name}”.")

    exists = db.execute(select(CollectionPost).where(
        CollectionPost.collection_id == collection_id,
        CollectionPost.post_id == post_id)).first()
    if not exists:
        db.add(CollectionPost(collection_id=collection_id, post_id=post_id))
    if c.cover_post_id is None:
        c.cover_post_id = post_id
    db.flush()
    _refresh_style_profile(collection_id)
    return {"saved": True, "collection": _summary(db, c)}


@router.delete("/{collection_id}/posts/{post_id}")
def unsave_post(collection_id: int, post_id: int, db: Session = Depends(get_db)):
    c = db.get(Collection, collection_id)
    if c is None:
        raise HTTPException(404, "Collection not found")
    db.execute(delete(CollectionPost).where(
        CollectionPost.collection_id == collection_id,
        CollectionPost.post_id == post_id))
    if c.cover_post_id == post_id:
        nxt = db.execute(select(CollectionPost.post_id).where(
            CollectionPost.collection_id == collection_id)
            .order_by(CollectionPost.added_at.desc()).limit(1)).first()
        c.cover_post_id = nxt[0] if nxt else None
    db.flush()
    _refresh_style_profile(collection_id)
    return {"removed": True}


def _refresh_style_profile(collection_id: int) -> None:
    """Knowledge engine hook (lands in Phase 6): mark profile stale."""
    try:
        from ..knowledge import engine as kengine
        kengine.mark_collection_dirty(collection_id)
    except ImportError:
        pass
