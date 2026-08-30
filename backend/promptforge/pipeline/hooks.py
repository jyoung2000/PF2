"""Post-ingest hooks: the knowledge engine and integrations register here at
app startup so the pipeline stays import-cycle-free. Each hook receives a post
id and must never raise out (failures are logged, ingest continues)."""
from __future__ import annotations

from typing import Callable

from ..logbus import bus

_hooks: list[tuple[str, Callable[[int], None]]] = []


def register(name: str, fn: Callable[[int], None]) -> None:
    _hooks[:] = [(n, f) for n, f in _hooks if n != name]
    _hooks.append((name, fn))


def clear() -> None:
    _hooks.clear()


def run_post_ingested(post_id: int) -> None:
    for name, fn in list(_hooks):
        try:
            fn(post_id)
        except Exception as e:  # hooks must never break ingest
            bus.error(f"hook.{name}", f"post {post_id}: {e}")
