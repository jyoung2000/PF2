"""Deterministic workflow replay (Browser Intelligence Level 1).

Executes a validated action list (policy.ALLOWED_WORKFLOW_OPS) with plain
Playwright — no AI anywhere. This is what cached workflows run on every
scheduled crawl; Stagehand/Browser Use only ever get involved when there is
no workflow yet or replay stops matching the site.

Safety: every navigation goes through policy.check_url AND a request
interceptor aborts any document-load outside the allowlist, so neither a
redirect nor a page-initiated navigation can leave the fence. Sessions load
from the existing DATA_DIR/sessions/{platform}.json storage_state; nothing
from it is ever returned or logged.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from ..config import get_config
from . import policy

DEFAULT_TIMEOUT_MS = 20_000
MAX_ACTIONS = 40
MAX_ROWS = 400


class EngineUnavailable(RuntimeError):
    """Playwright isn't installed — callers degrade, never crash."""


def available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
        return True
    except ImportError:
        return False


def _chromium_path() -> str | None:
    return os.environ.get("PF_CHROMIUM_PATH") or None


def _substitute(value: str, params: dict) -> str:
    out = str(value)
    for key, v in (params or {}).items():
        out = out.replace("{%s}" % key, str(v))
    return out


async def _extract(page, action: dict) -> list[dict]:
    items_sel = action.get("items")
    fields: dict = action.get("fields") or {}
    rows: list[dict] = []
    handles = await page.query_selector_all(items_sel) if items_sel else [page]
    for h in handles[:MAX_ROWS]:
        row: dict[str, Any] = {}
        for name, spec in fields.items():
            spec = spec if isinstance(spec, dict) else {"selector": str(spec)}
            sel = spec.get("selector")
            attr = spec.get("attr", "text")
            try:
                target = await h.query_selector(sel) if sel else h
                if target is None:
                    row[name] = None
                elif attr == "text":
                    row[name] = ((await target.inner_text()) or "").strip() or None
                elif attr == "html":
                    row[name] = await target.inner_html()
                else:
                    row[name] = await target.get_attribute(attr)
            except Exception:
                row[name] = None
        if any(v not in (None, "") for v in row.values()):
            rows.append(row)
    return rows


async def run_actions_async(actions: list[dict], params: dict | None = None,
                            storage_state: str | None = None,
                            headless: bool = True) -> dict:
    """Execute a validated workflow. Returns {rows, pages, duration_s,
    final_url}. Raises on op failure (selector missing, nav blocked …) so the
    caller can record the failure and consider repair."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise EngineUnavailable(
            "Playwright isn't installed — the deterministic browser engine "
            "needs the browser stack (Docker image, or "
            "requirements-browser.txt)") from e
    params = params or {}
    domains = policy.allowed_domains()
    policy.check_workflow_actions(actions)
    rows: list[dict] = []
    visited: list[str] = []
    t0 = time.monotonic()
    pw = await async_playwright().start()
    browser = None
    try:
        browser = await pw.chromium.launch(headless=headless,
                                           executable_path=_chromium_path())
        context = await browser.new_context(
            storage_state=storage_state if storage_state and os.path.isfile(storage_state) else None,
            viewport={"width": 1400, "height": 1000})

        async def guard(route):
            req = route.request
            if req.resource_type == "document" and not policy.host_allowed(req.url, domains):
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", guard)
        page = await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        for action in actions[:MAX_ACTIONS]:
            op = action["op"]
            if op == "goto":
                url = _substitute(action["url"], params)
                policy.check_url(url, domains)
                await page.goto(url, wait_until=action.get("wait_until", "domcontentloaded"))
                visited.append(page.url)
            elif op == "fill":
                value = action.get("value")
                if value is None and action.get("value_from"):
                    value = params.get(action["value_from"], "")
                await page.fill(action["selector"], _substitute(str(value or ""), params))
            elif op == "press":
                await page.press(action.get("selector") or "body", action["key"])
            elif op == "click":
                await page.click(action["selector"])
            elif op == "wait":
                if action.get("selector"):
                    await page.wait_for_selector(action["selector"],
                                                 timeout=int(action.get("timeout_ms", DEFAULT_TIMEOUT_MS)))
                else:
                    await page.wait_for_timeout(min(5000, int(action.get("timeout_ms", 500))))
            elif op == "scroll":
                for _ in range(min(20, int(action.get("times", 3)))):
                    await page.mouse.wheel(0, int(action.get("by", 1200)))
                    await page.wait_for_timeout(int(action.get("pause_ms", 400)))
            elif op == "extract":
                rows.extend(await _extract(page, action))
        final_url = page.url
    finally:
        try:
            if browser is not None:
                await browser.close()
        finally:
            await pw.stop()
    return {"rows": rows[:MAX_ROWS], "pages": visited, "final_url": final_url,
            "duration_s": round(time.monotonic() - t0, 2)}


def run_actions(actions: list[dict], params: dict | None = None,
                storage_state: str | None = None, headless: bool = True) -> dict:
    """Sync wrapper (the scraper stack is sync; one event loop per run, like
    browser_base D48)."""
    return asyncio.run(run_actions_async(actions, params, storage_state, headless))


def session_path(platform: str) -> str | None:
    p = get_config().sessions_dir / f"{platform}.json"
    return str(p) if p.is_file() else None
