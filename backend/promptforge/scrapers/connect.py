"""One-click in-app login for browser sites (X5): the server's own headless
Chromium is streamed into the Settings UI over a same-origin WebSocket (JPEG
frames out, mouse/keyboard/scroll/paste events in). The HUMAN does the entire
login themselves — this is the desktop capture_login.py flow with the display
moved into the browser, never automation of a login and never captcha/challenge
evasion (iron rule: if a challenge appears, the user answers it by hand).

Only the resulting Playwright storage_state (cookies/localStorage) is written —
to DATA_DIR/sessions/{site}.json, exactly what the Tier-2 adapters consume.
Keystrokes pass straight through to the page and are never logged or stored.

Playwright is lazy-imported (D5): without the browser stack the socket reports
a clean "use the Docker image / desktop capture" error. One connect session at
a time per platform; idle + hard timeouts; the browser always closes with the
socket. Login URLs can be overridden via PF_LOGIN_URL_<SITE> for stand-in
smoke tests (precedent: PF_CIVITAI_API_URL, D46/D50).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ..config import get_config
from ..logbus import bus
from .base import USER_AGENT

LOGIN_URLS = {
    "x": "https://x.com/login",
    "midjourney": "https://www.midjourney.com/explore",
    "tensorart": "https://tensor.art/",
    "seaart": "https://www.seaart.ai/",
    "pixai": "https://pixai.art/",
    # Grok Web (I5.3): a browser session on grok.com — clearly NOT the xAI API
    # key; stored like any other site session, powers nothing by itself yet
    "grok": "https://grok.com/",
}
# Cookie-name markers (substring match) that mean "logged in" on sites we
# know: the flow saves and finishes by itself.
KNOWN_LOGIN_MARKERS = {
    "x": ("auth_token",),
    "midjourney": ("Midjourney.AuthUserToken",),
    "grok": ("sso",),          # grok.com sets sso / sso-rw after sign-in
}
# Everywhere else, generic detection: after the user's FIRST input, a new
# cookie or localStorage key that looks like an auth artefact triggers a
# NON-final save — the window stays open in case the login isn't finished,
# and "Save session now" re-saves. Never fires on what the page set on load.
AUTH_NAME_RE = re.compile(
    r"auth|token|session|jwt|login|sid|uid|access|refresh|passport", re.I)
NOT_AUTH_RE = re.compile(
    r"csrf|xsrf|_ga|_gid|analytics|consent|cookieyes|__cf|cf_|_dd_|sentry", re.I)
INPUT_EVENTS = {"click", "text", "key", "scroll"}

VIEWPORT = {"width": 1280, "height": 800}
RECV_TIMEOUT = 0.5          # seconds between ticks while idle
FRAME_INTERVAL = 0.7        # min seconds between frames
IDLE_TIMEOUT = 300          # no client input for 5 min → give up
MAX_LIFETIME = 900          # 15 min hard cap per attempt
JPEG_QUALITY = 55

_active: set[str] = set()   # platforms with a connect session in flight


def login_url(platform: str) -> str | None:
    override = os.environ.get(f"PF_LOGIN_URL_{platform.upper()}")
    return override or LOGIN_URLS.get(platform)


class BrowserHandle:
    """What _launch returns — thin bundle so tests can inject fakes."""

    def __init__(self, page: Any, context: Any, closer: Any = None):
        self.page = page
        self.context = context
        self._closer = closer

    async def close(self) -> None:
        if self._closer is not None:
            try:
                await self._closer()
            except Exception:
                pass


async def _launch(platform: str) -> BrowserHandle:
    """Real Chromium via plain Playwright (present in the Docker image through
    the crawl4ai browser stack). Raises RuntimeError with guidance when the
    stack isn't installed."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "The browser stack isn't installed in this environment — in-app "
            "connect needs the Docker image (or pip install -r "
            "backend/requirements-browser.txt). Fallbacks: upload a session "
            "file, or run scripts/capture_login.py on your desktop.") from e
    pw = await async_playwright().start()
    try:
        # PF_CHROMIUM_PATH: optional escape hatch for hosts that ship their
        # own Chromium build (unset in the Docker image, which has the
        # matching Playwright browsers installed).
        exe = os.environ.get("PF_CHROMIUM_PATH") or None
        browser = await pw.chromium.launch(headless=True, executable_path=exe)
        context = await browser.new_context(
            viewport=VIEWPORT, user_agent=USER_AGENT)
        page = await context.new_page()
    except Exception:
        await pw.stop()
        raise

    async def closer() -> None:
        try:
            await browser.close()
        finally:
            await pw.stop()

    return BrowserHandle(page, context, closer)


