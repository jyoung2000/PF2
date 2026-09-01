"""Civitai adapter — official REST API (civitai.com/api/v1/images).

Cursor pagination, newest-first, optional CIVITAI_API_KEY bearer token
(higher limits + NSFW). meta can be null (skip unless civitai_keep_metaless).
Items include videos — detected via item.type / URL / magic bytes (D27)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .. import settings_store
from .base import USER_AGENT, ScrapedPost, SourceAdapter

API_URL = "https://civitai.com/api/v1/images"


def _api_url() -> str:
    """Overridable for stand-in servers in tests/smoke runs (PF_CIVITAI_API_URL)."""
    import os
    return os.environ.get("PF_CIVITAI_API_URL", API_URL)

_META_PARAM_KEYS = {
    "seed": "seed", "steps": "steps", "sampler": "sampler",
    "cfgScale": "cfg_scale", "Size": "size", "Clip skip": "clip_skip",
    "Denoising strength": "denoising_strength", "workflow": "workflow_name",
}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_nsfw(item: dict) -> bool:
    lvl = item.get("nsfwLevel")
    if isinstance(lvl, bool):
        return lvl
    if isinstance(lvl, (int, float)):
        return lvl > 1
    if isinstance(lvl, str):
        return lvl.lower() not in ("none", "safe", "")
    return bool(item.get("nsfw"))


def parse_item(item: dict, keep_metaless: bool = False) -> ScrapedPost | None:
    """Map one API item → ScrapedPost. Returns None to skip."""
    url = item.get("url")
    item_id = item.get("id")
    if not url or item_id is None:
        return None
    meta = item.get("meta")
    if not isinstance(meta, dict):
        meta = None
    if meta is None and not keep_metaless:
        return None

    params: dict[str, Any] = {}
    prompt = negative = model = None
    if meta:
        prompt = meta.get("prompt") or None
        negative = meta.get("negativePrompt") or None
        model = meta.get("Model") or meta.get("model") or None
        for src_key, dst_key in _META_PARAM_KEYS.items():
            if meta.get(src_key) not in (None, ""):
                params[dst_key] = meta[src_key]
        resources = meta.get("resources") or meta.get("civitaiResources")
        if isinstance(resources, list) and resources:
            loras = [r.get("name") or r.get("modelVersionName")
                     for r in resources
                     if isinstance(r, dict) and str(r.get("type", "")).lower() == "lora"]
            loras = [x for x in loras if x]
            if loras:
                params["loras"] = loras

    base_model = item.get("baseModel") or None
    media_type = "video" if str(item.get("type", "")).lower() == "video" else "image"
    if str(url).split("?")[0].lower().endswith((".mp4", ".webm")):
        media_type = "video"

    return ScrapedPost(
        platform="civitai",
        platform_post_id=str(item_id),
        media_url=url,
        media_type=media_type,
        prompt=prompt,
        negative_prompt=negative,
        model_name=model or base_model,
        model_version=base_model if model else None,
        params=params,
        author=item.get("username"),
        source_url=f"https://civitai.com/images/{item_id}",
        posted_at=_parse_dt(item.get("createdAt") or item.get("publishedAt")),
        nsfw=_is_nsfw(item),
    )


class CivitaiAdapter(SourceAdapter):
    name = "civitai"
    label = "Civitai"
    tier = 1
    requires_auth = False           # key optional
    default_interval_minutes = 10
    min_interval_minutes = 5        # respect their caching — never poll faster
    auth_kind = "api_key"
    api_key_setting = "civitai_api_key"
    api_key_url = "https://civitai.com/user/account"

    def make_client(self, s: Session, transport=None) -> httpx.Client:
        headers = {"User-Agent": USER_AGENT}
        key = settings_store.get(s, "civitai_api_key")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return httpx.Client(headers=headers, timeout=60, follow_redirects=True,
                            transport=transport)

    def test_connection(self, s: Session, transport=None) -> dict:
        """Paste-to-connect check: one authenticated 1-item request. Never
        raises — {ok, detail} drives the GUI badge."""
        if not settings_store.get(s, "civitai_api_key"):
            return {"ok": False, "detail": "No API key stored — paste one from "
                    "civitai.com → Account settings → API keys."}
        try:
            with self.make_client(s, transport=transport) as client:
                resp = client.get(_api_url(), params={"limit": 1})
        except httpx.HTTPError as e:
            return {"ok": False,
                    "detail": f"Can't reach Civitai ({type(e).__name__})."}
        if resp.status_code in (401, 403):
            return {"ok": False, "detail":
                    f"Civitai rejected the key (HTTP {resp.status_code}) — "
                    "create a fresh one under Account settings → API keys."}
        if resp.status_code != 200:
            return {"ok": False, "detail":
                    f"Civitai answered HTTP {resp.status_code} — try again "
                    "in a minute."}
        return {"ok": True,
                "detail": "Key accepted — higher rate limits + NSFW unlocked."}

    def fetch_recent(self, s: Session, client: httpx.Client,
                     limit: int = 100) -> list[ScrapedPost]:
        keep_metaless = bool(settings_store.get(s, "civitai_keep_metaless"))
        posts: list[ScrapedPost] = []
        cursor: str | None = None
        while len(posts) < limit:
            page_limit = min(100, limit)
            params: dict[str, Any] = {"limit": page_limit, "sort": "Newest"}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(_api_url(), params=params)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            for item in items:
                sp = parse_item(item, keep_metaless=keep_metaless)
                if sp is not None:
                    posts.append(sp)
                    if len(posts) >= limit:
                        break
            cursor = (data.get("metadata") or {}).get("nextCursor")
            if not items or not cursor:
                break
        return posts
