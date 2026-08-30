"""Core pipeline: adapter → normalize → dedupe → download media → extract
embedded metadata (BEFORE compression) → compress → store → learn/auto-push
hooks. Per-post failures are logged and skipped; a run never crashes the app."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import select

from .. import fts, settings_store
from ..aliases import normalize_model
from ..config import get_config
from ..db import session_scope
from ..logbus import bus
from ..models import Post
from ..scrapers.base import ScrapedPost
from . import hooks, media, metadata


@dataclass
class IngestStats:
    found: int = 0
    new: int = 0
    duplicates: int = 0
    skipped: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


def _is_duplicate(platform: str, platform_post_id: str) -> bool:
    with session_scope() as s:
        row = s.execute(
            select(Post.id).where(Post.platform == platform,
                                  Post.platform_post_id == platform_post_id)
        ).first()
        return row is not None


def _final_ext(media_type: str) -> str:
    return ".mp4" if media_type == "video" else ".webp"


def _sniff_media_type(head: bytes, fallback: str) -> str:
    if len(head) >= 8 and head[4:8] == b"ftyp":          # mp4/mov family
        return "video"
    if head.startswith(b"\x1a\x45\xdf\xa3"):             # webm/matroska
        return "video"
    if head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8")):
        return "image"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image"
    return fallback or "image"


def ingest_one(sp: ScrapedPost, client: httpx.Client,
               origin: str = "scraped") -> int | None:
    """Download, compress, store one post. Returns new post id or None
    (duplicate/skipped). Raises on hard failure (caller counts it)."""
    cfg = get_config()
    if _is_duplicate(sp.platform, sp.platform_post_id):
        return None

    uid = uuid.uuid4().hex
    platform_dir = cfg.media_dir / sp.platform
    tmp_path = platform_dir / f".tmp-{uid}"
    platform_dir.mkdir(parents=True, exist_ok=True)

    try:
        media.download(sp.media_url, tmp_path, client)

        # correct media type from actual content (magic bytes > URL ext > adapter claim)
        with tmp_path.open("rb") as fh:
            head = fh.read(16)
        media_type = _sniff_media_type(
            head, media.guess_media_type(sp.media_url) or sp.media_type)

        # embedded metadata BEFORE compression (images only)
        embedded: dict = {}
        if media_type == "image":
            embedded = metadata.extract_metadata(tmp_path)

        prompt = sp.prompt or embedded.get("prompt")
        negative = sp.negative_prompt or embedded.get("negative_prompt")
        params = dict(embedded.get("params") or {})
        params.update(sp.params or {})  # site-provided structured params win

        model_name = sp.model_name or params.get("model")

        with session_scope() as s:
            quality = settings_store.get(s, "image_quality")
            max_dim = settings_store.get(s, "image_max_dim")
            crf = settings_store.get(s, "video_crf")
            max_h = settings_store.get(s, "video_max_height")
            keep_originals = settings_store.get(s, "keep_originals")
            user_rules = settings_store.get(s, "model_aliases") or {}

        final_rel = Path("media") / sp.platform / f"{uid}{_final_ext(media_type)}"
        thumb_rel = Path("media") / sp.platform / "thumbs" / f"{uid}.webp"
        final_abs = cfg.data_dir / final_rel
        thumb_abs = cfg.data_dir / thumb_rel

        if media_type == "video":
            res = media.compress_video(tmp_path, final_abs, crf=crf, max_height=max_h)
            media.make_video_thumb(final_abs, thumb_abs)
        else:
            res = media.compress_image(tmp_path, final_abs, quality=quality, max_dim=max_dim)
            media.make_image_thumb(tmp_path, thumb_abs)  # thumb from original (best quality)

        if keep_originals:
            orig_dir = platform_dir / "originals"
            orig_dir.mkdir(parents=True, exist_ok=True)
            src_ext = Path(sp.media_url.split("?")[0]).suffix or ".bin"
            tmp_path.rename(orig_dir / f"{uid}{src_ext}")
        else:
            tmp_path.unlink(missing_ok=True)

        params["_original_bytes"] = res.original_bytes
        params["_stored_bytes"] = res.stored_bytes

        family = normalize_model(model_name, user_rules)

        with session_scope() as s:
            post = Post(
                platform=sp.platform,
                platform_post_id=sp.platform_post_id,
                prompt=prompt,
                negative_prompt=negative,
                model_name=model_name,
                model_family=family,
                model_version=sp.model_version,
                params=params,
                media_type=media_type,
                media_url=sp.media_url,
                media_path=str(final_rel),
                thumb_path=str(thumb_rel),
                media_width=res.width or None,
                media_height=res.height or None,
                duration_s=res.duration_s,
                author=sp.author,
                source_url=sp.source_url,
                posted_at=sp.posted_at,
                nsfw=sp.nsfw,
                origin=origin,
            )
            s.add(post)
            s.flush()
            fts.index_post(s, post.id, post.prompt, post.model_name, [])
            post_id = post.id

        hooks.run_post_ingested(post_id)
        return post_id
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def ingest_batch(source: str, posts: list[ScrapedPost],
                 client: httpx.Client) -> IngestStats:
    stats = IngestStats(found=len(posts))
    for sp in posts:
        try:
            if not sp.media_url:
                stats.skipped += 1
                continue
            result = ingest_one(sp, client)
            if result is None:
                stats.duplicates += 1
            else:
                stats.new += 1
        except Exception as e:
            stats.errors += 1
            msg = f"{sp.platform}:{sp.platform_post_id}: {type(e).__name__}: {e}"
            stats.error_messages.append(msg)
            bus.error(f"scraper.{source}", f"ingest failed — {msg}")
    return stats