def _clear_expired_flag(platform: str) -> None:
    """A freshly installed session voids any sticky 'expired' state."""
    from ..db import session_scope
    from . import get_adapter
    adapter = get_adapter(platform)
    if adapter is None:
        return
    with session_scope() as s:
        st = adapter.get_state(s)
        state = dict(st.state or {})
        if state.pop("session_expired", None) is not None:
            st.state = state


def save_storage_state_sync(platform: str, state: dict) -> None:
    cfg = get_config()
    cfg.sessions_dir.mkdir(parents=True, exist_ok=True)
    (cfg.sessions_dir / f"{platform}.json").write_text(json.dumps(state))
    _clear_expired_flag(platform)


async def _save_session(platform: str, context: Any) -> None:
    state = await context.storage_state()
    await asyncio.to_thread(save_storage_state_sync, platform, state)
    bus.info(f"scraper.{platform}", "login session saved from in-app connect")


def _known_login(platform: str, cookies: list[dict]) -> bool:
    markers = KNOWN_LOGIN_MARKERS.get(platform)
    if not markers:
        return False
    return any(c.get("value") and any(m in (c.get("name") or "") for m in markers)
               for c in cookies)


def _auth_like(name: str) -> bool:
    return bool(AUTH_NAME_RE.search(name)) and not NOT_AUTH_RE.search(name)


async def _storage_names(handle: BrowserHandle) -> set[str]:
    """Cookie names + localStorage keys of the current origin, prefixed so the
    two namespaces can't collide."""
    names: set[str] = set()
    try:
        for c in await handle.context.cookies():
            names.add("c:" + (c.get("name") or ""))
    except Exception:
        pass
    try:
        keys = await handle.page.evaluate("() => Object.keys(window.localStorage)")
        for k in keys or []:
            names.add("l:" + str(k))
    except Exception:
        pass
    return names


def _generic_login(baseline: set[str], current: set[str]) -> bool:
    return any(_auth_like(n[2:]) for n in current - baseline)


async def _finish(ws: WebSocket, platform: str, handle: BrowserHandle) -> None:
    await ws.send_json({"t": "status", "state": "saving",
                        "message": "Login detected — saving your session…"})
    await _save_session(platform, handle.context)
    await ws.send_json({"t": "saved", "final": True})


async def _handle_input(page: Any, msg: dict) -> bool:
    """Apply one client event to the page. Returns True for 'save' requests."""
    t = msg.get("t")
    if t == "click":
        await page.mouse.click(float(msg.get("x", 0)), float(msg.get("y", 0)))
    elif t == "text":
        text = str(msg.get("text", ""))
        if not text:
            return False
        if len(text) <= 3:
            # single keystrokes: real key events (login forms listen for them)
            await page.keyboard.type(text, delay=15)
        else:
            # paste: insert in one go
            await page.keyboard.insert_text(text)
    elif t == "key":
        key = str(msg.get("key", ""))
        if key:
            mods = [m for m, flag in (("Control", msg.get("ctrl")),
                                      ("Alt", msg.get("alt")),
                                      ("Shift", msg.get("shift")),
                                      ("Meta", msg.get("meta"))) if flag]
            await page.keyboard.press("+".join(mods + [key]))
    elif t == "scroll":
        await page.mouse.wheel(0, float(msg.get("dy", 0)))
    elif t == "save":
        return True
    return False


