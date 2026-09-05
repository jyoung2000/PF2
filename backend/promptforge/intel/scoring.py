"""Deterministic scoring (D64).

Candidate Score — computed BEFORE any download from what discovery showed;
gates enrichment/download so bandwidth goes to posts worth having.
Inspiration Value Score — computed after ingest from the stored record;
ranks the library and gates LLM analysis. Both expose their breakdown and
take weight overrides from settings `intel_weights`."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from ..aliases import DISPLAY_NAMES

DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "candidate": {
        "relevance": 1.5, "recency": 1.0, "engagement": 1.2, "ai_likelihood": 1.5,
        "media": 1.0, "prompt": 1.5, "metadata": 1.0, "source_quality": 0.8,
        "author_quality": 0.6, "model_relevance": 0.8, "novelty": 0.8,
    },
    "inspiration": {
        "visual_quality": 1.2, "prompt_quality": 1.5, "technical_detail": 1.2,
        "novelty": 1.0, "engagement": 1.0, "model_relevance": 0.8,
        "metadata_richness": 0.8,
    },
}

# platforms that are AI-only by construction vs. general social feeds
AI_NATIVE_PLATFORMS = {"civitai", "lexica", "midjourney", "tensorart", "seaart", "pixai"}
SOURCE_PRIOR = {"civitai": 0.9, "lexica": 0.7, "midjourney": 0.85, "tensorart": 0.7,
                "seaart": 0.6, "pixai": 0.6, "x": 0.6}
AI_TERMS = ("#aiart", "aiart", "ai art", "ai video", "aivideo", "midjourney",
            "stable diffusion", "sdxl", "flux", "sora", "veo", "kling", "runway",
            "comfyui", "prompt", "seedance", "seedream", "hailuo", "luma",
            "pika", "nano banana", "imagen", "dall-e", "dalle", "lora",
            "checkpoint", "txt2img", "img2img", "img2vid", "genai",
            "generated with", "text to video", "text-to-video", "wan2", "wan 2")
_ENGAGEMENT_KEYS = ("likes", "comments", "replies", "reposts", "quotes",
                    "shares", "bookmarks")
_NOISE_PARAM_KEYS = {"engagement", "hashtags", "prompt_confidence", "model_stated",
                     "media_index", "_is_reply", "size", "grok", "workflow"}


def get_weights(kind: str, overrides: dict | None = None) -> dict[str, float]:
    base = dict(DEFAULT_WEIGHTS[kind])
    for k, v in ((overrides or {}).get(kind) or {}).items():
        if k in base:
            try:
                base[k] = max(0.0, float(v))
            except (TypeError, ValueError):
                pass
    return base


def _clip(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _weighted(components: dict[str, float], weights: dict[str, float]) -> tuple[float, dict]:
    total_w = sum(weights.get(k, 0) for k in components) or 1.0
    score = sum(components[k] * weights.get(k, 0) for k in components) / total_w * 100
    breakdown = {k: {"value": round(components[k], 3), "weight": weights.get(k, 0),
                     "contribution": round(components[k] * weights.get(k, 0) / total_w * 100, 1)}
                 for k in components}
    return round(score, 1), breakdown


def engagement_total(engagement: dict | None) -> int | None:
    if not engagement:
        return None
    vals = []
    for k in _ENGAGEMENT_KEYS:
        v = engagement.get(k)
        if isinstance(v, (int, float)):
            vals.append(int(v))
    return sum(vals) if vals else None


def _engagement_component(total: int | None) -> float:
    if not total:
        return 0.0
    return _clip(math.log10(total + 1) / 4)   # 10k → 1.0


def _recency_component(posted_at: datetime | None, now: datetime | None = None) -> float:
    if posted_at is None:
        return 0.5
    now = now or datetime.now(timezone.utc)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - posted_at).total_seconds() / 86400)
    if days < 1:
        return 1.0
    if days < 7:
        return 0.8
    if days < 30:
        return 0.5
    if days < 180:
        return 0.3
    return 0.15


def _model_relevance(family: str | None, model_name: str | None,
                     known_families: set[str] | None = None) -> float:
    known = known_families or set(DISPLAY_NAMES)
    if family and family in known:
        return 1.0
    if family or model_name:
        return 0.6
    return 0.3


def _text_hits(text: str) -> int:
    low = text.lower()
    return sum(1 for t in AI_TERMS if t in low)


# ----------------------------------------------------------- candidate ----
def candidate_components(sp: Any, *, now: datetime | None = None,
                         known_families: set[str] | None = None,
                         recent_prompt_hashes: set[int] | None = None) -> dict[str, float]:
    params = sp.params or {}
    observed = sp.observed or {}
    text_parts = [sp.prompt or "", " ".join(params.get("hashtags") or []),
                  (observed.get("text") or {}).get("body") or ""]
    text = " ".join(t for t in text_parts if t)
    hits = _text_hits(text)
    ai_native = sp.platform in AI_NATIVE_PLATFORMS
    conf = params.get("prompt_confidence")
    prompt_ok = bool(sp.prompt) and conf != "low"

    if ai_native:
        relevance = 0.9
    elif hits:
        relevance = _clip(0.4 + 0.2 * hits)
    else:
        relevance = 0.7 if (sp.prompt or sp.model_name) else 0.3

    if ai_native:
        ai_like = 0.95
    else:
        ai_like = _clip(0.3 + (0.25 if sp.model_name else 0) + (0.2 if prompt_ok else 0)
                        + (0.15 if hits else 0) + (0.1 if params.get("workflow") else 0))

    engagement = observed.get("engagement") or params.get("engagement") or {}
    author = observed.get("author") or {}
    followers = author.get("followers")
    if isinstance(followers, (int, float)) and followers > 0:
        author_q = _clip(math.log10(followers + 1) / 6)
    elif author.get("verified"):
        author_q = 0.7
    else:
        author_q = 0.4

    meta_keys = [k for k in params if not k.startswith("_") and k not in _NOISE_PARAM_KEYS]
    prompt_hash = hash(sp.prompt.strip().lower()) if sp.prompt else None
    if prompt_hash is None:
        novelty = 0.6
    elif recent_prompt_hashes and prompt_hash in recent_prompt_hashes:
        novelty = 0.2
    else:
        novelty = 1.0

    from ..aliases import normalize_model
    family = normalize_model(sp.model_name) if sp.model_name else None
    return {
        "relevance": relevance,
        "recency": _recency_component(sp.posted_at, now),
        "engagement": _engagement_component(engagement_total(engagement)),
        "ai_likelihood": ai_like,
        "media": (1.0 if sp.media_type == "video" else 0.9) if sp.media_url else 0.0,
        "prompt": 1.0 if prompt_ok else (0.5 if sp.prompt else 0.0),
        "metadata": _clip(len(meta_keys) / 8),
        "source_quality": SOURCE_PRIOR.get(sp.platform, 0.5),
        "author_quality": author_q,
        "model_relevance": _model_relevance(family, sp.model_name, known_families),
        "novelty": novelty,
    }


def candidate_score(sp: Any, overrides: dict | None = None, **ctx) -> tuple[float, dict]:
    return _weighted(candidate_components(sp, **ctx), get_weights("candidate", overrides))


# --------------------------------------------------------- inspiration ----
def _prompt_quality(prompt: str | None, assertions: dict | None) -> float:
    if not prompt:
        return 0.0
    words = len(prompt.split())
    if words < 5:
        q = 0.3
    elif words < 15:
        q = 0.6
    elif words <= 60:
        q = 1.0
    else:
        q = 0.8
    # structure bonus: commas/sections/camera-lighting vocabulary
    low = prompt.lower()
    if any(w in low for w in ("lighting", "lens", "mm", "shot", "camera", "cinematic")):
        q = _clip(q + 0.1)
    a = (assertions or {}).get("prompt") or {}
    conf = float(a.get("confidence", 1.0))
    if a.get("source") == "ai":
        conf = min(conf, 0.6)
    return _clip(q * (0.5 + 0.5 * conf))


_TECH_KEYS = ("seed", "steps", "cfg_scale", "sampler", "scheduler", "size",
              "model", "lora", "loras", "controlnet", "vae", "workflow",
              "denoise", "upscale", "fps", "duration", "resolution")


def inspiration_components(post: Any, *, near_dups: int = 0,
                           known_families: set[str] | None = None) -> dict[str, float]:
    params = post.params or {}
    w, h = post.media_width or 0, post.media_height or 0
    mp = (w * h) / 1e6
    visual = _clip(0.8 * _clip(mp / 2.0) + (0.2 if post.media_type == "video" else 0.1))
    if post.media_type == "video" and (post.duration_s or 0) >= 3:
        visual = _clip(visual + 0.1)

    tech_hits = sum(1 for k in _TECH_KEYS if params.get(k) not in (None, "", [], {}))
    technical = 1.0 if params.get("workflow") or getattr(post, "has_workflow", False) \
        else _clip(tech_hits / 6)

    observed = post.observed or {}
    engagement = observed.get("engagement") or params.get("engagement") or {}
    total = post.engagement_total if getattr(post, "engagement_total", None) is not None \
        else engagement_total(engagement)

    raw_meta = params.get("_raw_metadata") or {}
    richness = _clip((len(raw_meta) if isinstance(raw_meta, dict) else 1) / 4 + tech_hits / 8)

    return {
        "visual_quality": visual,
        "prompt_quality": _prompt_quality(post.prompt, post.assertions),
        "technical_detail": technical,
        "novelty": _clip(1.0 - 0.4 * near_dups),
        "engagement": _engagement_component(total),
        "model_relevance": _model_relevance(post.model_family, post.model_name, known_families),
        "metadata_richness": richness,
    }


def inspiration_score(post: Any, overrides: dict | None = None, **ctx) -> tuple[float, dict]:
    return _weighted(inspiration_components(post, **ctx), get_weights("inspiration", overrides))


def explain(breakdown: dict) -> list[dict]:
    """Sorted, UI-ready rows: strongest contribution first."""
    rows = [{"component": k, **v} for k, v in (breakdown or {}).items()]
    rows.sort(key=lambda r: -r.get("contribution", 0))
    return rows
