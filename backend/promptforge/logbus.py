"""In-memory log bus: scraper/generation events → ring buffer + live WebSocket
subscribers. Publishers may run in worker threads; delivery hops onto the app's
asyncio loop via call_soon_threadsafe."""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field


@dataclass
class LogEvent:
    ts: float
    source: str      # e.g. "scraper.civitai", "generation", "system"
    level: str       # info | warn | error
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


class LogBus:
    def __init__(self, history_size: int = 500):
        self._history: deque[LogEvent] = deque(maxlen=history_size)
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def log(self, source: str, message: str, level: str = "info") -> LogEvent:
        ev = LogEvent(ts=time.time(), source=source, level=level, message=message)
        with self._lock:
            self._history.append(ev)
            subs = list(self._subscribers)
            loop = self._loop
        if loop is not None and not loop.is_closed():
            def _deliver():
                for q in subs:
                    if not q.full():
                        q.put_nowait(ev)
            try:
                loop.call_soon_threadsafe(_deliver)
            except RuntimeError:
                pass
        return ev

    def info(self, source: str, message: str) -> None:
        self.log(source, message, "info")

    def warn(self, source: str, message: str) -> None:
        self.log(source, message, "warn")

    def error(self, source: str, message: str) -> None:
        self.log(source, message, "error")

    def history(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in list(self._history)[-limit:]]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)


bus = LogBus()
