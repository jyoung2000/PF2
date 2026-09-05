"""Enrichment stage (I4.1): only high-value candidates get the expensive
lookups — comments/thread (X), related items + author (Civitai) — through
the adapter's declared capabilities. Everything fetched is stored under
post.enrichment as OBSERVED data; a creator's own reply carrying a
"Prompt:" becomes an `extracted` prompt assertion (never overriding an
explicit one). Browser lookups take the scheduler's global lock (D22)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import session_scope
from ..logbus import bus
from ..models import Post
from ..scrapers import get_adapter
from . import provenance, queue, scoring

TECH_TERMS_RE = re.compile(
    r"\b(model|prompt|workflow|settings?|seed|lora|checkpoint|controlnet|camera|lighting|"
    r"generat(?:ed|ion)|video model|image model|upscal(?:e|ed|er)|negative prompt|sampler|"
    r"steps|cfg|comfy|midjourney|kling|veo|sora|runway|flux|sref|--ar|--v\b)", re.I)
MAX_COMMENTS = 25


def technical(text: str | None) -> bool:
    return bool(text and TECH_TERMS_RE.search(text))


def prioritize_comments(comments: list[dict], author_handle: str | None) -> list[dict]:
    """Author replies first, then technical comments by engagement, then the
    rest by engagement; capped."""
    handle = (author_handle or "").lstrip("@").lower()

    def key(c: dict):
        is_author = (c.get("author") or "").lstrip("@").lower() == handle and handle
        return (0 if is_author else 1, 0 if c.get("technical") else 1, -(c.get("likes") or 0))
    for c in comments:
        c["technical"] = technical(c.get("text"))
        c["by_author"] = bool(handle) and (c.get("author") or "").lstrip("@").lower() == handle
    return sorted(comments, key=key)[:MAX_COMMENTS]


def _apply_comment_evidence(post: Post, comments: list[dict]) -> None:
    """Creators often post the prompt/model in their own reply."""
    from .extract import extract_from_text
    assertions = dict(post.assertions or {})
    for c in comments:
        if not c.get("by_author") or not c.get("text"):
            continue
        ex = extract_from_text(c["text"])
        if ex["prompt"] and ex["prompt_method"] == "labelled":
            if provenance.assert_field(assertions, "prompt", ex["prompt"], "extracted", 0.88,
                                       f"author's reply in thread ({c.get('id')})"):
                post.prompt = ex["prompt"]
                post.prompt_source = "extracted"
        if ex["model_name"] and ex["model_stated"]:
            if provenance.assert_field(assertions, "model", ex["model_name"], "extracted", 0.85,
                                       f"author named the model in a reply ({c.get('id')})"):
                from ..aliases import normalize_model
                post.model_name = ex["model_name"]
                post.model_family = normalize_model(ex["model_name"])
                post.model_source = "explicit"
    post.assertions = assertions


def enrich_post(post_id: int | None, payload: dict) -> str:
    if post_id is None:
        return "skipped"
    with session_scope() as s:
        post = s.get(Post, post_id)
        if post is None:
            return "skipped"
        adapter = get_adapter(post.platform)
        if adapter is None:
            return "skipped"
        caps = set(getattr(adapter, "capabilities", ()))
        if not caps & {"comments", "thread", "related", "author", "detail"}:
            return "skipped"
        if not adapter.is_configured(s):
            return "skipped"
        platform, ppid, author = post.platform, post.platform_post_id, post.author
        client = adapter.make_client(s)
    lock = None
    if getattr(adapter, "tier", 1) == 2:
        try:
            from .. import scheduler
            lock = scheduler._run_lock
        except (ImportError, AttributeError):
            lock = None
    enrichment: dict = {"fetched_at": datetime.now(timezone.utc).isoformat(), "capabilities": sorted(caps)}
    try:
        if lock is not None:
            lock.acquire()
        with session_scope() as s:
            if "comments" in caps and hasattr(adapter, "fetch_comments"):
                raw = adapter.fetch_comments(s, client, ppid)
                enrichment["comments"] = prioritize_comments(list(raw or []), author)
                enrichment["comment_count"] = len(raw or [])
            if "thread" in caps and hasattr(adapter, "fetch_thread"):
                enrichment["thread"] = list(adapter.fetch_thread(s, client, ppid) or [])
            if "related" in caps and hasattr(adapter, "fetch_related"):
                related = list(adapter.fetch_related(s, client, ppid) or [])
                ids = [r.platform_post_id for r in related]
                known = {r[0] for r in s.execute(select(Post.platform_post_id).where(
                    Post.platform == platform, Post.platform_post_id.in_(ids)))} if ids else set()
                enrichment["related"] = [{"platform_post_id": r.platform_post_id,
                                          "media_url": r.media_url, "known": r.platform_post_id in known}
                                         for r in related[:40]]
            if "author" in caps and hasattr(adapter, "fetch_author") and author:
                info = adapter.fetch_author(s, client, author)
                if info:
                    enrichment["author"] = info
    finally:
        if lock is not None:
            lock.release()
        try:
            client.close()
        except Exception:
            pass
    with session_scope() as s:
        post = s.get(Post, post_id)
        if post is None:
            return "skipped"
        post.enrichment = {**(post.enrichment or {}), **enrichment}
        evidence = ([dict(t, by_author=True) for t in enrichment.get("thread") or []]
                    + list(enrichment.get("comments") or []))
        if evidence:
            _apply_comment_evidence(post, evidence)
        if enrichment.get("author"):
            observed = dict(post.observed or {})
            observed["author"] = {**(observed.get("author") or {}), **enrichment["author"]}
            post.observed = observed
            from ..pipeline.ingest import _upsert_creator
            from ..scrapers.base import ScrapedPost
            post.creator_id = _upsert_creator(s, ScrapedPost(
                platform=post.platform, platform_post_id=post.platform_post_id,
                media_url=post.media_url or "", author=post.author), observed)
        post.pipeline_state = "enriched"
        # re-score now that more is known; maybe it earns analysis
        from .. import settings_store
        weights = settings_store.get(s, "intel_weights") or {}
        near = len((post.analysis or {}).get("near_dup_ids") or [])
        score, breakdown = scoring.inspiration_score(post, weights, near_dups=near)
        post.inspiration_score = score
        analysis = dict(post.analysis or {})
        analysis["inspiration"] = breakdown
        post.analysis = analysis
        if score >= float(settings_store.get(s, "intel_analysis_threshold") or 70):
            queue.enqueue(s, post.id, "analysis", priority=score)
        bus.info("intel", f"enriched post {post.id} ({platform}): "
                          f"{enrichment.get('comment_count', 0)} comments, "
                          f"{len(enrichment.get('related') or [])} related")
    return "complete"


queue.register("enrich", enrich_post)
