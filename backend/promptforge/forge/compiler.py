"""Prompt Compiler (spec §4): Raw idea → intent → requirements → structure →
model-specific optimization → parameter resolution → constraint check →
PromptPackage. Deterministic end to end; an optional LLM polish (the existing
budget-gated Enhance) can be layered on top and is clearly labelled when it
ran. Switching model recompiles the same intent — the idea is never lost."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..generation import pricing
from ..knowledge import stats as kstats
from . import catalog, intent as intent_mod, router

CAMERA_HINTS = {"image": "85mm lens, shallow depth of field",
                "video": "slow push in, stabilized camera"}
QUALITY_TAGS = ["masterpiece", "best quality", "highly detailed"]
DEFAULT_NEGATIVE = "blurry, low quality, watermark, deformed"


def structure_idea(intent: dict) -> dict:
    """Structured prompt representation: the subject is the brief minus the
    constraint phrases the intent parser consumed (best effort, still the
    user's words — never invented)."""
    text = intent.get("brief", "")
    subject = re.sub(intent_mod.DURATION_RE, "", text)
    subject = re.sub(intent_mod.RATIO_RE, "", subject)
    subject = re.sub(intent_mod.BUDGET_CAP_RE, "", subject)
    # constraint phrases the intent consumed leave the subject too: the
    # avoid-list is re-expressed per model, orientation words become params
    subject = re.sub(r"(?:,\s*)?\b(?:no|without|avoid|never)\s+(?:\w+[ -]?){1,3}\w", "", subject, flags=re.I)
    for rx, _v in intent_mod.RATIO_WORDS:
        subject = re.sub(rf"(?:,\s*)?{rx.pattern}", "", subject, count=1, flags=re.I)
    subject = re.sub(r"\s{2,}", " ", subject).strip(" ,.-")
    return {
        "subject": subject or text,
        "styles": intent.get("styles", []),
        "text_content": intent.get("text_content", []),
        "avoid": intent.get("avoid", []),
        "consistency": bool(intent.get("character_consistency")),
        "modality": intent.get("modality", "image"),
    }


def _knowledge_terms(family: str, limit: int = 4) -> list[str]:
    """Top learned terms from this installation's knowledge stats — real
    observations only, absent when the family has none."""
    try:
        data = kstats.load_stats(family)
        return [t for t, _ in kstats.top_terms(data, limit)]
    except Exception:
        return []


def optimize_for_model(structure: dict, family: str) -> dict:
    """Model-specific optimization from catalog prompt recommendations —
    tag-style vs natural language, camera vocabulary, negative handling.
    → {prompt, negative, notes}."""
    meta = catalog.load_families().get(family) or {}
    prompt_meta = meta.get("prompt") or {}
    supports = meta.get("supports") or {}
    style = prompt_meta.get("style", "natural_language")
    notes: list[str] = []

    parts: list[str] = [structure["subject"]]
    styles = [st for st in structure["styles"] if st.lower() not in structure["subject"].lower()]
    if styles:
        parts.append(", ".join(styles))
    if prompt_meta.get("camera_language") and not re.search(
            r"\b(\d+mm|lens|camera|close-?up|wide shot|dolly|pan\b|push in)\b",
            structure["subject"], re.I):
        parts.append(CAMERA_HINTS.get(structure["modality"], CAMERA_HINTS["image"]))
        notes.append("added camera language — this model responds strongly to it")
    for quoted in structure["text_content"]:
        parts.append(f'the text "{quoted}" rendered clearly')
        notes.append("spelled required text in quotes")
    terms = _knowledge_terms(family)
    if terms:
        parts.append(", ".join(terms))
        notes.append(f"folded in learned terms for {family}: {', '.join(terms)}")

    negative = None
    avoid = list(structure["avoid"])
    if supports.get("negative_prompt"):
        negative = ", ".join(avoid) if avoid else DEFAULT_NEGATIVE
        if avoid:
            notes.append("moved avoid-list into the negative prompt")
    elif avoid:
        parts.append("without " + " or ".join(avoid))
        notes.append("no negative prompt on this model — folded avoid-list into the prompt")

    if style == "tags":
        words = ", ".join(p.strip(" .") for p in parts if p)
        prompt = f"{words}, {', '.join(QUALITY_TAGS)}"
        notes.append("compiled as comma-separated tags with quality boosters")
        cap = prompt_meta.get("max_terms")
        if cap:
            toks = prompt.split(", ")
            if len(toks) > cap:
                prompt = ", ".join(toks[:cap])
                notes.append(f"trimmed to ~{cap} terms for this model's window")
    else:
        sentence = ". ".join(p.strip(" .") for p in parts if p)
        prompt = sentence + "."
        if style == "hybrid":
            notes.append("compiled as natural language (hybrid model)")
        else:
            notes.append("compiled as flowing natural language")
    if prompt_meta.get("notes"):
        notes.append(f"model guidance: {prompt_meta['notes']}")
    return {"prompt": prompt, "negative": negative, "notes": notes}


def evaluation_criteria(intent: dict) -> list[dict]:
    crit = [{"key": "subject", "check": "the requested subject is present and central"}]
    if intent.get("aspect_ratio"):
        crit.append({"key": "aspect_ratio", "check": f"output is {intent['aspect_ratio']}"})
    if intent.get("duration_s"):
        crit.append({"key": "duration", "check": f"runtime ≈ {intent['duration_s']}s"})
    for st in intent.get("styles", []):
        crit.append({"key": "style", "check": f"reads as {st}"})
    if intent.get("character_consistency"):
        crit.append({"key": "consistency", "check": "the same character is recognizable throughout"})
    for t in intent.get("text_content", []):
        crit.append({"key": "typography", "check": f'the text "{t}" is legible and correctly spelled'})
    for a in intent.get("avoid", []):
        crit.append({"key": "avoid", "check": f"no {a}"})
    return crit


def compile_package(s: Session, idea: str, family: str | None = None,
                    provider: str | None = None, params_override: dict | None = None,
                    use_llm: bool = False, intent_override: dict | None = None) -> dict:
    """The full pipeline → PromptPackage. `family`/`provider` pin the target
    (recompile path); otherwise the router picks and explains."""
    intent = intent_override or intent_mod.extract(idea)
    route = router.recommend(s, intent, family=family, provider=provider)
    chosen = route["recommended"]
    if chosen is None:
        return {"original": idea, "intent": intent, "route": route, "error":
                route.get("unsupported") or "no candidate model"}

    structure = structure_idea(intent)
    optimized = optimize_for_model(structure, chosen["family"])

    params = intent_mod.to_params(intent)
    params.update(params_override or {})
    check = catalog.validate_params(chosen["family"], params)
    params = check["params"]  # hard caps applied, and said so below

    llm_note = None
    if use_llm:
        try:
            from ..knowledge import enhance
            polished = enhance.enhance_prompt(optimized["prompt"], chosen["family"], None)
            optimized["prompt"] = polished["enhanced"]
            if polished.get("negative"):
                optimized["negative"] = polished["negative"]
            llm_note = {"applied": True, "notes": polished.get("notes", [])}
        except Exception as e:  # LLMNotConfigured / BudgetExceeded / anything — never fatal
            llm_note = {"applied": False, "reason": str(e) or type(e).__name__}

    est = pricing.estimate(chosen["family"], chosen["provider"], params)
    kind = pricing.family_kind(chosen["family"])
    package = {
        "original": idea,
        "optimized_prompt": optimized["prompt"],
        "negative_prompt": optimized["negative"],
        "structured": structure,
        "intent": intent,
        "family": chosen["family"], "display_name": chosen["display_name"],
        "provider": chosen["provider"], "provider_model_id": chosen["provider_model_id"],
        "connected": chosen["connected"], "kind": kind,
        "params": params,
        "references": (params_override or {}).get("_inputs", {}).get("references", []),
        "expected_output": f"{kind} · {params.get('aspect_ratio', 'default AR')}"
                           + (f" · {params['duration_s']}s" if params.get("duration_s") else ""),
        "estimated_cost": est,
        "plan": [{"step": "generate", "tool": f"generate_{kind}", "family": chosen["family"]}],
        "evaluation_criteria": evaluation_criteria(intent),
        "optimization_notes": optimized["notes"],
        "llm_polish": llm_note,
        "warnings": check["warnings"] + [v["message"] for v in check["violations"]],
        "route": {"policy": route["policy"], "reasons": chosen["reasons"],
                  "basis": chosen["basis"],
                  "unsupported_constraints": chosen["unsupported_constraints"],
                  "alternatives": [{k: a[k] for k in
                                    ("family", "display_name", "provider", "total", "estimate", "connected")}
                                   for a in route["alternatives"][:4]]},
    }
    return package


def recompile(s: Session, package: dict, family: str,
              provider: str | None = None, use_llm: bool = False) -> dict:
    """Same idea + intent, new target model (§4: switching models recompiles
    without destroying intent)."""
    return compile_package(s, package.get("original", ""), family=family,
                           provider=provider,
                           params_override={k: v for k, v in (package.get("params") or {}).items()
                                            if k == "_inputs"},
                           use_llm=use_llm, intent_override=package.get("intent"))
