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
MAX_COMMENTS = 25          # default; settings `research_max_comments` wins


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
    from .. import settings_store
    from ..db import session_scope as _scope
    try:
        with _scope() as s:
            cap = int(settings_store.get(s, "research_max_comments") or MAX_COMMENTS)
    except Exception:  # noqa: BLE001 — budgeting must never break enrichment
        cap = MAX_COMMENTS
    return sorted(comments, key=key)[:max(1, cap)]


def _apply_comment_evidence(post: Post, comments: list[dict]) -> None:
    """Creators often publish the prompt in their own reply — and sometimes
    split it across several (§22/§76). The shared parser assembles those
    fragments; provenance decides whether the result may replace what we
    already have (§122), and every fragment is kept as evidence (§52)."""
    from . import prompt_parser
    from ..aliases import normalize_model

    caption = ((post.observed or {}).get("text") or {}).get("body") or post.prompt
    replies = [{"id": c.get("id"), "text": c.get("text"), "author": c.get("author"),
                "url": c.get("url"), "is_creator": bool(c.get("by_author")),
                "score": c.get("likes")}
               for c in comments if c.get("text")]
    if not replies:
        return
    parsed = prompt_parser.parse_thread(caption, replies, platform=post.platform,
                                        creator=post.author)
    assertions = dict(post.assertions or {})
    params = dict(post.params or {})

    creator_frags = [f for f in parsed.fragments
                     if f.author_is_creator and f.source.startswith("explicit")]
    if parsed.prompt and creator_frags:
        current = params.get("prompt_source") or post.prompt_source
        rank = prompt_parser.coarse_source(parsed.prompt_source) or "extracted"
        refs = [f.ref for f in creator_frags if f.ref]
        if len(creator_frags) > 1:
            evidence = (f"assembled from {len(creator_frags)} published fragments "
                        "in the author's reply thread")
        else:
            evidence = ("published by the creator in the author's reply "
                        f"({parsed.prompt_source.replace('_', ' ')})")
        if refs:
            evidence += " [" + ", ".join(str(r) for r in refs[:4]) + "]"
        # The ladder (§122) decides whether this MAY replace what we have; the
        # provenance ranks (D66) decide whether it actually does. A candidate
        # that loses either check is still kept as evidence, never dropped.
        may_promote = prompt_parser.stronger_source(parsed.prompt_source, current) or (
            parsed.prompt_source == "assembled" and parsed.prompt != post.prompt)
        won = may_promote and provenance.assert_field(
            assertions, "prompt", parsed.prompt, rank, parsed.confidence, evidence)
        if won:
            post.prompt = parsed.prompt
            post.prompt_source = parsed.prompt_source
            params["prompt_source"] = parsed.prompt_source
            params["prompt_fragments"] = [f.as_dict() for f in parsed.fragments]
            if parsed.notes:
                params["prompt_notes"] = parsed.notes
        else:
            provenance.record_alternate(assertions, "prompt", parsed.prompt, rank,
                                        parsed.confidence, evidence)
            params.setdefault("prompt_fragments", [f.as_dict() for f in parsed.fragments])
    if parsed.negative and not post.negative_prompt:
        if provenance.assert_field(assertions, "negative_prompt", parsed.negative,
                                   "extracted", 0.85, "negative prompt in the creator's reply"):
            post.negative_prompt = parsed.negative
    if parsed.model_name and parsed.model_stated:
        if provenance.assert_field(assertions, "model", parsed.model_name, "extracted", 0.85,
                                   "the model was named in the thread"):
            post.model_name = parsed.model_name
            post.model_family = normalize_model(parsed.model_name)
            post.model_source = "explicit"
    for key, value in (parsed.params or {}).items():
        params.setdefault(key, value)
    post.params = params
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
