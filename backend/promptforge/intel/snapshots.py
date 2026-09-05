"""Optional sanitized raw-source snapshots (I4.3): captured API/GraphQL
payloads gzipped under DATA_DIR/snapshots/{platform}/ for parser debugging,
replay and regression fixtures. Secrets never land on disk — keys that look
like credentials are dropped recursively and bearer-like strings are
redacted. Off by default (settings `intel_snapshots`), capped per platform."""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_config

SECRET_KEY_RE = re.compile(r"auth|token|cookie|session|passw|secret|credential|api[_-]?key|bearer|csrf|x-client-transaction", re.I)
SECRET_VALUE_RE = re.compile(r"^(?:Bearer\s+)?[A-Za-z0-9_\-]{32,}$")
MAX_PER_PLATFORM = 50


def snapshots_dir(platform: str | None = None) -> Path:
    d = get_config().data_dir / "snapshots"
    return d / platform if platform else d


def sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items() if not SECRET_KEY_RE.search(str(k))}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, str) and SECRET_VALUE_RE.match(obj) and not obj.startswith("http"):
        return "[redacted]"
    return obj


def save_snapshot(platform: str, kind: str, payload: Any, meta: dict | None = None) -> Path:
    d = snapshots_dir(platform)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = d / f"{stamp}-{re.sub(r'[^a-z0-9_-]', '_', kind.lower())}.json.gz"
    body = {"platform": platform, "kind": kind, "captured_at": stamp,
            "meta": sanitize(meta or {}), "payload": sanitize(payload)}
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(body, fh)
    _prune(d)
    return path


def maybe_save(platform: str, kind: str, payload: Any, meta: dict | None = None) -> Path | None:
    """Honour the setting; never raise (snapshots are a debugging aid)."""
    try:
        from .. import settings_store
        from ..db import session_scope
        with session_scope() as s:
            enabled = bool(settings_store.get(s, "intel_snapshots"))
        if not enabled or payload in (None, [], {}):
            return None
        return save_snapshot(platform, kind, payload, meta)
    except Exception:
        return None


def _prune(d: Path) -> None:
    files = sorted(d.glob("*.json.gz"))
    for old in files[:-MAX_PER_PLATFORM]:
        try:
            old.unlink()
        except OSError:
            pass


def list_snapshots(platform: str | None = None) -> list[dict]:
    root = snapshots_dir()
    if not root.exists():
        return []
    out = []
    for path in sorted(root.glob("*/*.json.gz"), reverse=True):
        if platform and path.parent.name != platform:
            continue
        out.append({"platform": path.parent.name, "file": path.name,
                    "bytes": path.stat().st_size})
    return out


def load_snapshot(platform: str, file: str) -> dict | None:
    if "/" in file or ".." in file or not file.endswith(".json.gz"):
        return None
    path = snapshots_dir(platform) / file
    if not path.is_file():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)
