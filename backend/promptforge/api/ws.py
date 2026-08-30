"""WebSocket endpoints (3.7): live scraper/system log tail + generation
progress. Read-only, same-origin (D43)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..logbus import bus

router = APIRouter(tags=["ws"])


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
