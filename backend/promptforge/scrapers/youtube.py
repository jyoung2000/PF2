"""YouTube adapter (Inspiration 2.0, I9) — Tier 1, experimental.

YouTube ships its search results and watch pages as a JSON blob
(`ytInitialData` / `ytInitialPlayerResponse`) inside the HTML, so PF2 can
read them with plain HTTP and a defensive walk — no browser, no API key.
The value here is §119: AI-video creators put the full prompt and workflow
in the DESCRIPTION and the pinned comment far more often than in the title.

Marked experimental because the blob's shape is YouTube's private contract;
every parse is defensive and a shape change degrades to "no results", never
to a crash. Thumbnails are the stored media (PF2 never downloads the video
stream itself).
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .base import USER_AGENT, ScrapedPost, SourceAdapter
from .browser_base import walk_find_lists
from .social_base import SocialAdapter

WATCH = "https://www.youtube.com/watch?v="
DEFAULT_TERMS = ["ai video prompt tutorial", "comfyui workflow", "veo 3 prompt",
                 "kling ai prompt", "runway gen-4 workflow"]
_BLOB_RES = (re.compile(r"ytInitialData\s*=\s*(\{.+?\});</script>", re.S),
             re.compile(r'var ytInitialData = (\{.+?\});', re.S),
             re.compile(r"ytInitialPlayerResponse\s*=\s*(\{.+?\});", re.S))
_DUR_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})")


def _text_of(node: Any) -> str | None:
    """YouTube renders text as {simpleText} or {runs:[{text}]}."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return None
    if node.get("simpleText"):
        return node["simpleText"]
    runs = node.get("runs")
    if isinstance(runs, list):
        joined = "".join(r.get("text", "") for r in runs if isinstance(r, dict))
        return joined or None
    return None


def _int_of(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text.split()[0] if text.split() else "")
    return int(digits) if digits else None


def _duration_s(text: str | None) -> int | None:
    if not text:
        return None
    m = _DUR_RE.search(text)
    if not m:
        return None
    h, mnt, sec = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(sec)


def extract_blob(html: str) -> dict:
    """First parseable ytInitialData-style blob in the page (defensive)."""
    for pattern in _BLOB_RES:
        m = pattern.search(html or "")
        if not m:
            continue
        try:
            return json.loads(m.group(1))
        except ValueError:
            continue
    return {}


