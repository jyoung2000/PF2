"""WebSocket endpoints (3.7): live scraper/system log tail + generation
progress (read-only, same-origin, D43) + the in-app login connect stream
(X5 — interactive, so its origin is checked explicitly, D56)."""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..logbus import bus

router = APIRouter(tags=["ws"])


def _same_origin(ws: WebSocket) -> bool:
    """True when the Origin header is absent (non-browser client) or matches
    the Host the socket arrived on. Cross-site browser pages always send
    Origin, so this blocks drive-by pages from puppeting the login browser."""
    origin = ws.headers.get("origin")
    if not origin:
        return True
    return urlparse(origin).netloc == ws.headers.get("host")


@router.websocket("/api/ws/logs")
async def ws_logs(ws: WebSocket):
    await ws.accept()
    q = bus.subscribe()
    try:
        await ws.send_json({"type": "history", "events": bus.history(200)})
        while True:
            ev = await q.get()
            await ws.send_json({"type": "event", "event": ev.to_dict()})
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        pass
    finally:
        bus.unsubscribe(q)


@router.websocket("/api/ws/connect/{platform}")
async def ws_connect(ws: WebSocket, platform: str):
    """One-click in-app login (X5): streams the server's headless browser to
    the user and forwards their input back — see scrapers/connect.py."""
    if not _same_origin(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    from ..scrapers import connect
    await connect.run_connect(ws, platform)


@router.websocket("/api/ws/generation")
async def ws_generation(ws: WebSocket):
    """Generation queue progress: same bus, filtered to generation sources."""
    await ws.accept()
    q = bus.subscribe()
    try:
        history = [e for e in bus.history(200) if e["source"].startswith("generation")]
        await ws.send_json({"type": "history", "events": history})
        while True:
            ev = await q.get()
            if ev.source.startswith("generation"):
                await ws.send_json({"type": "event", "event": ev.to_dict()})
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        pass
    finally:
        bus.unsubscribe(q)
