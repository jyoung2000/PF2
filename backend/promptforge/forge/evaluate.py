"""Evaluation + refinement (spec §6): deterministic checks against what the
run actually produced (dimensions, duration, media type) and against the
prompt itself (missing intent elements, over/under-constraint, conflicts).
Content-level judgement that would need a vision model is REPORTED as
unavailable rather than guessed. The proposed refinement is a NEW variant
with a word-level diff — the user's prompt is never overwritten."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import Generation, Post
from .models import PromptVariant, VariantRun

CONFLICTS = [("photorealistic", "cartoon"), ("photorealistic", "anime"),
             ("realistic", "low-poly"), ("minimalist", "ultra detailed"),
             ("black and white", "vibrant colors")]


def _ratio(w: int | None, h: int | None) -> float | None:
    return (w / h) if w and h else None


def _want_ratio(ar: str | None) -> float | None:
    try:
        a, b = str(ar).split(":")
        return float(a) / float(b)
    except (ValueError, AttributeError, ZeroDivisionError):
        return None


def evaluate_run(s: Session, run: VariantRun) -> dict:
    """→ {findings: [{kind, severity, message}], checked, unavailable}."""
    v = s.get(PromptVariant, run.variant_id)
    g = s.get(Generation, run.generation_id) if run.generation_id else None
    post = s.get(Post, g.output_post_id) if g and g.output_post_id else None
    intent = (v.package or {}).get("intent") or {}
    findings: list[dict] = []
    checked: list[str] = []

    if g and g.status == "failed":
        findings.append({"kind": "generation_failed", "severity": "error",
                         "message": g.error or "generation failed"})

    if post is not None:
        want = _want_ratio(intent.get("aspect_ratio") or (v.params or {}).get("aspect_ratio"))
        got = _ratio(post.media_width, post.media_height)
        checked.append("aspect_ratio")
        if want and got and abs(got - want) / want > 0.02:
            findings.append({"kind": "aspect_ratio", "severity": "warn",
                             "message": f"requested {intent.get('aspect_ratio')} but the output is "
                                        f"{post.media_width}×{post.media_height}"})
        if intent.get("duration_s") and post.duration_s:
            checked.append("duration")
            if abs(post.duration_s - intent["duration_s"]) / intent["duration_s"] > 0.2:
                findings.append({"kind": "duration", "severity": "warn",
                                 "message": f"requested ≈{intent['duration_s']}s, got {post.duration_s:.1f}s"})
        want_kind = "video" if intent.get("modality") == "video" else "image"
        checked.append("media_type")
        if post.media_type != want_kind:
            findings.append({"kind": "media_type", "severity": "error",
                             "message": f"expected {want_kind}, got {post.media_type}"})

    prompt = v.prompt or ""
    low = prompt.lower()
    checked.append("prompt_coverage")
    for st in intent.get("styles", []):
        if st.lower() not in low:
            findings.append({"kind": "missing_element", "severity": "warn",
                             "message": f"the requested style '{st}' never made it into the prompt"})
    for t in intent.get("text_content", []):
        if t.lower() not in low:
            findings.append({"kind": "missing_element", "severity": "warn",
                             "message": f"required text \"{t}\" is not spelled out in the prompt"})
    for a in intent.get("avoid", []):
        neg = (v.negative or "").lower()
        if a.lower() not in neg and f"without {a.lower()}" not in low and f"no {a.lower()}" not in low:
            findings.append({"kind": "constraint", "severity": "warn",
                             "message": f"'avoid {a}' is expressed nowhere (prompt or negative)"})

    words = re.split(r"[,\s]+", prompt.strip())
    checked.append("constraint_balance")
    if len(words) > 110:
        findings.append({"kind": "over_constrained", "severity": "info",
                         "message": f"{len(words)} terms — very long prompts dilute each constraint"})
    subject = ((v.package or {}).get("structured") or {}).get("subject") or prompt
    if len(subject.split()) < 4:
        findings.append({"kind": "ambiguous", "severity": "info",
                         "message": "the subject is very short — models will improvise the rest"})
    for a, b in CONFLICTS:
        if a in low and b in low:
            findings.append({"kind": "conflict", "severity": "warn",
                             "message": f"'{a}' and '{b}' pull in opposite directions"})

    unavailable = ["composition adherence, character consistency and artifact "
                   "detection need a vision-capable model — not configured, so "
                   "they are not judged here"]
    return {"findings": findings, "checked": checked, "unavailable": unavailable,
            "verdict": ("fail" if any(f["severity"] == "error" for f in findings)
                        else "warn" if any(f["severity"] == "warn" for f in findings)
                        else "pass")}


def _word_diff(before: str, after: str) -> list[dict]:
    import difflib
    out = []
    sm = difflib.SequenceMatcher(a=before.split(), b=after.split())
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out.append({"op": "same", "text": " ".join(before.split()[i1:i2])})
        else:
            if i1 != i2:
                out.append({"op": "del", "text": " ".join(before.split()[i1:i2])})
            if j1 != j2:
                out.append({"op": "add", "text": " ".join(after.split()[j1:j2])})
    return out


def propose_refinement(s: Session, run: VariantRun, evaluation: dict,
                       use_llm: bool = False) -> dict:
    """Deterministic prompt surgery from the findings (+ optional LLM pass)
    → {prompt, negative, diff, changes, llm}. Nothing is written here."""
    v = s.get(PromptVariant, run.variant_id)
    intent = (v.package or {}).get("intent") or {}
    prompt, negative = v.prompt, v.negative
    changes: list[str] = []

    for f in evaluation.get("findings", []):
        if f["kind"] == "missing_element" and "style '" in f["message"]:
            st = f["message"].split("'")[1]
            prompt = f"{prompt.rstrip('. ')}, {st}"
            changes.append(f"added the missing style '{st}'")
        elif f["kind"] == "missing_element" and 'required text "' in f["message"]:
            t = f["message"].split('"')[1]
            prompt = f"{prompt.rstrip('. ')}, the text \"{t}\" rendered clearly"
            changes.append(f"spelled out the required text \"{t}\"")
        elif f["kind"] == "constraint":
            a = f["message"].split("'avoid ")[1].split("'")[0]
            if negative is not None:
                negative = f"{negative}, {a}" if negative else a
                changes.append(f"moved '{a}' into the negative prompt")
            else:
                prompt = f"{prompt.rstrip('. ')}, without {a}"
                changes.append(f"added 'without {a}'")
        elif f["kind"] == "aspect_ratio" and intent.get("aspect_ratio"):
            changes.append(f"re-asserted aspect ratio {intent['aspect_ratio']} in params")
        elif f["kind"] == "over_constrained":
            toks = [t for t in re.split(r",\s*", prompt) if t.strip()]
            seen, dedup = set(), []
            for t in toks:
                k = t.strip().lower()
                if k not in seen:
                    seen.add(k)
                    dedup.append(t.strip())
            if len(dedup) < len(toks):
                prompt = ", ".join(dedup)
                changes.append(f"removed {len(toks) - len(dedup)} duplicate terms")
        elif f["kind"] == "ambiguous":
            changes.append("consider one concrete detail for the subject "
                           "(who/where/when) — left to you, never invented")

    llm_note = None
    if use_llm:
        try:
            from ..knowledge import enhance
            polished = enhance.enhance_prompt(prompt, v.family, None)
            prompt = polished["enhanced"]
            llm_note = {"applied": True, "notes": polished.get("notes", [])}
            changes.append("LLM polish applied on top of the deterministic fixes")
        except Exception as e:
            llm_note = {"applied": False, "reason": str(e) or type(e).__name__}

    return {"prompt": prompt, "negative": negative,
            "diff": _word_diff(v.prompt, prompt), "changes": changes, "llm": llm_note,
            "unchanged": prompt == v.prompt and negative == v.negative}


def refine_run(s: Session, run_id: int, use_llm: bool = False,
               create_variant: bool = True) -> dict:
    """Evaluate → propose → (optionally) store the proposal as a NEW variant.
    The evaluation is persisted on the run either way."""
    from . import experiments
    run = s.get(VariantRun, run_id)
    if run is None:
        raise experiments.LabError(f"run {run_id} not found")
    evaluation = evaluate_run(s, run)
    run.evaluation = evaluation
    proposal = propose_refinement(s, run, evaluation, use_llm=use_llm)
    new_variant = None
    if create_variant and not proposal["unchanged"]:
        v = s.get(PromptVariant, run.variant_id)
        nv = experiments.add_variant(
            s, v.experiment_id, prompt=proposal["prompt"],
            negative=proposal["negative"], family=v.family, provider=v.provider,
            params=dict(v.params or {}), parent_id=v.id, origin="refined",
            label=f"refined from v{v.version}")
        nv.package = dict(v.package or {})
        new_variant = nv.id
    return {"evaluation": evaluation, "proposal": proposal,
            "new_variant_id": new_variant}
