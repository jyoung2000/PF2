"""Models view (3.2): every model family ever seen, purely data-driven —
counts, versions, first/last seen, "New" badge (<14 days). Alias rules are
GUI-editable here too."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import settings_store
from ..aliases import DEFAULT_RULES, display_family
from ..db import get_db
from ..models import Post

router = APIRouter(prefix="/api/models", tags=["models"])

NEW_WINDOW_DAYS = 14


@router.get("/meta")
def models_meta(db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            Post.model_family,
            func.count(Post.id),
            func.sum(func.iif(Post.media_type == "video", 1, 0)),
            func.min(Post.scraped_at),
            func.max(Post.scraped_at),
        ).where(Post.model_family.is_not(None)).group_by(Post.model_family)).all()
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEW_WINDOW_DAYS)
    out = []
    for family, total, videos, first_seen, last_seen in rows:
        if isinstance(first_seen, str):
            first_seen = datetime.fromisoformat(first_seen)
        if isinstance(last_seen, str):
            last_seen = datetime.fromisoformat(last_seen)
        first_aware = (first_seen.replace(tzinfo=timezone.utc)
                       if first_seen and first_seen.tzinfo is None else first_seen)
        versions = [r[0] for r in db.execute(
            select(Post.model_name).where(Post.model_family == family,
                                          Post.model_name.is_not(None))
            .group_by(Post.model_name)
            .order_by(func.count(Post.id).desc()).limit(8))]
        videos = videos or 0
        out.append({
            "family": family,
            "label": display_family(family),
            "post_count": total,
            "image_count": total - videos,
            "video_count": videos,
            "versions": versions,
            "first_seen": first_seen.isoformat() if first_seen else None,
            "last_seen": last_seen.isoformat() if last_seen else None,
            "is_new": bool(first_aware and first_aware >= cutoff),
        })
    # new families first, then by volume
    out.sort(key=lambda m: (not m["is_new"], -m["post_count"]))
    return {"models": out}


@router.get("/aliases")
def get_aliases(db: Session = Depends(get_db)):
    return {
        "defaults": [{"match": m, "family": f} for m, f in DEFAULT_RULES],
        "user_rules": settings_store.get(db, "model_aliases") or {},
    }


class AliasRules(BaseModel):
    user_rules: dict[str, str]


@router.put("/aliases")
def put_aliases(body: AliasRules, db: Session = Depends(get_db)):
    clean = {k.strip(): v.strip().lower() for k, v in body.user_rules.items()
             if k.strip() and v.strip()}
    settings_store.put(db, "model_aliases", clean)
    # re-normalize existing posts so new rules apply retroactively
    from ..aliases import normalize_model
    for p in db.execute(select(Post)).scalars():
        p.model_family = normalize_model(p.model_name, clean)
    db.flush()
    return {"user_rules": clean, "renormalized": True}
