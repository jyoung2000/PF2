"""Serialization helpers (plain dicts — shapes consumed by frontend/src/api.ts)."""
from __future__ import annotations

from .aliases import display_family
from .models import Collection, Post


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def post_card(p: Post) -> dict:
    return {
        "id": p.id,
        "platform": p.platform,
        "media_type": p.media_type,
        "media_url": f"/{p.media_path}" if p.media_path else None,
        "thumb_url": f"/{p.thumb_path}" if p.thumb_path else None,
        "width": p.media_width,
        "height": p.media_height,
        "duration_s": p.duration_s,
        "prompt": p.prompt,
        "model_name": p.model_name,
        "model_family": p.model_family,
        "model_family_label": display_family(p.model_family) if p.model_family else None,
        "favorite": p.favorite,
        "nsfw": p.nsfw,
        "origin": p.origin,
        "posted_at": _iso(p.posted_at),
        "scraped_at": _iso(p.scraped_at),
    }


def post_detail(p: Post, tag_names: list[str],
                collections: list[dict] | None = None) -> dict:
    d = post_card(p)
    params = {k: v for k, v in (p.params or {}).items() if not k.startswith("_")}
    d.update({
        "negative_prompt": p.negative_prompt,
        "model_version": p.model_version,
        "params": params,
        "technique_tags": p.technique_tags or [],
        "tags": tag_names,
        "collections": collections or [],
        "author": p.author,
        "source_url": p.source_url,
        "original_media_url": p.media_url,
        "synced_to_baserow": p.synced_to_baserow,
        "posted_to_discord": p.posted_to_discord,
        "original_bytes": (p.params or {}).get("_original_bytes"),
        "stored_bytes": (p.params or {}).get("_stored_bytes"),
    })
    return d


def collection_summary(c: Collection, count: int = 0,
                       cover_urls: list[str] | None = None) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "model_family": c.model_family,
        "model_family_label": display_family(c.model_family) if c.model_family else None,
        "allow_mixed_models": c.allow_mixed_models,
        "count": count,
        "cover_urls": cover_urls or [],
        "created_at": _iso(c.created_at),
    }
