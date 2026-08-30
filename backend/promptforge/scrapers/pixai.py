"""PixAI adapter (5.6) — public gallery; intercepts the GraphQL artwork feed.
Experimental (GraphQL schema shifts)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import ScrapedPost
from .browser_base import BrowserAdapter, walk_find_lists


def _node_predicate(node: dict) -> bool:
    has_id = isinstance(node.get("id"), (str, int)) and node.get("id")
    media = node.get("media") or node.get("mediaUrl")
    return bool(has_id and (isinstance(media, dict) or isinstance(media, str))
                and (node.get("prompts") or node.get("prompt")
                     or node.get("title") is not None))


def _media_url(node: dict) -> tuple[str | None, int | None, int | None]:
    media = node.get("media")
    if isinstance(media, dict):
        urls = media.get("urls")
        if isinstance(urls, list):
            public = next((u.get("url") for u in urls
                           if isinstance(u, dict)
                           and str(u.get("variant", "")).upper() in ("PUBLIC", "ORIGINAL")),
                          None)
            fallback = next((u.get("url") for u in urls if isinstance(u, dict)
                             and u.get("url")), None)
            return public or fallback, media.get("width"), media.get("height")
        if isinstance(media.get("url"), str):
            return media["url"], media.get("width"), media.get("height")
    if isinstance(node.get("mediaUrl"), str):
        return node["mediaUrl"], None, None
    return None, None, None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_node(node: dict) -> ScrapedPost | None:
    url, width, height = _media_url(node)
    node_id = node.get("id")
    if not url or not node_id:
        return None
    prompt = node.get("prompts") or node.get("prompt") or None
    if isinstance(prompt, list):
        prompt = "\n".join(str(p) for p in prompt) or None

    parameters = node.get("parameters") or {}
    if not isinstance(parameters, dict):
        parameters = {}
    params: dict[str, Any] = {}
    for src, dst in (("samplingSteps", "steps"), ("steps", "steps"),
                     ("samplingMethod", "sampler"), ("sampler", "sampler"),
                     ("seed", "seed"), ("cfgScale", "cfg_scale"),
                     ("modelId", "model_id"), ("lora", "loras")):
        if parameters.get(src) not in (None, "", {}):
            params[dst] = parameters[src]
    negative = parameters.get("negativePrompts") or parameters.get("negativePrompt")
    if isinstance(negative, list):
        negative = "\n".join(str(n) for n in negative) or None
    if width and height:
        params["size"] = f"{width}x{height}"

    model = (parameters.get("modelName") or node.get("modelName")
             or parameters.get("model") or None)
    if not model and params.get("model_id"):
        model = f"pixai-model-{params['model_id']}"

    author = node.get("authorName")
    author_obj = node.get("author")
    if not author and isinstance(author_obj, dict):
        author = author_obj.get("username") or author_obj.get("displayName")

    is_video = str(url).split("?")[0].lower().endswith((".mp4", ".webm"))

    return ScrapedPost(
        platform="pixai",
        platform_post_id=str(node_id),
        media_url=url,
        media_type="video" if is_video else "image",
        prompt=prompt,
        negative_prompt=negative,
        model_name=model,
        params=params,
        author=author,
        source_url=f"https://pixai.art/artwork/{node_id}",
        posted_at=_parse_dt(node.get("createdAt")),
        nsfw=bool(node.get("isNsfw") or node.get("nsfw")),
    )


class PixAIAdapter(BrowserAdapter):
    name = "pixai"
    label = "PixAI"
    requires_auth = False
    experimental = True
    default_interval_minutes = 60
    min_interval_minutes = 20
    start_url = "https://pixai.art/en/artworks"

    def wants_response(self, url: str) -> bool:
        u = url.lower()
        return "pixai" in u and "graphql" in u

    def parse_captured(self, responses: list[dict]) -> list[ScrapedPost]:
        posts: list[ScrapedPost] = []
        seen: set[str] = set()
        for resp in responses:
            for node in walk_find_lists(resp.get("json"), _node_predicate):
                sp = parse_node(node)
                if sp is not None and sp.platform_post_id not in seen:
                    seen.add(sp.platform_post_id)
                    posts.append(sp)
        return posts
