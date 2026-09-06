"""Browser-tier social sources (Inspiration 2.0, I9): TikTok, Instagram,
Pinterest, Threads, Tumblr.

These platforms have no usable public JSON, so each is a `SocialBrowserAdapter`
described by CONFIGURATION — a search URL and the row shape its workflow must
produce — rather than bespoke scraping code. The crawl runs through Browser
Intelligence: a cached workflow replays deterministically, and AI is involved
only to discover or repair that workflow (I8), inside the domain allowlist and
the read-only policy.

Honesty rules (§190): none of these claims to work before a workflow exists.
Until one is discovered or written they report "Needs setup" with the exact
reason, and they never crash a run. Login is the user's own interactive
session (D56/D59) — PF2 never asks for a password and never bypasses a
challenge.
"""
from __future__ import annotations

from .base import ScrapedPost
from .social_base import SocialBrowserAdapter, ts

ROW_SCHEMA = {"fields": {"title": "string", "url": "string", "media": "string",
                         "author": "string", "text": "string"}, "many": True}


class _SocialSite(SocialBrowserAdapter):
    """Shared row → ScrapedPost mapping for the configured sites."""
    row_schema = ROW_SCHEMA
    media_type = "image"

    def rows_to_posts(self, rows: list[dict]) -> list[ScrapedPost]:
        out: list[ScrapedPost] = []
        for row in rows:
            media = (row.get("media") or "").strip()
            url = (row.get("url") or "").strip()
            if not media or not url:
                continue
            post_id = url.rstrip("/").rsplit("/", 1)[-1] or url
            out.append(self.build_post(
                platform=self.name, post_id=post_id, media_url=media,
                media_type=self.media_type,
                title=(row.get("title") or "").strip() or None,
                text=(row.get("text") or "").strip() or None,
                author=(row.get("author") or "").lstrip("@").strip() or None,
                source_url=url, posted_at=ts(row.get("posted_at")),
                media={"type": self.media_type, "url": media}))
        return out

    def needs_setup_reason(self, s):
        base = super().needs_setup_reason(s)
        if base:
            return base
        from ..browserintel import workflows as wf_store
        if wf_store.get_active(s, self.name, "search") is None:
            return (f"No browser workflow for {self.label} yet — open Sources → "
                    f"{self.label} → Learn workflow (needs an AI browser engine), "
                    "or add one by hand. Until then this source stays idle.")
        return None

    def is_configured(self, s) -> bool:
        from ..browserintel import workflows as wf_store
        if self.requires_auth and not self.storage_state_path().is_file():
            return False
        return wf_store.get_active(s, self.name, "search") is not None


class TikTokAdapter(_SocialSite):
    name = "tiktok"
    label = "TikTok"
    experimental = True
    requires_auth = False          # public search works logged-out, often gated
    media_type = "image"           # cover image; the video stays on TikTok
    start_url = "https://www.tiktok.com/search?q=ai%20video%20prompt"
    search_url = "https://www.tiktok.com/search?q={query}"
    search_setting = "tiktok_terms"
    default_terms = ["ai video prompt", "veo 3", "kling ai"]
    default_interval_minutes = 90
    capabilities = frozenset({"search", "media", "video", "browser_session",
                              "browser_required", "ai_discovery", "prompt"})
    extraction_policy = {"prompt_locations": ["caption", "comment"],
                         "comments_matter": True, "metadata_available": False,
                         "threads_matter": False}


class InstagramAdapter(_SocialSite):
    name = "instagram"
    label = "Instagram"
    experimental = True
    requires_auth = True           # explore/search needs a session
    start_url = "https://www.instagram.com/explore/tags/aiart/"
    search_url = "https://www.instagram.com/explore/tags/{query}/"
    search_setting = "instagram_tags"
    default_terms = ["aiart", "aivideo", "midjourney"]
    default_interval_minutes = 120
    capabilities = frozenset({"search", "media", "image", "video", "authenticated",
                              "browser_session", "browser_required", "ai_discovery",
                              "prompt"})
    extraction_policy = {"prompt_locations": ["caption"], "comments_matter": True,
                         "metadata_available": False, "threads_matter": False}


class PinterestAdapter(_SocialSite):
    name = "pinterest"
    label = "Pinterest"
    experimental = True
    requires_auth = False
    start_url = "https://www.pinterest.com/search/pins/?q=ai%20art%20prompt"
    search_url = "https://www.pinterest.com/search/pins/?q={query}"
    search_setting = "pinterest_terms"
    default_terms = ["ai art prompt", "midjourney prompt"]
    default_interval_minutes = 120
    capabilities = frozenset({"search", "media", "image", "browser_session",
                              "browser_required", "ai_discovery", "prompt"})
    extraction_policy = {"prompt_locations": ["caption", "description"],
                         "comments_matter": False, "metadata_available": False,
                         "threads_matter": False}


class ThreadsAdapter(_SocialSite):
    name = "threads"
    label = "Threads"
    experimental = True
    requires_auth = True
    start_url = "https://www.threads.net/search?q=ai%20video"
    search_url = "https://www.threads.net/search?q={query}"
    search_setting = "threads_terms"
    default_terms = ["ai video prompt", "flux prompt"]
    default_interval_minutes = 120
    capabilities = frozenset({"search", "media", "image", "video", "thread",
                              "authenticated", "browser_session", "browser_required",
                              "ai_discovery", "prompt"})
    extraction_policy = {"prompt_locations": ["caption", "thread"],
                         "comments_matter": True, "metadata_available": False,
                         "threads_matter": True}


class TumblrAdapter(_SocialSite):
    name = "tumblr"
    label = "Tumblr"
    experimental = True
    requires_auth = False
    start_url = "https://www.tumblr.com/search/ai%20art"
    search_url = "https://www.tumblr.com/search/{query}"
    search_setting = "tumblr_terms"
    default_terms = ["ai art", "aiartwork"]
    default_interval_minutes = 180
    capabilities = frozenset({"search", "media", "image", "browser_session",
                              "browser_required", "ai_discovery", "prompt"})
    extraction_policy = {"prompt_locations": ["caption"], "comments_matter": False,
                         "metadata_available": False, "threads_matter": False}


SITES = [TikTokAdapter, InstagramAdapter, PinterestAdapter, ThreadsAdapter, TumblrAdapter]
