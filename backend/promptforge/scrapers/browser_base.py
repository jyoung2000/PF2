"""Shared machinery for Tier 2 (crawl4ai/Playwright) adapters (5.1).

- crawl4ai imported lazily: the app and test suite run without it (D5).
- Stealth on, one site at a time (scheduler lock, D22), Chromium alive only
  during the run.
- Response BODIES captured via a page.on("response") hook (D48); adapters
  implement `wants_response(url)` + `parse_captured(responses)` so parsing
  stays deterministic and unit-testable on fixtures.
- Auth via Playwright storage_state under DATA_DIR/sessions/{site}.json
  (scripts/capture_login.py exports it); missing/expired sessions surface as
  GUI status, never crashes (D47).
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from ..config import get_config
from ..logbus import bus
from .base import USER_AGENT, ScrapedPost, SourceAdapter

BACKOFF_BASE_MINUTES = 30
BACKOFF_MAX_MINUTES = 8 * 60


class CapturedResponse(dict):
    """{'url': str, 'json': Any}"""


class BrowserAdapter(SourceAdapter):
    tier = 2
    start_url: str = ""
    # infinite scroll style: "scan_full_page" (append-style galleries) or
    # "virtual" (feeds that recycle DOM nodes — Midjourney)
    scroll_mode: str = "scan_full_page"
    virtual_scroll_selector: str = "#pageScroll"
    scroll_count: int = 12
    page_timeout_ms: int = 90_000

    auth_kind = "session"

    # -- session handling ----------------------------------------------------
    def storage_state_path(self) -> Path:
        return get_config().sessions_dir / f"{self.name}.json"

    def session_status(self, s: Session) -> str:
        """valid | expired | missing — reported for every browser site, login
        optional ones included (the GUI labels those 'optional')."""
        path = self.storage_state_path()
        if not path.is_file():
            return "missing"
        st = self.get_state(s)
        if (st.state or {}).get("session_expired"):
            return "expired"
        return "valid"

    def is_configured(self, s: Session) -> bool:
        if self.requires_auth:
            return self.storage_state_path().is_file()
        return True

    def needs_setup_reason(self, s: Session) -> str | None:
        if self.requires_auth and not self.storage_state_path().is_file():
            return ("Login session missing — click Connect to log in right "
                    "here (or upload a scripts/capture_login.py export / copy "
                    f"it to data/sessions/{self.name}.json)")
        return None

    def health(self, s: Session) -> dict:
        base = super().health(s)
        if base["status"] in ("ok", "experimental") and self.requires_auth:
            if self.session_status(s) == "expired":
                return {"status": "error",
                        "detail": "Login session expired — click Reconnect "
                                  "(or re-run capture_login.py)"}
        return base

    # -- media client with session cookies (D47) -----------------------------
    def make_client(self, s: Session) -> httpx.Client:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Referer": self.start_url or None},
            timeout=90, follow_redirects=True)
        path = self.storage_state_path()
        if path.is_file():
            try:
                state = json.loads(path.read_text())
                for cookie in state.get("cookies", []):
                    client.cookies.set(
                        cookie.get("name", ""), cookie.get("value", ""),
                        domain=cookie.get("domain", ""),
                        path=cookie.get("path", "/"))
            except (ValueError, OSError):
                pass
        return client

    # -- capture contract ----------------------------------------------------
    def wants_response(self, url: str) -> bool:  # pragma: no cover - abstract-ish
        return False

    def parse_captured(self, responses: list[dict]) -> list[ScrapedPost]:
        raise NotImplementedError

    # -- backoff (429/503) ---------------------------------------------------
    def _in_backoff(self, s: Session) -> float | None:
        st = self.get_state(s)
        until = (st.state or {}).get("backoff_until", 0)
        if until and time.time() < until:
            return until - time.time()
        return None

    def _record_backoff(self, s: Session, status_code: int) -> None:
        st = self.get_state(s)
        state = dict(st.state or {})
        step = int(state.get("backoff_step", 0)) + 1
        minutes = min(BACKOFF_MAX_MINUTES, BACKOFF_BASE_MINUTES * (2 ** (step - 1)))
        state.update({"backoff_step": step,
                      "backoff_until": time.time() + minutes * 60})
        st.state = state
        s.flush()
        bus.warn(f"scraper.{self.name}",
                 f"got HTTP {status_code} — backing off {minutes} min")

    def _clear_backoff(self, s: Session) -> None:
        st = self.get_state(s)
        state = dict(st.state or {})
        if state.get("backoff_step") or state.get("backoff_until"):
            state.pop("backoff_step", None)
            state.pop("backoff_until", None)
            st.state = state
            s.flush()

    # -- the crawl -----------------------------------------------------------
    def fetch_recent(self, s: Session, client: httpx.Client,
                     limit: int = 100) -> list[ScrapedPost]:
        remaining = self._in_backoff(s)
        if remaining is not None:
            bus.warn(f"scraper.{self.name}",
                     f"in backoff for another {remaining/60:.0f} min — skipping")
            return []
        storage = self.storage_state_path()
        responses, page_status = self._run_crawl(
            storage_state=str(storage) if storage.is_file() else None)
        from ..intel import snapshots
        snapshots.maybe_save(self.name, "captured", responses, {"start_url": self.start_url})
        if page_status in (429, 503):
            self._record_backoff(s, page_status)
            return []
        if page_status in (401, 403) and self.requires_auth:
            st = self.get_state(s)
            st.state = {**(st.state or {}), "session_expired": True}
            s.flush()
            bus.warn(f"scraper.{self.name}",
                     "looks logged out — session marked expired")
            return []
        self._clear_backoff(s)
        posts = self.parse_captured(responses)
        if self.requires_auth and posts:
            st = self.get_state(s)
            state = dict(st.state or {})
            if state.pop("session_expired", None) is not None:
                st.state = state
                s.flush()
        return posts[:limit]

    def _run_crawl(self, storage_state: str | None) -> tuple[list[dict], int]:
        """Blocking wrapper around one crawl4ai arun(). Returns (captured
        responses, page HTTP status)."""
        return asyncio.run(self._crawl_async(storage_state))

    async def _crawl_async(self, storage_state: str | None) -> tuple[list[dict], int]:
        try:
            from crawl4ai import (AsyncWebCrawler, BrowserConfig, CacheMode,
                                  CrawlerRunConfig)
        except ImportError as e:
            raise RuntimeError(
                "crawl4ai isn't installed in this environment — browser "
                "adapters need the Docker image (or pip install -r "
                "backend/requirements-browser.txt && crawl4ai-setup)") from e

        captured: list[dict] = []
        wants = self.wants_response

        async def on_page_context_created(page, context=None, **kwargs):
            async def on_response(response):
                try:
                    if not wants(response.url):
                        return
                    ctype = (response.headers or {}).get("content-type", "")
                    if "json" not in ctype and not response.url.endswith(".json"):
                        return
                    body = await response.json()
                    captured.append({"url": response.url, "json": body})
                except Exception:
                    pass
            page.on("response", on_response)
            return page

        browser_cfg = BrowserConfig(
            headless=True, enable_stealth=True, user_agent=None,
            storage_state=storage_state, viewport_width=1400,
            viewport_height=1000)

        run_kwargs: dict[str, Any] = dict(
            cache_mode=CacheMode.BYPASS,
            capture_network_requests=True,
            page_timeout=self.page_timeout_ms,
            wait_until="networkidle",
        )
        if self.scroll_mode == "virtual":
            try:
                from crawl4ai import VirtualScrollConfig
                run_kwargs["virtual_scroll_config"] = VirtualScrollConfig(
                    container_selector=self.virtual_scroll_selector,
                    scroll_count=self.scroll_count,
                    scroll_by="container_height",
                    wait_after_scroll=0.6)
            except ImportError:
                run_kwargs["scan_full_page"] = True
        else:
            run_kwargs["scan_full_page"] = True
            run_kwargs["scroll_delay"] = 0.5

        run_cfg = CrawlerRunConfig(**run_kwargs)
        status = 0
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            crawler.crawler_strategy.set_hook(
                "on_page_context_created", on_page_context_created)
            result = await crawler.arun(self.start_url, config=run_cfg)
            status = getattr(result, "status_code", None) or (
                200 if getattr(result, "success", False) else 0)
        return captured, status


# ---------------------------------------------------------------- helpers ---
def walk_find_lists(payload: Any, predicate: Callable[[dict], bool],
                    max_depth: int = 8) -> list[dict]:
    """Recursively collect dicts matching predicate from arbitrarily nested
    API JSON — keeps parsers resilient to envelope changes."""
    found: list[dict] = []
    seen: set[int] = set()

    def _walk(node: Any, depth: int) -> None:
        if depth > max_depth or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, dict):
            if predicate(node):
                found.append(node)
                return
            for v in node.values():
                _walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                _walk(v, depth + 1)

    _walk(payload, 0)
    return found
