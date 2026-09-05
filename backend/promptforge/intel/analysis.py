"""Budgeted AI analysis stage (I3.2) — the ONLY place scraped posts meet an
LLM, and only for high-value records via the central queue.

Classifies AI likelihood (5 levels), extracts a prompt ONLY when none is
resolved, infers a model ONLY when none is stated (marked inferred, lower
confidence), suggests techniques (whitelisted) and descriptors. Provenance
ranking (D66) guarantees AI output never overwrites explicit data; uncertain
posts are kept, never deleted."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .. import settings_store
from ..aliases import normalize_model
from ..db import session_scope
from ..knowledge import techniques
from ..llm import client as llm_client
from ..logbus import bus
from ..models import Post
from . import provenance, queue

AI_STATUSES = ("definitely_ai", "probably_ai", "uncertain", "probably_not_ai", "definitely_not_ai")

SYSTEM = (
    "You are the analysis stage of PromptForge, a self-hosted AI-art research "
    "library. You classify whether a social/gallery post shows AI-generated media, "
    "recover a generation prompt only when the post text contains one, and infer "
    "the generation model only from explicit clues (names, hashtags, tool "
    "signatures) — never from how the image 'looks'. Be conservative. Reply ONLY "
    "with valid JSON.")


def _context(post: Post) -> str:
    observed = post.observed or {}
    text = observed.get("text") or {}
    params = post.params or {}
    keys = sorted(k for k in params if not k.startswith("_") and k not in
                  ("engagement", "hashtags", "workflow", "grok"))
    model_src = provenance.source_of(post.assertions, "model")
    lines = [
        f"platform: {post.platform}", f"media: {post.media_type} "
        f"{post.media_width or '?'}x{post.media_height or '?'}"
        + (f" {post.duration_s:.1f}s" if post.duration_s else ""),
        f"engagement_total: {post.engagement_total or 0}",
        f"post_text: {(text.get('body') or '')[:900]}",
        f"hashtags: {' '.join(text.get('hashtags') or [])}",
        f"resolved_prompt: {(post.prompt or '')[:600]} "
        f"(source={provenance.source_of(post.assertions, 'prompt') or 'none'})",
        f"stated_model: {post.model_name or 'none'} (source={model_src or 'none'})",
        f"generation_params_present: {', '.join(keys) or 'none'}",
        f"techniques_detected: {', '.join(post.technique_tags or []) or 'none'}",
    ]
    return "\n".join(lines)


def _prompt_for(post: Post) -> str:
    need_prompt = not provenance.is_high_confidence(post.assertions, "prompt")
    need_model = provenance.source_of(post.assertions, "model") not in ("observed", "extracted", "metadata")
    return f"""{_context(post)}

Return JSON:
{{
 "ai_status": one of {list(AI_STATUSES)},
 "ai_confidence": 0.0-1.0,
 "ai_reason": "one short sentence citing the evidence",
 "prompt": {"the generation prompt if the post text literally contains one, else null" if need_prompt else "null (a prompt is already resolved)"},
 "prompt_confidence": 0.0-1.0,
 "model": {"model name if explicitly evidenced (hashtag, name, tool signature) else null" if need_model else "null (already stated)"},
 "model_confidence": 0.0-1.0,
 "model_reason": "why, or null",
 "techniques": [slugs from: {', '.join(techniques.all_slugs())}],
 "descriptors": {{"subject": "...", "style": "...", "camera": "...", "lighting": "...", "composition": "..."}}
}}"""


def _parse(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def analyze_post(post_id: int | None, payload: dict) -> str:
    """Queue handler for stage 'analysis'."""
    if post_id is None:
        return "skipped"
    with session_scope() as s:
        if not settings_store.get(s, "intel_ai_analysis_enabled"):
            return "skipped"
        post = s.get(Post, post_id)
        if post is None:
            return "skipped"
        try:
            client = llm_client.build_client(s)
            llm_client.check_budget(s, client)
        except llm_client.LLMNotConfigured:
            return "skipped"           # nothing to run with; not an error
        except llm_client.BudgetExceeded as e:
            raise queue.Deferred(str(e))
        user = _prompt_for(post)
    try:
        raw = llm_client.run_llm("inspiration-analysis", SYSTEM, user, max_tokens=700)
    except llm_client.BudgetExceeded as e:
        raise queue.Deferred(str(e))
    result = _parse(raw or "")
    if not result:
        raise RuntimeError("analysis reply was not JSON")
    with session_scope() as s:
        post = s.get(Post, post_id)
        if post is None:
            return "skipped"
        _apply(post, result, source=getattr(client, "name", "llm"))
    return "complete"


def _apply(post: Post, result: dict, source: str) -> None:
    assertions = dict(post.assertions or {})
    analysis = dict(post.analysis or {})
    status = result.get("ai_status")
    if status in AI_STATUSES:
        try:
            conf = max(0.0, min(1.0, float(result.get("ai_confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        post.ai_status, post.ai_confidence = status, conf
        analysis["ai"] = {"status": status, "confidence": conf,
                          "reason": str(result.get("ai_reason") or "")[:300],
                          "source": source, "at": datetime.now(timezone.utc).isoformat()}

    prompt = result.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        conf = float(result.get("prompt_confidence") or 0.5)
        if provenance.assert_field(assertions, "prompt", prompt.strip(), "ai", conf,
                                   f"extracted by {source} from post text"):
            post.prompt = prompt.strip()
            post.prompt_source = "ai"

    model = result.get("model")
    if isinstance(model, str) and model.strip():
        conf = float(result.get("model_confidence") or 0.5)
        if provenance.assert_field(assertions, "model", model.strip(), "ai", conf,
                                   str(result.get("model_reason") or f"inferred by {source}")):
            post.model_name = model.strip()
            post.model_family = normalize_model(model.strip())
            post.model_source = "ai"
            params = dict(post.params or {})
            params["model_inferred"] = True
            post.params = params

    allowed = set(techniques.all_slugs())
    tech = [t for t in (result.get("techniques") or []) if isinstance(t, str) and t in allowed]
    if tech:
        post.technique_tags = sorted(set((post.technique_tags or []) + tech))
        provenance.assert_field(assertions, "techniques_ai", tech, "ai", 0.6, f"suggested by {source}")
    desc = result.get("descriptors")
    if isinstance(desc, dict):
        analysis["descriptors"] = {k: str(v)[:200] for k, v in desc.items() if v}
    post.assertions = assertions
    post.analysis = analysis
    post.pipeline_state = "analyzed"
    bus.info("intel", f"analysis: post {post.id} → {post.ai_status} ({post.ai_confidence})")


queue.register("analysis", analyze_post)
