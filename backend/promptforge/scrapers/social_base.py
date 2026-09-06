"""Shared social-source machinery (Inspiration 2.0, I9; spec §14–§15, §77).

Two things live here:

1. `SocialAdapter` — the mixin every social source (HTTP or browser) uses for
   the things they all do identically: turning a post + its replies into a
   ScrapedPost through the shared prompt parser, declaring an extraction
   policy (where prompts usually live on this platform), and search-term
   handling. It is deliberately NOT a scraper of its own.

2. `SocialBrowserAdapter` — a `BrowserAdapter` whose crawl is driven by a
   cached Browser Intelligence workflow instead of hand-written selectors, so
   a new browser-only platform is configuration (start URLs + an extraction
   schema), not code. Deterministic replay first; AI discovery/repair only
   when the site changes and the user allows it (I8).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .. import settings_store
from ..intel import prompt_parser
from ..logbus import bus
from .base import ScrapedPost, SourceAdapter
from .browser_base import BrowserAdapter

# every capability a source may declare (§14). Adapters advertise only what
# they really do; scheduling, UI and enrichment never assume more.
ALL_CAPABILITIES = frozenset({
    "search", "author", "detail", "comments", "thread", "media", "related",
    "prompt", "metadata", "video", "image", "pagination", "authenticated",
    "public", "browser_session", "browser_required", "api", "ai_discovery",
})


class SocialAdapter:
    """Mixin: shared post normalisation for social platforms."""

    # where prompts usually live on this platform (§77) — drives enrichment
    # priorities and the "check the comments" behaviour
    extraction_policy: dict = {
        "prompt_locations": ["caption"],
        "comments_matter": False,
        "metadata_available": False,
        "threads_matter": False,
    }

    def search_terms(self, s: Session, setting_key: str, default: list[str]) -> list[str]:
        raw = settings_store.get(s, setting_key) or ""
        if isinstance(raw, list):
            terms = [str(t).strip() for t in raw if str(t).strip()]
        else:
            terms = [t.strip() for t in str(raw).split(",") if t.strip()]
        return terms or default

    def build_post(self, *, platform: str, post_id: str, media_url: str,
                   media_type: str = "image", text: str | None = None,
                   title: str | None = None, description: str | None = None,
                   author: str | None = None, author_meta: dict | None = None,
                   source_url: str | None = None, posted_at: datetime | None = None,
                   engagement: dict | None = None, replies: list[dict] | None = None,
                   structured: dict | None = None, nsfw: bool = False,
                   relations: dict | None = None, extra_params: dict | None = None,
                   media: dict | None = None) -> ScrapedPost:
        """One place where a social item becomes a ScrapedPost: the shared
        parser mines the text (+ the creator's own replies), and everything
        the source SHOWED lands in `observed` (the I1 envelope) while the
        parse result lands in params with its provenance."""
        parsed = prompt_parser.extract_prompt(
            {"title": title, "text": text, "description": description,
             "replies": replies, "structured": structured},
            {"platform": platform, "creator": author})
        params: dict[str, Any] = {
            "prompt_source": parsed.prompt_source,
            "prompt_confidence": "high" if parsed.is_explicit else "low",
            "model_stated": parsed.model_stated,
            **(parsed.params or {}),
        }
        if parsed.fragments:
            params["prompt_fragments"] = [f.as_dict() for f in parsed.fragments]
        if parsed.components:
            params["prompt_components"] = parsed.components
        if parsed.notes:
            params["prompt_notes"] = parsed.notes
        if parsed.wants_comments:
            params["wants_comments"] = True
        if parsed.hashtags:
            params["hashtags"] = parsed.hashtags
        if engagement:
            params["engagement"] = engagement
        if extra_params:
            params.update(extra_params)

        observed = {
            "identity": {"platform": platform, "platform_post_id": str(post_id),
                         "source_url": source_url, "source_type": "post"},
            "author": {"handle": author, **(author_meta or {})} if author else {},
            "engagement": engagement or {},
            "text": {"title": title, "body": text, "description": description,
                     "hashtags": parsed.hashtags},
            "media": media or {"type": media_type, "url": media_url},
            "relations": relations or {},
        }
        if replies:
            observed["relations"]["reply_count_seen"] = len(replies)
        return ScrapedPost(
            platform=platform, platform_post_id=str(post_id), media_url=media_url,
            media_type=media_type, prompt=parsed.prompt,
            negative_prompt=parsed.negative, model_name=parsed.model_name,
            params=params, author=author, source_url=source_url,
            posted_at=posted_at, nsfw=nsfw, observed=observed)


def ts(value: Any) -> datetime | None:
    """Epoch seconds / ISO-8601 → aware datetime (sources mix both)."""
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


class SocialBrowserAdapter(SocialAdapter, BrowserAdapter):
    """A browser social source described by configuration: search/author URL
    templates plus the extraction schema its workflow must satisfy.

    The crawl runs the cached workflow through Browser Intelligence, which
    replays it deterministically and only involves AI when it breaks (I8).
    Subclasses map the resulting rows onto ScrapedPosts in `rows_to_posts`."""

    tier = 2
    requires_auth = False
    search_url: str = ""          # e.g. "https://site.com/search?q={query}"
    author_url: str = ""
    row_schema: dict = {"fields": {"title": "string", "url": "string",
                                   "media": "string", "author": "string"},
                        "many": True}
    search_setting: str = ""      # settings key holding comma-separated terms
    default_terms: list[str] = ["ai video prompt"]

    def workflow_seed(self) -> list[dict] | None:
        """Optional hand-written starting workflow. When None, the first run
        needs AI discovery (or a workflow saved from the GUI)."""
        return None

    def rows_to_posts(self, rows: list[dict]) -> list[ScrapedPost]:
        raise NotImplementedError

    def fetch_recent(self, s: Session, client: httpx.Client,
                     limit: int = 100) -> list[ScrapedPost]:
        from .. import browserintel as bi
        from ..browserintel import workflows as wf_store
        terms = self.search_terms(s, self.search_setting, self.default_terms)
        state = self.get_state(s)
        idx = int((state.state or {}).get("term_index", 0))
        query = terms[idx % len(terms)] if terms else ""
        state.state = {**(state.state or {}), "term_index": (idx + 1) % max(1, len(terms))}
        s.flush()

        seed = self.workflow_seed()
        if seed is not None and wf_store.get_active(s, self.name, "search") is None:
            wf_store.save_version(s, self.name, "search", seed, "builtin",
                                  schema=self.row_schema,
                                  notes=f"search {self.label} for a research query")
        try:
            result = bi.run_workflow(self.name, "search", {"query": query})
        except bi.EngineUnavailable as e:
            bus.warn(f"scraper.{self.name}", str(e))
            return []
        return self.rows_to_posts(result.get("rows") or [])[:limit]


def capability_report(adapter: SourceAdapter) -> dict:
    """Truthful capability + how-it-works summary for the Sources UI (§189)."""
    caps = sorted(adapter.capabilities)
    if adapter.tier == 0:
        how = "Public API — no login, no browser"
    elif adapter.tier == 1:
        how = "Public web/JSON endpoints — no browser"
    else:
        how = "Browser" + (" (login required)" if adapter.requires_auth else " (login optional)")
    return {"capabilities": caps, "how_it_works": how, "tier": adapter.tier,
            "extraction_policy": getattr(adapter, "extraction_policy", {})}
