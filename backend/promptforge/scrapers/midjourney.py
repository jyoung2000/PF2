"""Midjourney Explore adapter (5.3) — requires the user's paid login session
(storage_state from scripts/capture_login.py). VirtualScroll feed; prompts +
model version come from intercepted internal JSON (jobs). Parsing is
deliberately multi-shape: MJ's app API envelope moves around (D46)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .base import ScrapedPost
from .browser_base import BrowserAdapter, walk_find_lists

CDN = "https://cdn.midjourney.com"
_version_re = re.compile(r"--(?:v|version)\s+([\w.]+)")
_niji_re = re.compile(r"--niji\s*([\w.]*)")


def _job_predicate(node: dict) -> bool:
    has_id = isinstance(node.get("id"), str) and len(str(node.get("id"))) >= 8
    has_prompt = any(isinstance(node.get(k), str) and node.get(k)
                     for k in ("prompt", "full_command", "fullCommand"))
    return has_id and has_prompt


def _image_url(job: dict) -> str | None:
    for key in ("image_paths", "imagePaths"):
        paths = job.get(key)
        if isinstance(paths, list) and paths and isinstance(paths[0], str):
            return paths[0]
    for key in ("video_url", "videoUrl"):
        if isinstance(job.get(key), str) and job[key]:
            return job[key]
    job_id = job.get("id")
    if job_id:
        return f"{CDN}/{job_id}/0_0.jpeg"
    return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_job(job: dict) -> ScrapedPost | None:
    url = _image_url(job)
    job_id = job.get("id")
    if not url or not job_id:
        return None
    command = (job.get("full_command") or job.get("fullCommand")
               or job.get("prompt") or "")
    prompt = job.get("prompt") or command
    # strip trailing parameter flags from the displayed prompt
    prompt = re.split(r"\s--\w", prompt)[0].strip() or None

    niji = _niji_re.search(command)
    version = _version_re.search(command)
    if niji:
        model_name = f"Niji {niji.group(1)}".strip()
        model_version = niji.group(1) or None
    else:
        model_name = "Midjourney"
        model_version = version.group(1) if version else None
        if model_version:
            model_name = f"Midjourney v{model_version}"

    params: dict[str, Any] = {}
    for flag, key in (("ar", "aspect_ratio"), ("chaos", "chaos"), ("s", "stylize"),
                      ("stylize", "stylize"), ("weird", "weird"), ("seed", "seed"),
                      ("sref", "style_reference"), ("cref", "character_reference")):
        m = re.search(rf"--{flag}\s+(\S+)", command)
        if m:
            params[key] = m.group(1)

    media_type = "video" if (str(job.get("job_type") or job.get("jobType") or "")
                             .lower().find("video") >= 0
                             or str(url).split("?")[0].endswith(".mp4")) else "image"
    width = job.get("width") or job.get("event", {}).get("width") \
        if isinstance(job.get("event"), dict) else job.get("width")
    height = job.get("height")
    if width and height:
        params.setdefault("size", f"{width}x{height}")

    return ScrapedPost(
        platform="midjourney",
        platform_post_id=str(job_id),
        media_url=url,
        media_type=media_type,
        prompt=prompt,
        model_name=model_name,
        model_version=model_version,
        params=params,
        author=(job.get("username") or job.get("user", {}).get("username")
                if isinstance(job.get("user"), dict) else job.get("username")),
        source_url=f"https://www.midjourney.com/jobs/{job_id}",
        posted_at=_parse_dt(job.get("enqueue_time") or job.get("enqueueTime")
                            or job.get("created_at")),
        nsfw=bool(job.get("isNsfw") or job.get("nsfw")),
    )


class MidjourneyAdapter(BrowserAdapter):
    name = "midjourney"
    label = "Midjourney Explore"
    requires_auth = True
    default_interval_minutes = 60
    min_interval_minutes = 30
    start_url = "https://www.midjourney.com/explore?tab=recent"
    scroll_mode = "virtual"
    virtual_scroll_selector = "#pageScroll"
    scroll_count = 10

    def wants_response(self, url: str) -> bool:
        u = url.lower()
        return ("midjourney.com" in u and "/api/" in u
                and any(k in u for k in ("explore", "jobs", "search", "recent")))

    def parse_captured(self, responses: list[dict]) -> list[ScrapedPost]:
        posts: list[ScrapedPost] = []
        seen: set[str] = set()
        for resp in responses:
            for job in walk_find_lists(resp.get("json"), _job_predicate):
                sp = parse_job(job)
                if sp is not None and sp.platform_post_id not in seen:
                    seen.add(sp.platform_post_id)
                    posts.append(sp)
        return posts