async def run_connect(ws: WebSocket, platform: str) -> None:
    """Drive one connect session over an accepted WebSocket."""
    url = login_url(platform)
    if url is None:
        await ws.send_json({"t": "error",
                            "message": f"'{platform}' has no in-app login."})
        await ws.close()
        return
    if platform in _active:
        await ws.send_json({"t": "error", "message":
                            "A connect window for this site is already open — "
                            "finish or close it first."})
        await ws.close()
        return

    _active.add(platform)
    handle: BrowserHandle | None = None
    try:
        await ws.send_json({"t": "status", "state": "launching",
                            "message": "Starting the server's browser…"})
        try:
            handle = await _launch(platform)
        except Exception as e:
            await ws.send_json({"t": "error", "message": str(e)})
            return
        try:
            await handle.page.goto(url, wait_until="domcontentloaded",
                                   timeout=45_000)
        except Exception as e:
            # keep streaming — the error page itself is informative
            bus.warn(f"scraper.{platform}", f"connect: page load issue: {e}")
        await ws.send_json({
            "t": "status", "state": "live",
            "message": "Log in below exactly as usual — this is your own "
                       "server's browser. If a verification step appears, "
                       "complete it yourself."})

        started = time.time()
        last_input = started
        last_frame = 0.0
        baseline: set[str] | None = None   # storage names at first user input
        auto_saved = False
        while True:
            now = time.time()
            if now - started > MAX_LIFETIME:
                await ws.send_json({"t": "error", "message":
                                    "Timed out — reopen the connect window "
                                    "to try again."})
                return
            if now - last_input > IDLE_TIMEOUT:
                await ws.send_json({"t": "error", "message":
                                    "Closed after 5 minutes of inactivity."})
                return

            save_requested = False
            idle_tick = False
            try:
                raw = await asyncio.wait_for(ws.receive_text(),
                                             timeout=RECV_TIMEOUT)
                last_input = time.time()
                try:
                    msg = json.loads(raw)
                except ValueError:
                    msg = {}
                if msg.get("t") == "cancel":
                    return
                if baseline is None and msg.get("t") in INPUT_EVENTS:
                    baseline = await _storage_names(handle)
                try:
                    save_requested = await _handle_input(handle.page, msg)
                except Exception as e:
                    bus.warn(f"scraper.{platform}", f"connect input error: {e}")
            except asyncio.TimeoutError:
                idle_tick = True

            if save_requested:
                await _finish(ws, platform, handle)
                return
            if idle_tick:
                # auto-detect only between input bursts, so every queued
                # keystroke lands before the session is captured
                if platform in KNOWN_LOGIN_MARKERS:
                    try:
                        cookies = await handle.context.cookies()
                    except Exception:
                        cookies = []
                    if _known_login(platform, cookies):
                        await _finish(ws, platform, handle)
                        return
                elif baseline is not None and not auto_saved:
                    if _generic_login(baseline, await _storage_names(handle)):
                        await _save_session(platform, handle.context)
                        auto_saved = True
                        await ws.send_json({
                            "t": "saved", "final": False,
                            "message": "Login detected — session saved ✓. "
                                       "Not finished? Keep going, then hit "
                                       "Save session now to re-save."})

            if time.time() - last_frame >= FRAME_INTERVAL:
                try:
                    frame = await handle.page.screenshot(
                        type="jpeg", quality=JPEG_QUALITY)
                    await ws.send_bytes(frame)
                    last_frame = time.time()
                except Exception:
                    pass
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        pass
    finally:
        _active.discard(platform)
        if handle is not None:
            await handle.close()
        try:
            await ws.close()
        except Exception:
            pass
