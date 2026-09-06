"""Sanitized crawl diagnostics (Inspiration 2.0, spec §68, §202).

Failed browser jobs leave a small JSON record (and optionally a screenshot
path) under DATA_DIR/browserintel/diagnostics — everything passes
policy.sanitize first, secrets never land on disk, and the store is bounded.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_config
from . import policy

KEEP = 50


def _dir() -> Path:
    d = get_config().data_dir / "browserintel" / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def record(source: str, task: str, step: str, error: str,
           extra: dict | None = None, screenshot: bytes | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    name = f"{stamp}-{source}-{task}"[:80]
    d = _dir()
    payload = policy.sanitize({
        "source": source, "task": task, "step": step,
        "error": policy.sanitize_text(error)[:2000],
        "at": datetime.now(timezone.utc).isoformat(),
        **(extra or {}),
    })
    if screenshot:
        try:
            (d / f"{name}.png").write_bytes(screenshot)
            payload["screenshot"] = f"{name}.png"
        except OSError:
            pass
    (d / f"{name}.json").write_text(json.dumps(payload, indent=2, default=str))
    _prune(d)
    return name


def _prune(d: Path) -> None:
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP:]:
        old.unlink(missing_ok=True)
        old.with_suffix(".png").unlink(missing_ok=True)


def list_diagnostics(source: str | None = None, limit: int = 25) -> list[dict]:
    out = []
    for p in sorted(_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text())
        except (ValueError, OSError):
            continue
        if source and data.get("source") != source:
            continue
        data["file"] = p.name
        out.append(data)
        if len(out) >= limit:
            break
    return out


class Stopwatch:
    def __init__(self):
        self.t0 = time.monotonic()

    @property
    def seconds(self) -> float:
        return round(time.monotonic() - self.t0, 2)
