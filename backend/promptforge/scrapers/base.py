"""SourceAdapter interface (pluggable per-site adapters) + ScrapedPost.

Adding a new site = one new file implementing SourceAdapter, registered in
scrapers/__init__.py. Nothing else changes (pipeline/GUI/schema are generic).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from ..models import ScraperState

USER_AGENT = "PromptForge/1.0 (self-hosted prompt library)"


@dataclass
class ScrapedPost:
    platform: str
    platform_post_id: str
    media_url: str
    media_type: str = "image"          # best guess; corrected at download time
    prompt: str | None = None
    negative_prompt: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    params: dict = field(default_factory=dict)
    author: str | None = None
    source_url: str | None = None
    posted_at: datetime | None = None
    nsfw: bool = False
    # I1 layered envelope: everything the source actually SHOWED, structured —
    # {"identity": {...}, "author": {...}, "engagement": {...}, "text": {...},
    #  "media": {...}, "relations": {...}}. Optional; adapters fill what they have.
    observed: dict | None = None


class SourceAdapter(ABC):
    name: str = ""                 # slug, e.g. "civitai"
    label: str = ""                # display name
    tier: int = 1                  # 1 = plain HTTP, 2 = browser (crawl4ai)
    requires_auth: bool = False    # needs login session / API key to work at all
    experimental: bool = False
    default_interval_minutes: int = 15
    min_interval_minutes: int = 5
    # how the GUI "connects" this source: "session" (browser login),
    # "api_key" (paste-to-connect; see api_key_setting/api_key_url), "none"
    auth_kind: str = "none"
    api_key_setting: str | None = None
    api_key_url: str | None = None

    # -- configuration ------------------------------------------------------
    def is_configured(self, s: Session) -> bool:
        """False ⇒ GUI shows 'Needs setup' (never an error)."""
        return True

    def needs_setup_reason(self, s: Session) -> str | None:
        return None

    # -- lifecycle ----------------------------------------------------------
    def make_client(self, s: Session) -> httpx.Client:
        """One client per run; the SAME client downloads media (signed URLs)."""
        return httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=60,
            follow_redirects=True)

    @abstractmethod
    def fetch_recent(self, s: Session, client: httpx.Client,
                     limit: int = 100) -> list[ScrapedPost]:
        """Newest-first batch. Raise for a run-level failure (recorded on the
        adapter's state, never propagated beyond the run)."""

    # -- status -------------------------------------------------------------
    def get_state(self, s: Session) -> ScraperState:
        st = s.get(ScraperState, self.name)
        if st is None:
            st = ScraperState(
                name=self.name, enabled=not self.requires_auth,
                interval_minutes=self.default_interval_minutes, state={})
            s.add(st)
            s.flush()
        return st

    def health(self, s: Session) -> dict:
        st = self.get_state(s)
        if not self.is_configured(s):
            return {"status": "needs_setup",
                    "detail": self.needs_setup_reason(s) or "Not configured"}
        if st.last_status == "error":
            return {"status": "error", "detail": st.last_error or "Last run failed"}
        if self.experimental:
            return {"status": "experimental", "detail": "Best-effort adapter"}
        return {"status": "ok", "detail": None}
