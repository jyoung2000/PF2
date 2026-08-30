"""Search API: FTS5 free text + `tag:` / `model:` / `platform:` qualifiers +
all gallery filters, optionally scoped to a collection (D6)."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import fts
from ..aliases import display_family, normalize_model
from ..db import get_db
from ..models import Post, PostTag, Tag
from ..schemas import post_card
from .posts import apply_post_filters

router = APIRouter(prefix="/api", tags=["search"])

_QUALIFIER_RE = re.compile(r'\b(tag|model|platform):("([^"]*)"|(\S+))', re.I)


def parse_query(q: str) -> tuple[str, dict[str, list[str]]]:
    """Split a query into free text + qualifiers {tag: [...], model: [...], platform: [...]}"""
    quals: dict[str, list[str]] = {"tag": [], "model": [], "platform": []}

    def _collect(m: re.Match) -> str:
        key = m.group(1).lower()
        value = m.group(3) if m.group(3) is not None else m.group(4)
        if value:
            quals[key].append(value)
        return " "

    free = _QUALIFIER_RE.sub(_collect, q or "").strip()
    return free, quals


@router.get("/search")
def search(q: str = "", cursor: int = 0, limit: int = 40,
           platform: str | None = None, model: str | None = None,
           media_type: str | None = None, nsfw: bool = False,
           favorite: bool = False, origin: str | None = None,
           technique: str | None = None, collection_id: int | None = None,
           date_from: str | None = None, date_to: str | None = None,
           db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    free_text, quals = parse_query(q)

    # merge qualifiers into filters
    if quals["model"] and not model:
        model = normalize_model(quals["model"][0]) or quals["model"][0]
    if quals["platform"] and not platform:
        platform = quals["platform"][0].lower()

    def base_stmt():
        stmt = select(Post)
        stmt = apply_post_filters(
            stmt, platform=platform, model=model, media_type=media_type,
            nsfw=nsfw, favorite=favorite, origin=origin, technique=technique,
            collection_id=collection_id, date_from=date_from, date_to=date_to)
        for tag_name in quals["tag"]:
            stmt = stmt.where(Post.id.in_(
                select(PostTag.post_id).join(Tag, Tag.id == PostTag.tag_id)
                .where(func.lower(Tag.name) == tag_name.lower())))
        return stmt

    if free_text:
        ranked_ids = fts.search_posts(db, free_text, limit=400)
        if not ranked_ids:
            return {"items": [], "next_cursor": None, "total": 0}
        stmt = base_stmt().where(Post.id.in_(ranked_ids))
        rows = db.execute(stmt).scalars().all()
        by_id = {p.id: p for p in rows}
        ordered = [by_id[i] for i in ranked_ids if i in by_id]
        page = ordered[cursor:cursor + limit]
        next_cursor = cursor + limit if cursor + limit < len(ordered) else None
        return {"items": [post_card(p) for p in page],
                "next_cursor": next_cursor, "total": len(ordered)}

    # no free text: plain filtered listing, id-desc cursor (cursor = last id)
    stmt = base_stmt().order_by(Post.id.desc())
    if cursor:
        stmt = stmt.where(Post.id < cursor)
    rows = db.execute(stmt.limit(limit + 1)).scalars().all()
    items = rows[:limit]
    next_cursor = items[-1].id if len(rows) > limit else None
    return {"items": [post_card(p) for p in items],
            "next_cursor": next_cursor, "total": None}


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