class YouTubeAdapter(SocialAdapter, SourceAdapter):
    name = "youtube"
    label = "YouTube"
    tier = 1
    requires_auth = False
    experimental = True
    auth_kind = "none"
    default_interval_minutes = 45
    min_interval_minutes = 15
    capabilities = frozenset({"search", "author", "detail", "media", "video",
                              "pagination", "public", "prompt"})
    extraction_policy = {
        "prompt_locations": ["description", "comment", "caption"],
        "comments_matter": True,       # pinned comments carry workflows
        "metadata_available": False,
        "threads_matter": False,
        "note": "descriptions are the primary prompt/workflow location (§119)",
    }

    def make_client(self, s: Session) -> httpx.Client:
        return httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            timeout=45, follow_redirects=True)

    def terms(self, s: Session) -> list[str]:
        return self.search_terms(s, "youtube_terms", DEFAULT_TERMS)

    # -- parsing -----------------------------------------------------------
    def parse_search(self, html_or_blob: Any, descriptions: dict | None = None
                     ) -> list[ScrapedPost]:
        blob = html_or_blob if isinstance(html_or_blob, dict) else extract_blob(html_or_blob)
        renderers = walk_find_lists(blob, lambda d: "videoId" in d and "title" in d,
                                    max_depth=16)
        out: list[ScrapedPost] = []
        seen: set[str] = set()
        for r in renderers:
            vid = r.get("videoId")
            title = _text_of(r.get("title"))
            if not vid or not title or vid in seen:
                continue
            seen.add(vid)
            thumbs = ((r.get("thumbnail") or {}).get("thumbnails") or [])
            thumb = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
            owner = (_text_of(r.get("ownerText")) or _text_of(r.get("longBylineText"))
                     or _text_of(r.get("shortBylineText")))
            snippet = " ".join(x for x in (
                _text_of(r.get("descriptionSnippet")),
                _text_of((r.get("detailedMetadataSnippets") or [{}])[0].get("snippetText")
                         if r.get("detailedMetadataSnippets") else None)) if x)
            description = (descriptions or {}).get(vid) or snippet or None
            duration = _duration_s(_text_of(r.get("lengthText")))
            out.append(self.build_post(
                platform=self.name, post_id=vid, media_url=thumb, media_type="image",
                media={"type": "image", "url": thumb, "video_url": f"{WATCH}{vid}",
                       "duration_s": duration, "is_thumbnail_of_video": True},
                title=title, description=description,
                author=owner.lstrip("@") if owner else None,
                source_url=f"{WATCH}{vid}",
                engagement={"views": _int_of(_text_of(r.get("viewCountText")))},
                relations={"published_text": _text_of(r.get("publishedTimeText")),
                           "duration_s": duration},
                extra_params={"youtube_video_id": vid,
                              "media_note": "thumbnail stored; the video stays on YouTube"}))
        return out

    def parse_watch(self, html: str) -> dict:
        """Watch page → {title, description, author, views} (the description
        is where prompts/workflows actually live)."""
        blob = extract_blob(html)
        details = (walk_find_lists(blob, lambda d: "videoId" in d and "shortDescription" in d,
                               max_depth=16) or [{}])[0]
        out = {"title": details.get("title"),
               "description": details.get("shortDescription"),
               "author": details.get("author"),
               "video_id": details.get("videoId"),
               "duration_s": int(details["lengthSeconds"]) if str(
                   details.get("lengthSeconds") or "").isdigit() else None,
               "views": _int_of(details.get("viewCount"))}
        if not out["description"]:
            data = extract_blob(html)
            attributed = walk_find_lists(data, lambda d: "attributedDescription" in d,
                                         max_depth=16)
            if attributed:
                out["description"] = ((attributed[0].get("attributedDescription") or {})
                                      .get("content"))
        return out

    # -- fetching ----------------------------------------------------------
    def _search_html(self, client: httpx.Client, query: str) -> str:
        r = client.get("https://www.youtube.com/results",
                       params={"search_query": query, "sp": "CAI%3D"})  # sort: newest
        r.raise_for_status()
        return r.text

    def fetch_recent(self, s: Session, client: httpx.Client,
                     limit: int = 50) -> list[ScrapedPost]:
        terms = self.terms(s)
        state = self.get_state(s)
        idx = int((state.state or {}).get("term_index", 0))
        term = terms[idx % len(terms)] if terms else DEFAULT_TERMS[0]
        state.state = {**(state.state or {}), "term_index": (idx + 1) % max(1, len(terms)),
                       "last_term": term}
        s.flush()
        return self.search(s, client, term, limit=limit)

    def search(self, s: Session, client: httpx.Client, query: str, *,
               limit: int = 25, with_descriptions: int = 6) -> list[ScrapedPost]:
        """Search, then fetch the top N watch pages for their descriptions —
        that is where the prompt usually is (§119). Bounded on purpose."""
        posts = self.parse_search(self._search_html(client, query))[:limit]
        for post in posts[:max(0, with_descriptions)]:
            vid = post.params.get("youtube_video_id")
            if not vid:
                continue
            try:
                r = client.get(f"{WATCH}{vid}")
                r.raise_for_status()
                detail = self.parse_watch(r.text)
            except httpx.HTTPError:
                continue
            if detail.get("description"):
                enriched = self.build_post(
                    platform=self.name, post_id=vid, media_url=post.media_url,
                    media_type="image", media=(post.observed or {}).get("media"),
                    title=detail.get("title") or (post.observed or {}).get("text", {}).get("title"),
                    description=detail["description"],
                    author=detail.get("author") or post.author,
                    source_url=post.source_url,
                    engagement={"views": detail.get("views")},
                    extra_params={"youtube_video_id": vid,
                                  "media_note": post.params.get("media_note")})
                post.prompt = enriched.prompt
                post.negative_prompt = enriched.negative_prompt
                post.model_name = post.model_name or enriched.model_name
                post.params.update({k: v for k, v in enriched.params.items()
                                    if k not in ("engagement",)})
                if post.observed is not None and enriched.observed is not None:
                    post.observed["text"] = enriched.observed["text"]
        return posts

    def fetch_author(self, s: Session, client: httpx.Client, handle: str, *,
                     limit: int = 30) -> list[ScrapedPost]:
        handle = handle if handle.startswith("@") else f"@{handle}"
        r = client.get(f"https://www.youtube.com/{handle}/videos")
        r.raise_for_status()
        return self.parse_search(r.text)[:limit]

    def test_connection(self, s: Session) -> dict:
        try:
            with self.make_client(s) as client:
                html = self._search_html(client, "ai video prompt")
            found = len(self.parse_search(html))
            if found:
                return {"ok": True, "detail": f"YouTube search reachable ({found} results parsed)."}
            return {"ok": False, "detail": "YouTube responded but no results parsed — its page "
                                           "shape may have changed (adapter is experimental)."}
        except httpx.HTTPError as e:
            return {"ok": False, "detail": f"Can't reach YouTube: {type(e).__name__}"}
