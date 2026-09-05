"""GUI-editable settings stored in the `settings` table.

Precedence: DB value > env default > code default (D23).
Secrets are write-only through the API: reads return a mask, writes with the
sentinel "__unchanged__" keep the stored value.
"""
from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy.orm import Session

from .models import Setting

UNCHANGED = "__unchanged__"

SECRET_KEYS = {
    "civitai_api_key", "anthropic_api_key", "openai_api_key",
    "fal_api_key", "replicate_api_token", "wavespeed_api_key",
    "baserow_token", "discord_bot_token", "grok_api_key",
}

# setting key -> env var that provides its default
ENV_MAP = {
    "civitai_api_key": "CIVITAI_API_KEY",
    "lexica_search_terms": "LEXICA_SEARCH_TERMS",
    "llm_provider": "PF_LLM_PROVIDER",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "anthropic_model": "ANTHROPIC_MODEL",
    "openai_base_url": "OPENAI_BASE_URL",
    "openai_api_key": "OPENAI_API_KEY",
    "openai_model": "OPENAI_MODEL",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "ollama_model": "OLLAMA_MODEL",
    "llm_daily_budget": "PF_LLM_DAILY_BUDGET",
    "fal_api_key": "FAL_API_KEY",
    "replicate_api_token": "REPLICATE_API_TOKEN",
    "wavespeed_api_key": "WAVESPEED_API_KEY",
    "baserow_url": "BASEROW_URL",
    "baserow_token": "BASEROW_TOKEN",
    "baserow_table_id": "BASEROW_TABLE_ID",
    "discord_bot_token": "DISCORD_BOT_TOKEN",
    "discord_channel_id": "DISCORD_CHANNEL_ID",
    "image_quality": "PF_IMAGE_QUALITY",
    "image_max_dim": "PF_IMAGE_MAX_DIM",
    "video_crf": "PF_VIDEO_CRF",
    "video_max_height": "PF_VIDEO_MAX_HEIGHT",
    "keep_originals": "PF_KEEP_ORIGINALS",
    "grok_api_key": "GROK_API_KEY",
}

DEFAULTS: dict[str, Any] = {
    "civitai_api_key": "",
    "civitai_keep_metaless": False,   # D27
    "lexica_search_terms": "cinematic portrait,isometric city,studio lighting",
    "llm_provider": "",               # anthropic | openai | ollama | companion | mock(tests)
    "anthropic_api_key": "",
    "anthropic_model": "claude-sonnet-5",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "ollama_base_url": "http://host.docker.internal:11434",
    "ollama_model": "llama3.1",
    "llm_daily_budget": 200,
    "llm_cloud_fallback": False,      # fall back to cloud when companion offline
    "fal_api_key": "",
    "replicate_api_token": "",
    "wavespeed_api_key": "",
    "baserow_url": "https://api.baserow.io",
    "baserow_token": "",
    "baserow_table_id": "",
    "baserow_auto_sync": False,
    "discord_bot_token": "",
    "discord_channel_id": "",
    "discord_rules": None,            # integrations/discord_rules.DEFAULT_RULES applied lazily
    "image_quality": 82,
    "image_max_dim": 2048,
    "video_crf": 27,
    "video_max_height": 1080,
    "keep_originals": False,
    "nsfw_default_show": False,       # D40
    # X.com source scope (Phase X1)
    "x_search_terms": "#midjourney, #AIart, #aivideo, #flux",
    "x_max_per_run": 40,
    "x_min_engagement": 0,
    "x_media_filter": "both",         # images | videos | both
    "x_skip_replies": True,
    # Monitoring defaults (Phase X2)
    "monitor_default_interval": 60,   # minutes
    "monitor_default_tag": "",
    # Grok / xAI (Phase X3)
    "grok_api_key": "",
    "grok_base_url": "https://api.x.ai/v1",
    "grok_model": "grok-3-mini",
    "grok_discover_enabled": True,
    "grok_curate_enabled": False,
    "grok_curate_daily_budget": 100,
    "grok_digest_enabled": False,
    "grok_digest_hours": 24,
    "grok_digest_to_discord": False,
    "model_aliases": {},              # user rules: {"substring": "family"}
    "auto_add_generated_to_collection": True,
    # --- Inspiration Intelligence (I1) ---
    "intel_weights": {},                # {"candidate": {...}, "inspiration": {...}} weight overrides
    "intel_min_candidate_score": 25,    # candidates below this are skipped BEFORE download
    "intel_enrich_threshold": 60,       # candidate score ≥ → ENRICH job (detail/author/comments)
    "intel_analysis_threshold": 70,     # inspiration score ≥ → ANALYSIS (LLM/VLM) job
    "intel_near_dup_distance": 6,       # dHash hamming ≤ → near-duplicate link
    "intel_snapshots": False,           # sanitized raw source snapshots (I4)
    "intel_queue_batch": 20,            # jobs per scheduler tick
    "intel_ai_analysis_enabled": True,  # LLM classification/extraction for high-value posts
    "knowledge_min_confidence": 0.7,    # assertions below this never enter canonical stats
    "knowledge_accept_ai": False,       # let AI-inferred prompt/model feed the knowledge files
}

_BOOL_KEYS = {k for k, v in DEFAULTS.items() if isinstance(v, bool)}
_INT_KEYS = {k for k, v in DEFAULTS.items() if isinstance(v, int) and not isinstance(v, bool)}


def _coerce(key: str, value: Any) -> Any:
    if value is None:
        return value
    if key in _BOOL_KEYS and isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if key in _INT_KEYS and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return DEFAULTS[key]
    return value


def get(s: Session, key: str, default: Any = None) -> Any:
    row = s.get(Setting, key)
    if row is not None:
        return _coerce(key, json.loads(row.value))
    env_var = ENV_MAP.get(key)
    if env_var and os.environ.get(env_var) not in (None, ""):
        return _coerce(key, os.environ[env_var])
    if key in DEFAULTS:
        return DEFAULTS[key]
    return default


def put(s: Session, key: str, value: Any) -> None:
    if key in SECRET_KEYS and value == UNCHANGED:
        return
    row = s.get(Setting, key)
    encoded = json.dumps(value)
    if row is None:
        s.add(Setting(key=key, value=encoded))
    else:
        row.value = encoded
    s.flush()


def put_many(s: Session, values: dict[str, Any]) -> None:
    for k, v in values.items():
        put(s, k, v)


def mask(value: str) -> str:
    if not value:
        return ""
    return "••••" + str(value)[-4:]


def all_masked(s: Session) -> dict[str, Any]:
    """Full merged settings dict with secrets masked — safe for the GUI."""
    out: dict[str, Any] = {}
    for key in DEFAULTS:
        val = get(s, key)
        if key in SECRET_KEYS:
            out[key] = mask(val)
        else:
            out[key] = val
    return out
