"""SeaArt adapter (5.5) — public explore feed, same network-capture approach
as TensorArt. Experimental: SeaArt reshapes its API often."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import ScrapedPost
from .browser_base import BrowserAdapter, walk_find_lists


def _item_predicate(node: dict) -> bool:
    has_id = any(isinstance(node.get(k), (str, int)) and node.get(k)
                 for k in ("id", "art_id", "artwork_id"))
    banner = node.get("banner") or node.get("cover") or node.get("image")
    return bool(has_id and (isinstance(banner, dict) and banner.get("url")
                            or isinstance(node.get("url"), str)))


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / (1000 if value > 1e12 else 1))
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OSError, OverflowError):
        return None


def parse_item(item: dict) -> ScrapedPost | None:
    item_id = item.get("id") or item.get("art_id") or item.get("artwork_id")
    banner = item.get("banner") or item.get("cover") or item.get("image") or {}
    url = banner.get("url") if isinstance(banner, dict) else item.get("url")
    if not item_id or not url:
        return None
    meta = item.get("meta") or item.get("apply_info") or {}
    if not isinstance(meta, dict):
        meta = {}

    params: dict[str, Any] = {}
    for src, dst in (("sampler_name", "sampler"), ("sampler", "sampler"),
                     ("seed", "seed"), ("steps", "steps"),
                     ("cfg_scale", "cfg_scale"), ("vae", "vae")):
        if meta.get(src) not in (None, ""):
            params[dst] = meta[src]
    if isinstance(banner, dict) and banner.get("width") and banner.get("height"):
        params["size"] = f"{banner['width']}x{banner['height']}"

    author = None
    user = item.get("author") or item.get("user") or {}
    if isinstance(user, dict):
        author = user.get("name") or user.get("username") or user.get("nick_name")

    is_video = str(url).split("?")[0].lower().endswith((".mp4", ".webm")) or bool(
        item.get("is_video"))

    return ScrapedPost(
        platform="seaart",
        platform_post_id=str(item_id),
        media_url=url,
        media_type="video" if is_video else "image",
        prompt=meta.get("prompt") or item.get("prompt") or None,
        negative_prompt=meta.get("negative_prompt") or None,
        model_name=(meta.get("model") or meta.get("model_no")
                    or meta.get("base_model") or None),
        params=params,
        author=author,
        source_url=f"https://www.seaart.ai/artwork/detail/{item_id}",
        posted_at=_parse_dt(item.get("create_time") or item.get("created_at")),
        nsfw=bool(item.get("is_nsfw") or item.get("nsfw")),
    )


class SeaArtAdapter(BrowserAdapter):
    name = "seaart"
    label = "SeaArt"
    requires_auth = False
    capabilities = frozenset({"browser_session", "search"})
    experimental = True
    default_interval_minutes = 60
    min_interval_minutes = 20
    start_url = "https://www.seaart.ai/explore"

    def wants_response(self, url: str) -> bool:
        u = url.lower()
        return ("seaart" in u and "/api/" in u
                and any(k in u for k in ("artwork", "explore", "list", "square")))

    def parse_captured(self, responses: list[dict]) -> list[ScrapedPost]:
        posts: list[ScrapedPost] = []
        seen: set[str] = set()
        for resp in responses:
            for item in walk_find_lists(resp.get("json"), _item_predicate):
                sp = parse_item(item)
                if sp is not None and sp.platform_post_id not in seen:
                    seen.add(sp.platform_post_id)
                    posts.append(sp)
        return posts
