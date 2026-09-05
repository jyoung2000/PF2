"""Search API: FTS5 free text + `tag:` / `model:` / `platform:` qualifiers +
all gallery filters, optionally scoped to a collection (D6)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import fts
from ..aliases import display_family, normalize_model
from ..db import get_db
from ..intel import query as adv
from ..models import Post, PostTag, Tag
from ..schemas import post_card
from .posts import apply_post_filters

router = APIRouter(prefix="/api", tags=["search"])


def parse_query(q: str) -> tuple[str, dict[str, list[str]]]:
    """Split a query into free text + the legacy qualifier dict {tag, model,
    platform}. The full syntax (has:/creator:/technique:/camera:/after:/
    before:/engagement:/inspiration:/ai:/model_source:/sort:) lives in
    intel.query (I6.1)."""
    pq = adv.parse(q)
    return pq.free_text, pq.legacy()


@router.get("/search")
def search(q: str = "", cursor: int = 0, limit: int = 40,
           platform: str | None = None, model: str | None = None,
           media_type: str | None = None, nsfw: bool = False,
           favorite: bool = False, origin: str | None = None,
           technique: str | None = None, collection_id: int | None = None,
           date_from: str | None = None, date_to: str | None = None,
           sort: str | None = None,
           db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    pq = adv.parse(q)
    free_text = pq.free_text
    sort = pq.sort or (sort if sort in adv.SORTS else None)

    # merge qualifiers into filters
    if pq.models and not model:
        model = adv.normalize_model_filter(pq.models)
    if pq.platforms and not platform:
        platform = pq.platforms[0]

    def base_stmt():
        stmt = select(Post)
        stmt = apply_post_filters(
            stmt, platform=platform, model=model, media_type=media_type,
            nsfw=nsfw, favorite=favorite, origin=origin, technique=technique,
            collection_id=collection_id, date_from=date_from, date_to=date_to)
        stmt = adv.apply_tags(stmt, pq.tags)
        return adv.apply_filters(stmt, pq)

    if free_text:
        ranked_ids = fts.search_posts(db, free_text, limit=400)
        if not ranked_ids:
            return {"items": [], "next_cursor": None, "total": 0, "ignored": pq.ignored}
        stmt = base_stmt().where(Post.id.in_(ranked_ids))
        rows = db.execute(stmt).scalars().all()
        by_id = {p.id: p for p in rows}
        ordered = adv.sort_rows([by_id[i] for i in ranked_ids if i in by_id], sort)
        page = ordered[cursor:cursor + limit]
        next_cursor = cursor + limit if cursor + limit < len(ordered) else None
        return {"items": [post_card(p) for p in page],
                "next_cursor": next_cursor, "total": len(ordered), "ignored": pq.ignored}

    if sort in ("inspiration", "engagement", "oldest"):
        # non-id ordering → offset cursor
        stmt = adv.order_for(base_stmt(), sort).offset(cursor).limit(limit + 1)
        rows = db.execute(stmt).scalars().all()
        items = rows[:limit]
        next_cursor = cursor + limit if len(rows) > limit else None
        return {"items": [post_card(p) for p in items],
                "next_cursor": next_cursor, "total": None, "ignored": pq.ignored}

    # default: plain filtered listing, id-desc cursor (cursor = last id)
    stmt = base_stmt().order_by(Post.id.desc())
    if cursor:
        stmt = stmt.where(Post.id < cursor)
    rows = db.execute(stmt.limit(limit + 1)).scalars().all()
    items = rows[:limit]
    next_cursor = items[-1].id if len(rows) > limit else None
    return {"items": [post_card(p) for p in items],
            "next_cursor": next_cursor, "total": None, "ignored": pq.ignored}


@router.get("/suggest")
def suggest(q: str = "", db: Session = Depends(get_db)):
    """Type-ahead: known model families + tags matching the prefix."""
    q = (q or "").strip().lower()
    fam_rows = db.execute(
        select(Post.model_family, func.count(Post.id))
        .where(Post.model_family.is_not(None))
        .group_by(Post.model_family)
        .order_by(func.count(Post.id).desc()).limit(50)).all()
    models = [
        {"family": fam, "label": display_family(fam), "count": count}
        for fam, count in fam_rows
        if not q or q in fam.lower() or q in display_family(fam).lower()
    ][:8]
    tag_stmt = (select(Tag.name, func.count(PostTag.post_id))
                .join(PostTag, PostTag.tag_id == Tag.id, isouter=True)
                .group_by(Tag.id).order_by(func.count(PostTag.post_id).desc())
                .limit(50))
    tags = [{"name": name, "count": cnt} for name, cnt in db.execute(tag_stmt)
            if not q or name.lower().startswith(q)][:8]
    return {"models": models, "tags": tags}
