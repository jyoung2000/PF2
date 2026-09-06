"""Artifact landing for non-image/video generation outputs (Phase 2).

The generation queue ingests images and video as library Posts. Audio, 3D
meshes and text results (transcripts, audio analysis) have no Post
representation, so they land here: a file under DATA_DIR/forge/artifacts
plus a record on the Generation row's params, keeping one lineage story.

Paths are server-generated and re-validated on read (same posture as
film/storage.py, D74) so a provider-supplied name can never escape the
directory.
"""
from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from ..config import get_config

SAFE_EXT = {
    ".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac",          # audio
    ".glb", ".gltf", ".obj", ".fbx", ".usdz", ".ply", ".zip",  # 3d
    ".txt", ".json", ".srt", ".vtt",                           # text
}
EXT_BY_KIND = {"audio": ".mp3", "3d": ".glb", "text": ".txt"}
MAX_BYTES = 512 * 1024 * 1024


def artifacts_dir() -> Path:
    d = get_config().data_dir / "forge" / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extension(url: str, kind: str) -> str:
    name = re.sub(r"[?#].*$", "", url or "")
    ext = Path(name).suffix.lower()
    if ext in SAFE_EXT:
        return ext
    guessed = mimetypes.guess_extension(mimetypes.guess_type(name)[0] or "") or ""
    return guessed if guessed in SAFE_EXT else EXT_BY_KIND.get(kind, ".bin")


def resolve(rel: str) -> Path:
    """DATA_DIR-relative 'forge/artifacts/…' → absolute, traversal-checked."""
    if not rel or not rel.startswith("forge/artifacts/") or ".." in rel:
        raise ValueError(f"not an artifact path: {rel!r}")
    root = (get_config().data_dir / "forge" / "artifacts").resolve()
    path = (get_config().data_dir / rel).resolve()
    if root not in path.parents and path.parent != root:
        raise ValueError(f"artifact path escapes the store: {rel!r}")
    return path


def store_download(client, url: str, kind: str, generation_id: int) -> dict:
    """Download a provider output into the artifact store.
    → {path, bytes, kind, url} with a DATA_DIR-relative path."""
    ext = _extension(url, kind)
    name = f"gen{generation_id}-{uuid.uuid4().hex[:8]}{ext}"
    dest = artifacts_dir() / name
    size = 0
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise ValueError(f"artifact exceeds {MAX_BYTES // (1024*1024)}MB")
                fh.write(chunk)
    return {"path": f"forge/artifacts/{name}", "bytes": size, "kind": kind,
            "source_url": url}


def store_text(text: str, kind: str, generation_id: int) -> dict:
    name = f"gen{generation_id}-{uuid.uuid4().hex[:8]}.txt"
    dest = artifacts_dir() / name
    dest.write_text(text)
    return {"path": f"forge/artifacts/{name}", "bytes": len(text.encode()),
            "kind": kind, "text": text[:4000]}
