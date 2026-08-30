"""Prompt Enhance (7.5): upscale any prompt with the model knowledge file,
the collection style profile and foundation.md. Returns before/after +
one-line "why" notes. Requires a configured LLM (409 upstream, D41)."""
from __future__ import annotations

import json
import re

from ..db import session_scope
from ..models import Collection
from . import files

SYSTEM = (
    "You are PromptForge's prompt enhancer. You rewrite AI image/video prompts "
    "to be materially better for a specific model, using the provided "
    "knowledge. Preserve the user's subject and intent exactly — never invent "
    "a different subject. Improve structure, specificity, camera/lighting "
    "language and model fit. Reply ONLY with valid JSON.")


def _foundation_digest(max_chars: int = 3200) -> str:
    path = files.foundation_path()
    if not path.exists():
        files.install_foundation()
    _fm, body = files.read_md(path)
    return body[:max_chars]


def _model_digest(family: str | None, max_chars: int = 2200) -> str:
    if not family:
        return ""
    path = files.model_file_path(family)
    if not path.exists():
        return ""
    _fm, body = files.read_md(path)
    keep = []
    for section in ("Profile", "Deterministic stats", "Prompting guidance",
                    "Failure patterns", "Learned notes"):
        content = files.get_section(body, section)
        if content:
            keep.append(f"### {section}\n{content}")
    return "\n".join(keep)[:max_chars]


def _style_digest(collection_id: int | None, max_chars: int = 1500) -> str:
    if not collection_id:
        return ""
    path = files.style_file_path(collection_id)
    if not path.exists():
        from . import engine
        engine.refresh_style_profile(collection_id, use_llm=False)
    if not path.exists():
        return ""
    _fm, body = files.read_md(path)
    return body[:max_chars]


def enhance_prompt(prompt: str, model_family: str | None = None,
                   collection_id: int | None = None) -> dict:
    """→ {before, enhanced, notes: [{change, why}]}. Raises LLMNotConfigured /
    LLMError upward for the API layer to translate."""
    from ..llm.client import run_llm

    collection_name = None
    if collection_id:
        with session_scope() as s:
            c = s.get(Collection, collection_id)
            collection_name = c.name if c else None

    user = f"""Target model family: {model_family or 'unspecified'}
{f'Target collection style: {collection_name}' if collection_name else ''}

## Foundation knowledge (excerpt)
{_foundation_digest()}

## Model knowledge
{_model_digest(model_family) or '(no model file yet — rely on foundation)'}

## Style profile
{_style_digest(collection_id) or '(none)'}

## Prompt to enhance
{prompt}

Rewrite the prompt for this model{' and style' if collection_name else ''}.
Reply with JSON:
{{
 "enhanced": "the improved prompt (text only, ready to paste)",
 "negative": "suggested negative prompt, or '' if this model ignores negatives",
 "notes": [{{"change": "what changed (3-8 words)", "why": "one line why"}}]
}}
Keep 2-6 notes, most important first."""

    raw = run_llm("enhance", SYSTEM, user, max_tokens=1200)
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return {"before": prompt, "enhanced": raw.strip(), "negative": "",
                "notes": [{"change": "rewritten", "why": "model returned free text"}]}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {"before": prompt, "enhanced": raw.strip(), "negative": "",
                "notes": []}
    notes = [n for n in (data.get("notes") or [])
             if isinstance(n, dict) and n.get("change")][:6]
    return {"before": prompt,
            "enhanced": str(data.get("enhanced") or "").strip() or prompt,
            "negative": str(data.get("negative") or "").strip(),
            "notes": notes}
