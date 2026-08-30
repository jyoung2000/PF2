"""Companion hub (9.1, D25, D30): holds the ONE live desktop connection,
correlates request/response over the WebSocket, exposes a sync bridge for the
LLM client, and drains the offline job queue on reconnect."""
from __future__ import annotations

import asyncio
import itertools
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import session_scope
from ..logbus import bus
from ..models import Companion, LlmJob


class CompanionOffline(Exception):
    pass


class CompanionHub:
    def __init__(self):
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._companion_id: int | None = None
        self._name: str | None = None
        self._models: list[str] = []
        self._futures: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    # -- connection lifecycle (called from the WS endpoint) ------------------
    def register(self, ws, companion_id: int, name: str,
                 loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._ws = ws
            self._loop = loop
            self._companion_id = companion_id
            self._name = name
            self._models = []
        bus.info("companion", f"“{name}” connected")

    def set_models(self, models: list[str]) -> None:
        self._models = [str(m) for m in models][:100]

    def unregister(self, ws) -> None:
        with self._lock:
            if self._ws is ws:
                self._ws = None
                self._companion_id = None
                for fut in self._futures.values():
                    if not fut.done():
                        fut.set_exception(CompanionOffline("companion went offline"))
                self._futures.clear()
                name = self._name
                bus.warn("companion", f"“{name}” disconnected")

    def handle_message(self, data: dict) -> None:
        """Called from the WS receive loop (event loop thread)."""
        msg_type = data.get("t")
        if msg_type == "hello":
            self.set_models(data.get("ollama_models") or [])
            self._touch()
        elif msg_type in ("result", "chunk"):
            fut = self._futures.get(str(data.get("id")))
            if fut is not None and msg_type == "result" and not fut.done():
                if data.get("ok"):
                    fut.set_result(data.get("data"))
                else:
                    fut.set_exception(
                        RuntimeError(str(data.get("error") or "companion error")))
        elif msg_type == "pong":
            self._touch()

    def _touch(self) -> None:
        if self._companion_id is None:
            return
        try:
            with session_scope() as s:
                row = s.get(Companion, self._companion_id)
                if row is not None:
                    row.last_seen = datetime.now(timezone.utc)
        except Exception:
            pass

    # -- status --------------------------------------------------------------
    @property
    def online(self) -> bool:
        return self._ws is not None

    def status(self) -> dict:
        queued = 0
        try:
            with session_scope() as s:
                queued = len(s.execute(select(LlmJob.id).where(
                    LlmJob.status == "queued")).all())
        except Exception:
            pass
        return {"online": self.online, "name": self._name,
                "models": self._models, "queued_jobs": queued}

    # -- request bridge ------------------------------------------------------
    async def request(self, method: str, payload: dict,
                      timeout: float = 300) -> dict:
        with self._lock:
            ws = self._ws
            loop = self._loop
        if ws is None or loop is None:
            raise CompanionOffline("companion is offline")
        req_id = str(next(self._ids))
        fut: asyncio.Future = loop.create_future()
        self._futures[req_id] = fut
        try:
            await ws.send_json({"t": "request", "id": req_id,
                                "method": method, "payload": payload})
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._futures.pop(req_id, None)

    def request_sync(self, method: str, payload: dict,
                     timeout: float = 300) -> dict:
        """Blocking bridge for sync code (LLM client, worker threads)."""
        with self._lock:
            loop = self._loop
        if not self.online or loop is None:
            raise CompanionOffline("companion is offline")
        future = asyncio.run_coroutine_threadsafe(
            self.request(method, payload, timeout), loop)
        return future.result(timeout=timeout + 5)

    def kick(self, companion_id: int) -> None:
        """Close the live socket after a revoke."""
        with self._lock:
            ws = self._ws
            loop = self._loop
            match = self._companion_id == companion_id
        if match and ws is not None and loop is not None:
            asyncio.run_coroutine_threadsafe(ws.close(code=4001), loop)


hub = CompanionHub()


def drain_job_queue() -> int:
    """Scheduler tick (D30/D49): while the companion (or any provider) can
    serve LLM calls again, queued analysis jobs are satisfied by re-running the
    idempotent learning pass, then marked done."""
    from .. import settings_store
    with session_scope() as s:
        queued = s.execute(select(LlmJob).where(
            LlmJob.status == "queued")).scalars().all()
        if not queued:
            return 0
        provider = settings_store.get(s, "llm_provider")
        fallback = settings_store.get(s, "llm_cloud_fallback")
    if provider == "companion" and not hub.online:
        if not fallback:
            return 0
        # cloud fallback: temporarily unavailable companion → jobs run on cloud
    from ..knowledge import engine as kengine
    try:
        kengine.scheduled_learning_pass()
    except Exception as e:
        bus.error("companion", f"queued-job drain failed: {e}")
        return 0
    with session_scope() as s:
        rows = s.execute(select(LlmJob).where(
            LlmJob.status == "queued")).scalars().all()
        for job in rows:
            job.status = "done"
            job.result = {"drained": True}
        count = len(rows)
    if count:
        bus.info("companion", f"drained {count} queued analysis job(s)")
    return count
