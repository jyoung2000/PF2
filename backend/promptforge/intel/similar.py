"""Similarity search (I6.3) on the existing store — no vector DB:
visual (64-bit dHash hamming), prompt (phrase-set Jaccard over FTS
candidates), technique overlap, best examples for a model, plus the
explicit dedupe links."""
from __future__ import annotations

from sqlalchemy import or_, select

from .. import fts
from ..knowledge import stats as kstats
from ..models import Post
from . import dedupe, prompt_parser, provenance


def visual(s, post: Post, limit: int = 24, max_distance: int = 14) -> list[dict]:
    found = dedupe.near_duplicates(s, post.phash, exclude_id=post.id, max_distance=max_distance, limit=limit)
    return [{"post_id": pid, "distance": d, "similarity": round(1 - d / 64, 3)} for pid, d in found]


def _phrases(prompt: str | None) -> set[str]:
    if not prompt:
        return set()
    words = {w for w in prompt.lower().split() if len(w) > 3 and w not in kstats.STOPWORDS}
    return set(kstats.extract_phrases(prompt)) | words


def prompt_similar(s, post: Post, limit: int = 24) -> list[dict]:
    mine = _phrases(post.prompt)
    if not mine:
        return []
    phrases = sorted((t for t in mine if " " in t), key=len, reverse=True)[:5]
    words = sorted((t for t in mine if " " not in t), key=len, reverse=True)[:6]
    terms = phrases + words
    candidates: dict[int, None] = {}
    for term in terms:
        for pid in fts.search_posts(s, term, limit=150):
            if pid != post.id:
                candidates[pid] = None
    if not candidates:
        return []
    rows = s.execute(select(Post.id, Post.prompt).where(Post.id.in_(list(candidates)))).all()
    scored = []
    for pid, prompt in rows:
        theirs = _phrases(prompt)
        if not theirs:
            continue
        j = len(mine & theirs) / len(mine | theirs)
        if j > 0:
            scored.append({"post_id": pid, "similarity": round(j, 3)})
    scored.sort(key=lambda r: (-r["similarity"], -r["post_id"]))
    return scored[:limit]


def technique_related(s, post: Post, limit: int = 24) -> list[dict]:
    tags = list(post.technique_tags or [])
    if not tags:
        return []
    stmt = select(Post.id, Post.technique_tags, Post.inspiration_score).where(
        Post.id != post.id, or_(*[Post.technique_tags.like(f'%"{t}"%') for t in tags]))
    scored = []
    for pid, their, score in s.execute(stmt):
        overlap = len(set(tags) & set(their or []))
        if overlap:
            scored.append({"post_id": pid, "shared": overlap,
                           "shared_techniques": sorted(set(tags) & set(their or [])),
                           "inspiration": score})
    scored.sort(key=lambda r: (-r["shared"], -(r["inspiration"] or 0), -r["post_id"]))
    return scored[:limit]


def best_for_model(s, family: str, limit: int = 24) -> list[int]:
    ai_sources = list(prompt_parser.FINE_BY_COARSE["ai"]) + ["ai"]
    stmt = (select(Post).where(Post.model_family == family, Post.prompt.is_not(None),
                               or_(Post.prompt_source.is_(None),
                                   Post.prompt_source.not_in(ai_sources)))
            .order_by(Post.inspiration_score.desc().nulls_last(), Post.id.desc()).limit(limit * 2))
    out = []
    for p in s.execute(stmt).scalars():
        if p.assertions and not provenance.is_high_confidence(p.assertions, "prompt"):
            continue
        out.append(p.id)
        if len(out) >= limit:
            break
    return out


def related(s, post: Post, limit: int = 12) -> dict:
    return {"visual": visual(s, post, limit), "prompt": prompt_similar(s, post, limit),
            "technique": technique_related(s, post, limit), "links": dedupe.links_for(s, post.id)}
