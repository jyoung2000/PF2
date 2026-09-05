"""Dedupe levels (D65): exact platform id (existing UNIQUE), sha256 of the
original bytes, 64-bit dHash near-duplicates. Everything links, nothing
deletes."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from ..models import PostLink, Post


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dhash(path: Path | str, size: int = 8) -> str | None:
    """Difference hash: grayscale → (size+1)×size → adjacent-pixel gradient
    bits → 64-bit hex. Robust to resize/recompression, sensitive to content."""
    try:
        with Image.open(path) as im:
            im = im.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
            px = list(im.getdata())
    except Exception:
        return None
    bits = 0
    for row in range(size):
        for col in range(size):
            left = px[row * (size + 1) + col]
            right = px[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def hamming(a: str | None, b: str | None) -> int:
    if not a or not b:
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def near_duplicates(s, phash: str | None, exclude_id: int | None = None,
                    max_distance: int = 6, limit: int = 20) -> list[tuple[int, int]]:
    """[(post_id, distance)] of stored posts within `max_distance` bits."""
    if not phash:
        return []
    stmt = select(Post.id, Post.phash).where(Post.phash.is_not(None))
    if exclude_id is not None:
        stmt = stmt.where(Post.id != exclude_id)
    found = []
    for pid, ph in s.execute(stmt):
        d = hamming(phash, ph)
        if d <= max_distance:
            found.append((pid, d))
    found.sort(key=lambda t: (t[1], t[0]))
    return found[:limit]


def exact_duplicates(s, content_hash: str | None, exclude_id: int | None = None) -> list[int]:
    if not content_hash:
        return []
    stmt = select(Post.id).where(Post.content_hash == content_hash)
    if exclude_id is not None:
        stmt = stmt.where(Post.id != exclude_id)
    return [r[0] for r in s.execute(stmt)]


def link_posts(s, a: int, b: int, kind: str, score: float | None = None) -> bool:
    """Symmetric, idempotent link. Returns True when newly created."""
    if a == b:
        return False
    exists = s.execute(select(PostLink.id).where(
        PostLink.post_id == a, PostLink.other_id == b, PostLink.kind == kind)).first()
    if exists:
        return False
    s.add(PostLink(post_id=a, other_id=b, kind=kind, score=score))
    s.add(PostLink(post_id=b, other_id=a, kind=kind, score=score))
    s.flush()
    return True


def links_for(s, post_id: int) -> list[dict]:
    rows = s.execute(select(PostLink).where(PostLink.post_id == post_id)
                     .order_by(PostLink.kind, PostLink.score.desc())).scalars().all()
    return [{"post_id": r.other_id, "kind": r.kind, "score": r.score} for r in rows]
