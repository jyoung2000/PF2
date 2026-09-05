"""Safe file placement under DATA_DIR/film (spec §28): ids are server-made,
stored paths are DATA_DIR-relative (`film/…`) and re-validated on every
read; nothing a client sends is ever used as a path component. Files are
served by the `/film-media` StaticFiles mount (which itself refuses to leave
its directory)."""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from ..config import get_config

IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
VIDEO_TYPES = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
AUDIO_TYPES = {"audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
               "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/aac": ".aac",
               "audio/flac": ".flac"}
_EXT_RE = re.compile(r"^\.[a-z0-9]{1,5}$")


class UnsafePath(ValueError):
    """Raised for any path that is absolute, escapes DATA_DIR/film, or
    contains traversal segments."""


def film_root() -> Path:
    return get_config().film_dir


def resolve(rel: str | None) -> Path:
    """DATA_DIR-relative path (must start with `film/`) → absolute path that is
    guaranteed to live inside the film directory."""
    if not rel or not isinstance(rel, str):
        raise UnsafePath(str(rel))
    if rel.startswith(("/", "\\")) or "\x00" in rel or "\\" in rel:
        raise UnsafePath(rel)
    parts = Path(rel).parts
    if len(parts) < 2 or parts[0] != "film" or any(p in ("..", ".", "") for p in parts):
        raise UnsafePath(rel)
    root = film_root().resolve()
    full = (get_config().data_dir / rel).resolve()
    if not full.is_relative_to(root):
        raise UnsafePath(rel)
    return full


def url_for(rel: str | None) -> str | None:
    """Public URL for a stored film file (None when nothing is stored)."""
    if not rel:
        return None
    try:
        resolve(rel)
    except UnsafePath:
        return None
    return "/film-media/" + "/".join(Path(rel).parts[1:])


def new_name(ext: str) -> str:
    ext = (ext or "").lower()
    if not _EXT_RE.match(ext):
        raise UnsafePath(f"bad extension {ext!r}")
    return uuid.uuid4().hex + ext


def asset_rel(asset_id: int, sub: str, name: str) -> str:
    return f"film/assets/{int(asset_id)}/{_sub(sub)}/{_name(name)}"


def project_rel(project_id: int, sub: str, name: str) -> str:
    return f"film/projects/{int(project_id)}/{_sub(sub)}/{_name(name)}"


def clip_rel(name: str) -> str:
    return f"film/clips/{_name(name)}"


def _sub(sub: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", sub or ""):
        raise UnsafePath(f"bad subdir {sub!r}")
    return sub


def _name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", name or "") or name.startswith("."):
        raise UnsafePath(f"bad file name {name!r}")
    return name


def write(rel: str, data: bytes) -> Path:
    full = resolve(rel)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return full


def remove(rel: str | None) -> None:
    if not rel:
        return
    try:
        resolve(rel).unlink(missing_ok=True)
    except (UnsafePath, OSError):
        pass


def ext_for(content_type: str | None, filename: str | None, allowed: dict) -> str | None:
    """Extension for an upload by content type, falling back to the file
    name's suffix when it maps to the same allowed set."""
    ext = allowed.get((content_type or "").split(";")[0].strip().lower())
    if ext:
        return ext
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    return suffix if suffix in set(allowed.values()) else None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
