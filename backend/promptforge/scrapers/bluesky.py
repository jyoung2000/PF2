"""Bluesky adapter (Inspiration 2.0, I9) — Tier 0, documented public API.

Bluesky's AppView (`public.api.bsky.app`) serves search, author feeds and
post threads without any credential, so this is the cheapest, most reliable
social source PF2 has: no browser, no login, no rate-limit games. AI-art and
AI-video posts there frequently carry the model name in the text and the
prompt in the author's own reply, both of which the shared parser handles.
"""
from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from .base import USER_AGENT, ScrapedPost, SourceAdapter
from .social_base import SocialAdapter, ts

API = "https://public.api.bsky.app/xrpc"
DEFAULT_TERMS = ["ai video prompt", "flux prompt", "kling ai", "veo 3", "comfyui workflow"]


class BlueskyAdapter(SocialAdapter, SourceAdapter):
    name = "bluesky"
    label = "Bluesky"
    tier = 0
    requires_auth = False
    auth_kind = "none"
    default_interval_minutes = 20
    min_interval_minutes = 10
    capabilities = frozenset({"search", "author", "detail", "thread", "comments",
                              "media", "image", "video", "pagination", "public",
                              "api", "prompt"})
    extraction_policy = {
        "prompt_locations": ["caption", "thread"],
        "comments_matter": True,
        "metadata_available": False,
        "threads_matter": True,
    }

    def make_client(self, s: Session) -> httpx.Client:
        return httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                            timeout=45, follow_redirects=True)

    def terms(self, s: Session) -> list[str]:
        return self.search_terms(s, "bluesky_terms", DEFAULT_TERMS)

    # -- parsing -----------------------------------------------------------
    @staticmethod
    def _rkey(uri: str) -> str:
        return (uri or "").rsplit("/", 1)[-1]

    @staticmethod
    def _media_of(post: dict) -> tuple[str | None, str, dict, str | None]:
        """(url, type, media envelope, alt text). Handles image, video and
        recordWithMedia embeds."""
        embed = post.get("embed") or {}
        for _ in range(2):     # unwrap recordWithMedia
            images = embed.get("images")
            if images:
                first = images[0] or {}
                url = first.get("fullsize") or first.get("thumb")
                return url, "image", {"type": "image", "url": url,
                                      "count": len(images),
                                      "thumb": first.get("thumb")}, first.get("alt")
            if embed.get("playlist") or embed.get("video"):
                url = embed.get("playlist") or embed.get("video")
                return url, "video", {"type": "video", "url": url,
                                      "thumb": embed.get("thumbnail")}, embed.get("alt")
            embed = embed.get("media") or {}
            if not embed:
                break
        return None, "image", {}, None

    def _post_from(self, post: dict, replies: list[dict] | None = None) -> ScrapedPost | None:
        url, media_type, media, alt = self._media_of(post)
        if not url:
            return None
        record = post.get("record") or {}
        author = post.get("author") or {}
        handle = author.get("handle")
        uri = post.get("uri") or ""
        text = record.get("text")
        return self.build_post(
            platform=self.name, post_id=uri or self._rkey(uri),
            media_url=url, media_type=media_type, media={**media, "alt": alt},
            text=text, description=alt if alt and alt != text else None,
            author=handle,
            author_meta={"display_name": author.get("displayName"),
                         "did": author.get("did"),
                         "profile_url": f"https://bsky.app/profile/{handle}" if handle else None},
            source_url=(f"https://bsky.app/profile/{handle}/post/{self._rkey(uri)}"
                        if handle and uri else None),
            posted_at=ts(record.get("createdAt") or post.get("indexedAt")),
            engagement={"likes": post.get("likeCount"), "replies": post.get("replyCount"),
                        "reposts": post.get("repostCount"), "quotes": post.get("quoteCount")},
            replies=replies,
            relations={"uri": uri, "cid": post.get("cid"),
                       "langs": record.get("langs")})

    def parse_search(self, payload: dict) -> list[ScrapedPost]:
        out = []
        for post in (payload or {}).get("posts") or []:
            sp = self._post_from(post)
            if sp is not None:
                out.append(sp)
        return out

    def parse_feed(self, payload: dict) -> list[ScrapedPost]:
        out = []
        for item in (payload or {}).get("feed") or []:
            post = (item or {}).get("post") or {}
            sp = self._post_from(post)
            if sp is not None:
                out.append(sp)
        return out

    def parse_thread(self, payload: dict, author: str | None = None) -> list[dict]:
        rows: list[dict] = []

        def walk(node: Any, depth: int = 0) -> None:
            if not isinstance(node, dict) or depth > 3:
                return
            post = node.get("post") or {}
            record = post.get("record") or {}
            who = (post.get("author") or {}).get("handle")
            if record.get("text") and depth > 0:
                rows.append({"id": post.get("uri"), "text": record.get("text"),
                             "author": who,
                             "url": (f"https://bsky.app/profile/{who}/post/"
                                     f"{BlueskyAdapter._rkey(post.get('uri') or '')}") if who else None,
                             "is_creator": bool(author) and who == author,
                             "score": post.get("likeCount")})
            for child in node.get("replies") or []:
                walk(child, depth + 1)

        walk((payload or {}).get("thread") or {})
        rows.sort(key=lambda r: (not r.get("is_creator"), -(r.get("score") or 0)))
        return rows

    # -- fetching ----------------------------------------------------------
    def fetch_recent(self, s: Session, client: httpx.Client,
                     limit: int = 100) -> list[ScrapedPost]:
        terms = self.terms(s)
        state = self.get_state(s)
        idx = int((state.state or {}).get("term_index", 0))
        term = terms[idx % len(terms)] if terms else DEFAULT_TERMS[0]
        state.state = {**(state.state or {}), "term_index": (idx + 1) % max(1, len(terms)),
                       "last_term": term}
        s.flush()
        return self.search(s, client, term, limit=limit)

    def search(self, s: Session, client: httpx.Client, query: str, *,
               limit: int = 50, since: str | None = None) -> list[ScrapedPost]:
        params: dict[str, Any] = {"q": query, "limit": min(100, max(1, limit)),
                                  "sort": "latest"}
        if since:
            params["since"] = since
        r = client.get(f"{API}/app.bsky.feed.searchPosts", params=params)
        r.raise_for_status()
        return self.parse_search(r.json())[:limit]

    def fetch_author(self, s: Session, client: httpx.Client, handle: str, *,
                     limit: int = 50) -> list[ScrapedPost]:
        r = client.get(f"{API}/app.bsky.feed.getAuthorFeed",
                       params={"actor": handle.lstrip("@"), "limit": min(100, limit),
                               "filter": "posts_with_media"})
        r.raise_for_status()
        return self.parse_feed(r.json())[:limit]

    def fetch_comments(self, s: Session, client: httpx.Client,
                       platform_post_id: str) -> list[dict]:
        r = client.get(f"{API}/app.bsky.feed.getPostThread",
                       params={"uri": platform_post_id, "depth": 2})
        r.raise_for_status()
        payload = r.json()
        author = (((payload.get("thread") or {}).get("post") or {})
                  .get("author") or {}).get("handle")
        return self.parse_thread(payload, author=author)

    def fetch_thread(self, s: Session, client: httpx.Client,
                     platform_post_id: str) -> list[dict]:
        return [c for c in self.fetch_comments(s, client, platform_post_id)
                if c.get("is_creator")]

    def test_connection(self, s: Session) -> dict:
        try:
            with self.make_client(s) as client:
                r = client.get(f"{API}/app.bsky.feed.searchPosts",
                               params={"q": "ai art", "limit": 1})
            if r.status_code == 200:
                return {"ok": True, "detail": "Bluesky's public AppView is reachable "
                                              "(no login needed)."}
            return {"ok": False, "detail": f"Unexpected HTTP {r.status_code} from Bluesky."}
        except httpx.HTTPError as e:
            return {"ok": False, "detail": f"Can't reach Bluesky: {type(e).__name__}"}
