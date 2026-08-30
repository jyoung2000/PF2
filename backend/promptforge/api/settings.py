"""Settings API (3.9): GET masked settings, PUT live updates, storage stats,
purge tool. Everything applies immediately — no restart (settings_store D23)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import fts, settings_store
from ..config import get_config
from ..db import get_db
from ..models import Post

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    return {"settings": settings_store.all_masked(db),
            "secret_keys": sorted(settings_store.SECRET_KEYS)}


@router.put("")
def put_settings(values: dict = Body(...), db: Session = Depends(get_db)):
    known = {k: v for k, v in values.items() if k in settings_store.DEFAULTS}
    settings_store.put_many(db, known)
    db.flush()
    _apply_side_effects(known)
    return {"settings": settings_store.all_masked(db), "applied": sorted(known)}


def _apply_side_effects(changed: dict) -> None:
    if any(k.startswith("discord") for k in changed):
        try:
            from ..integrations import discord_bot
            discord_bot.manager.sync_from_settings()
        except ImportError:
            pass


@router.get("/storage")
def storage_stats(db: Session = Depends(get_db)):
    cfg = get_config()
    post_count = db.execute(select(func.count(Post.id))).scalar_one()
    video_count = db.execute(select(func.count(Post.id)).where(
        Post.media_type == "video")).scalar_one()
    original = stored = 0
    for (params,) in db.execute(select(Post.params)):
        if isinstance(params, dict):
            original += params.get("_original_bytes") or 0
            stored += params.get("_stored_bytes") or 0
    disk_used = 0
    media_files = 0
    if cfg.media_dir.is_dir():
        for f in cfg.media_dir.rglob("*"):
            if f.is_file():
                disk_used += f.stat().st_size
                media_files += 1
    db_bytes = cfg.db_path.stat().st_size if cfg.db_path.exists() else 0
    return {
        "post_count": post_count,
        "image_count": post_count - video_count,
        "video_count": video_count,
        "media_files": media_files,
        "disk_used_bytes": disk_used + db_bytes,
        "db_bytes": db_bytes,
        "original_bytes": original,
        "stored_bytes": stored,
        "saved_bytes": max(0, original - stored),
        "data_dir": str(cfg.data_dir),
    }


class PurgeBody(BaseModel):
    platform: str | None = None
    older_than_days: int | None = None
    include_favorites: bool = False
    dry_run: bool = True


@router.post("/purge")
def purge(body: PurgeBody, db: Session = Depends(get_db)):
    stmt = select(Post)
    if body.platform:
        stmt = stmt.where(Post.platform == body.platform)
    if body.older_than_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=body.older_than_days)
        stmt = stmt.where(Post.scraped_at < cutoff)
    if not body.include_favorites:
        stmt = stmt.where(Post.favorite.is_(False))
    posts = db.execute(stmt).scalars().all()
    if body.dry_run:
        return {"would_delete": len(posts), "dry_run": True}
    cfg = get_config()
    freed = 0
    for p in posts:
        for rel in (p.media_path, p.thumb_path):
            if rel:
                f = cfg.data_dir / rel
                if f.exists():
                    freed += f.stat().st_size
                    f.unlink()
        fts.deindex_post(db, p.id)
        db.delete(p)
    db.flush()
    return {"deleted": len(posts), "freed_bytes": freed, "dry_run": False}
