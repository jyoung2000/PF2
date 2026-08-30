"""TensorArt adapter (5.4) — public gallery; intercepts the community post
list JSON. Captures prompt, negative, model, LoRAs, sampler, seed."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import ScrapedPost
from .browser_base import BrowserAdapter, walk_find_lists


def _post_predicate(node: dict) -> bool:
    has_id = any(node.get(k) for k in ("postId", "id"))
    imgs = node.get("images") or node.get("imageList")
    return bool(has_id and isinstance(imgs, list) and imgs)


def _diffusion_info(item: dict) -> dict:
    for key in ("diffusionInfo", "generationInfo", "meta", "genMeta"):
        v = item.get(key)
        if isinstance(v, dict):
            return v
    # sometimes nested on the first image
    imgs = item.get("images") or []
    if imgs and isinstance(imgs[0], dict):
        for key in ("diffusionInfo", "meta"):
            v = imgs[0].get(key)
            if isinstance(v, dict):
                return v
    return {}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / (1000 if value > 1e12 else 1))
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OSError, OverflowError):
        return None


def parse_post(item: dict) -> ScrapedPost | None:
    post_id = item.get("postId") or item.get("id")
    images = item.get("images") or item.get("imageList") or []
    if not post_id or not images or not isinstance(images[0], dict):
        return None
    first = images[0]
    url = first.get("url") or first.get("originalUrl") or first.get("src")
    if not url:
        return None

    info = _diffusion_info(item)
    prompt = (info.get("prompt") or info.get("prompts") or item.get("prompt")
              or None)
    if isinstance(prompt, list):
        prompt = "\n".join(str(p) for p in prompt) or None
    negative = info.get("negativePrompt") or info.get("negative_prompt")

    model = None
    loras: list[str] = []
    models_field = info.get("models")
    if isinstance(models_field, list):
        for m in models_field:
            if not isinstance(m, dict):
                continue
            label = m.get("label") or m.get("name") or m.get("modelName")
            mtype = str(m.get("type") or "").upper()
            if mtype == "LORA" and label:
                loras.append(label)
            elif label and model is None:
                model = label
    model = model or info.get("model") or info.get("baseModel") or None

    params: dict[str, Any] = {}
    for src, dst in (("samplerName", "sampler"), ("sampler", "sampler"),
                     ("seed", "seed"), ("steps", "steps"),
                     ("cfgScale", "cfg_scale"), ("cfg_scale", "cfg_scale"),
                     ("vae", "vae"), ("clipSkip", "clip_skip")):
        if info.get(src) not in (None, ""):
            params[dst] = info[src]
    if loras:
        params["loras"] = loras
    width, height = first.get("width"), first.get("height")
    if width and height:
        params["size"] = f"{width}x{height}"

    user = item.get("user") or item.get("creator") or {}
    author = (user.get("username") or user.get("nickName") or user.get("name")
              if isinstance(user, dict) else None)

    is_video = bool(first.get("isVideo")) or str(url).split("?")[0].lower().endswith(
        (".mp4", ".webm"))

    return ScrapedPost(
        platform="tensorart",
        platform_post_id=str(post_id),
        media_url=url,
        media_type="video" if is_video else "image",
        prompt=prompt,
        negative_prompt=negative,
        model_name=model,
        params=params,
        author=author,
        source_url=f"https://tensor.art/posts/{post_id}",
        posted_at=_parse_dt(item.get("createdTime") or item.get("publishTime")
                            or item.get("created_at")),
        nsfw=bool(item.get("isNsfw") or item.get("nsfw")),
    )


class TensorArtAdapter(BrowserAdapter):
    name = "tensorart"
    label = "TensorArt"
    requires_auth = False
    default_interval_minutes = 60
    min_interval_minutes = 20
    start_url = "https://tensor.art/posts"

    def wants_response(self, url: str) -> bool:
        u = url.lower()
        return ("tensor.art" in u
                and any(k in u for k in ("/post/list", "/posts", "community",
                                         "/post/query")))

    def parse_captured(self, responses: list[dict]) -> list[ScrapedPost]:
        posts: list[ScrapedPost] = []
        seen: set[str] = set()
        for resp in responses:
            for item in walk_find_lists(resp.get("json"), _post_predicate):
                sp = parse_post(item)
                if sp is not None and sp.platform_post_id not in seen:
                    seen.add(sp.platform_post_id)
                    posts.append(sp)
        return posts
