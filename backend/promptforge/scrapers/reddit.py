"""Reddit adapter (Inspiration 2.0, I9) — Tier 1, no browser, no login.

Reddit serves its own public JSON for search, subreddit listings and comment
threads (`.json` on any URL). That makes it the highest-value Grok-free
prompt source in PF2: AI-art subreddits routinely post the full prompt, and
when they don't, the prompt is very often in the author's own top comment —
which this adapter can fetch through the standard enrichment capability.

Deterministic throughout: JSON in, ScrapedPost out, prompts mined by the
shared parser. No AI is involved at scrape time.
"""
from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from .. import settings_store
from .base import USER_AGENT, ScrapedPost, SourceAdapter
from .social_base import SocialAdapter, ts

API = "https://www.reddit.com"
DEFAULT_SUBS = ["StableDiffusion", "aivideo", "midjourney", "comfyui",
                "singularity", "generative"]
DEFAULT_TERMS = ["prompt", "workflow"]
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")


class RedditAdapter(SocialAdapter, SourceAdapter):
    name = "reddit"
    label = "Reddit"
    tier = 1
    requires_auth = False
    auth_kind = "none"
    default_interval_minutes = 20
    min_interval_minutes = 10
    capabilities = frozenset({"search", "author", "detail", "comments", "thread",
                              "media", "video", "image", "pagination", "public",
                              "api", "prompt"})
    extraction_policy = {
        "prompt_locations": ["caption", "comment", "thread"],
        "comments_matter": True,      # "prompt in comments" is the norm here
        "metadata_available": False,  # reddit strips PNG metadata on upload
        "threads_matter": True,
    }

    # -- config ------------------------------------------------------------
    def is_configured(self, s: Session) -> bool:
        return True

    def make_client(self, s: Session) -> httpx.Client:
        return httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                            timeout=45, follow_redirects=True)

    def subreddits(self, s: Session) -> list[str]:
        return self.search_terms(s, "reddit_subreddits", DEFAULT_SUBS)

    # -- parsing -----------------------------------------------------------
    @staticmethod
    def _media_of(data: dict) -> tuple[str | None, str, dict]:
        """(url, type, media envelope). Prefers the real media over previews;
        galleries yield their first image (the rest land in `relations`)."""
        media: dict[str, Any] = {}
        if data.get("is_video") and (data.get("media") or {}).get("reddit_video"):
            rv = data["media"]["reddit_video"]
            media = {"type": "video", "url": rv.get("fallback_url"),
                     "duration_s": rv.get("duration"),
                     "width": rv.get("width"), "height": rv.get("height")}
            return rv.get("fallback_url"), "video", media
        url = data.get("url_overridden_by_dest") or data.get("url") or ""
        if url.lower().endswith(IMAGE_EXT):
            return url, "image", {"type": "image", "url": url}
        gallery = (data.get("media_metadata") or {})
        if gallery:
            for item in gallery.values():
                src = ((item or {}).get("s") or {}).get("u") or ((item or {}).get("s") or {}).get("gif")
                if src:
                    src = src.replace("&amp;", "&")
                    return src, "image", {"type": "image", "url": src,
                                          "gallery_size": len(gallery)}
        preview = (((data.get("preview") or {}).get("images") or [{}])[0].get("source") or {})
        if preview.get("url"):
            src = preview["url"].replace("&amp;", "&")
            return src, "image", {"type": "image", "url": src, "from_preview": True}
        return None, "image", media

    def _post_from(self, data: dict, replies: list[dict] | None = None) -> ScrapedPost | None:
        media_url, media_type, media = self._media_of(data)
        if not media_url:
            return None
        permalink = data.get("permalink") or ""
        return self.build_post(
            platform=self.name,
            post_id=data.get("id") or data.get("name") or permalink,
            media_url=media_url, media_type=media_type, media=media,
            title=data.get("title"), text=data.get("selftext") or None,
            author=data.get("author"),
            author_meta={"profile_url": f"{API}/user/{data.get('author')}"} if data.get("author") else None,
            source_url=f"{API}{permalink}" if permalink else data.get("url"),
            posted_at=ts(data.get("created_utc")),
            engagement={"likes": data.get("ups"), "comments": data.get("num_comments"),
                        "score": data.get("score"), "ratio": data.get("upvote_ratio")},
            replies=replies, nsfw=bool(data.get("over_18")),
            relations={"subreddit": data.get("subreddit"),
                       "flair": data.get("link_flair_text"),
                       "crosspost": bool(data.get("crosspost_parent"))},
            extra_params={"subreddit": data.get("subreddit")})

    def parse_listing(self, payload: dict) -> list[ScrapedPost]:
        """A listing envelope → posts (defensive: shapes vary by endpoint)."""
        out: list[ScrapedPost] = []
        children = ((payload or {}).get("data") or {}).get("children") or []
        for child in children:
            data = (child or {}).get("data") or {}
            if not data or child.get("kind") not in (None, "t3"):
                continue
            post = self._post_from(data)
            if post is not None:
                out.append(post)
        return out

    def parse_comments(self, payload: Any, author: str | None = None,
                       limit: int = 25) -> list[dict]:
        """Comment tree → flat reply dicts for the shared parser (creator's
        own comments first — that is where prompts live)."""
        listings = payload if isinstance(payload, list) else [payload]
        rows: list[dict] = []

        def walk(node: Any, depth: int = 0) -> None:
            if depth > 3 or len(rows) >= limit * 2:
                return
            if isinstance(node, dict):
                data = node.get("data") or {}
                if node.get("kind") == "t1" and data.get("body"):
                    rows.append({"id": data.get("id"), "text": data.get("body"),
                                 "author": data.get("author"),
                                 "url": f"{API}{data.get('permalink')}" if data.get("permalink") else None,
                                 "score": data.get("score"),
                                 "is_creator": bool(author) and data.get("author") == author})
                for key in ("children", "replies"):
                    if data.get(key):
                        walk(data[key], depth + 1)
                if node.get("data", {}).get("children"):
                    walk(node["data"]["children"], depth + 1)
            elif isinstance(node, list):
                for item in node:
                    walk(item, depth)

        walk(listings)
        rows.sort(key=lambda r: (not r.get("is_creator"), -(r.get("score") or 0)))
        return rows[:limit]

    # -- fetching ----------------------------------------------------------
    def fetch_recent(self, s: Session, client: httpx.Client,
                     limit: int = 100) -> list[ScrapedPost]:
        """Rotate the configured subreddits, newest first."""
        subs = self.subreddits(s)
        state = self.get_state(s)
        idx = int((state.state or {}).get("sub_index", 0))
        sub = subs[idx % len(subs)] if subs else DEFAULT_SUBS[0]
        state.state = {**(state.state or {}), "sub_index": (idx + 1) % max(1, len(subs)),
                       "last_subreddit": sub}
        s.flush()
        r = client.get(f"{API}/r/{sub}/new.json", params={"limit": min(100, limit),
                                                          "raw_json": 1})
        r.raise_for_status()
        return self.parse_listing(r.json())[:limit]

    def search(self, s: Session, client: httpx.Client, query: str, *,
               limit: int = 50, sort: str = "new", period: str = "week",
               subreddit: str | None = None) -> list[ScrapedPost]:
        """Research entry point (§27): a real query against Reddit search."""
        path = f"/r/{subreddit}/search.json" if subreddit else "/search.json"
        params = {"q": query, "limit": min(100, limit), "sort": sort,
                  "t": period, "raw_json": 1, "type": "link"}
        if subreddit:
            params["restrict_sr"] = "1"
        r = client.get(f"{API}{path}", params=params)
        r.raise_for_status()
        return self.parse_listing(r.json())[:limit]

    def fetch_author(self, s: Session, client: httpx.Client, handle: str, *,
                     limit: int = 50) -> list[ScrapedPost]:
        r = client.get(f"{API}/user/{handle.lstrip('@u/')}/submitted.json",
                       params={"limit": min(100, limit), "sort": "new", "raw_json": 1})
        r.raise_for_status()
        return self.parse_listing(r.json())[:limit]

    def fetch_comments(self, s: Session, client: httpx.Client,
                       platform_post_id: str) -> list[dict]:
        with session_or(s) as sess:
            max_comments = int(settings_store.get(sess, "research_max_comments") or 25)
        r = client.get(f"{API}/comments/{platform_post_id}.json",
                       params={"limit": max_comments, "sort": "top", "raw_json": 1})
        r.raise_for_status()
        payload = r.json()
        author = None
        try:
            author = payload[0]["data"]["children"][0]["data"]["author"]
        except (KeyError, IndexError, TypeError):
            pass
        return self.parse_comments(payload, author=author, limit=max_comments)

    def fetch_thread(self, s: Session, client: httpx.Client,
                     platform_post_id: str) -> list[dict]:
        """The author's own comments on their post — where the prompt hides."""
        return [c for c in self.fetch_comments(s, client, platform_post_id)
                if c.get("is_creator")]

    def test_connection(self, s: Session) -> dict:
        try:
            with self.make_client(s) as client:
                r = client.get(f"{API}/r/{DEFAULT_SUBS[0]}/new.json", params={"limit": 1})
            if r.status_code == 200:
                return {"ok": True, "detail": "Reddit's public JSON API is reachable."}
            if r.status_code in (403, 429):
                return {"ok": False, "detail": f"Reddit rate-limited this host (HTTP {r.status_code}) "
                                               "— it will retry with backoff."}
            return {"ok": False, "detail": f"Unexpected HTTP {r.status_code} from Reddit."}
        except httpx.HTTPError as e:
            return {"ok": False, "detail": f"Can't reach Reddit: {type(e).__name__}"}


class _NullCtx:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *a):
        return False


def session_or(s):
    """Use the caller's session when given one (enrichment passes it)."""
    return _NullCtx(s)
