"""Evaluation + refinement (spec §6; Phase 2 multimodal upgrade).

Two layers, always labelled so the user knows what judged the result:

* **metadata** — deterministic checks against what the run actually produced
  (dimensions, duration, media type) and against the prompt itself (missing
  intent elements, over/under-constraint, conflicts). Always runs, cheap,
  low confidence about *content*.
* **multimodal** — a real look at the artifact through `forge/vision.py`
  (configured vision LLM, or MuAPI's openrouter-vision; video is sampled into
  keyframes; audio is transcribed/analysed). Scores prompt adherence,
  composition, consistency, quality and artifacts with evidence.

When no evaluator is configured the report says so explicitly and stays in
metadata mode — content judgement is never simulated. The proposed refinement
is a NEW variant with a word-level diff; the user's prompt is never
overwritten."""
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


def evaluate_run(s: Session, run: VariantRun, with_multimodal: bool = True) -> dict:
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

    multimodal = multimodal_evaluation(s, run) if with_multimodal else {
        "available": False, "mode": "metadata", "reason": "not requested"}
    for issue in (multimodal.get("issues") or []):
        findings.append({"kind": "content", "severity": "warn", "message": issue})

    unavailable = []
    if not multimodal.get("available"):
        unavailable.append(
            "content judgement (composition, character consistency, artifacts) "
            "was NOT performed: " + (multimodal.get("reason") or "no evaluator"))

    verdict = ("fail" if any(f["severity"] == "error" for f in findings)
               else "warn" if any(f["severity"] == "warn" for f in findings)
               else "pass")
    dims = dict(multimodal.get("dimensions") or {})
    overall = multimodal.get("overall_score")
    confidence = multimodal.get("confidence") if multimodal.get("available") else 0.3
    return {"findings": findings, "checked": checked, "unavailable": unavailable,
            "verdict": verdict, "multimodal": multimodal,
            "overall_score": overall, "dimensions": dims,
            "recommendations": multimodal.get("recommendations") or [],
            "evidence": multimodal.get("evidence") or [],
            "confidence": confidence,
            "mode": multimodal.get("mode", "metadata")}


VISION_SYSTEM = (
    "You are a strict generative-media reviewer. You are shown the actual "
    "output of a generation request. Judge ONLY what you can see or hear. "
    "Reply with JSON only: {\"dimensions\": {\"prompt_adherence\": 0-100, "
    "\"composition\": 0-100, \"subject_presence\": 0-100, \"quality\": 0-100, "
    "\"consistency\": 0-100, \"typography\": 0-100}, \"issues\": [\"…\"], "
    "\"recommendations\": [\"…\"], \"evidence\": [\"what you actually saw\"], "
    "\"confidence\": 0.0-1.0}. Omit any dimension the request does not "
    "involve (e.g. typography when no text was requested). Never invent "
    "detail you cannot observe.")

DIMENSION_KEYS = ("prompt_adherence", "composition", "subject_presence",
                  "quality", "consistency", "typography", "motion",
                  "temporal_stability", "audio", "intelligibility")


def _media_for_run(s: Session, run: VariantRun) -> tuple[object | None, str]:
    """→ (Path|None, kind) for whatever this run produced."""
    from pathlib import Path

    from ..config import get_config
    g = s.get(Generation, run.generation_id) if run.generation_id else None
    if g is None:
        return None, "unknown"
    artifact = (g.params or {}).get("_artifact")
    if artifact and artifact.get("path"):
        try:
            from . import artifacts
            return artifacts.resolve(artifact["path"]), artifact.get("kind") or "audio"
        except ValueError:
            return None, artifact.get("kind") or "audio"
    post = s.get(Post, g.output_post_id) if g.output_post_id else None
    if post is not None and post.media_path:
        return get_config().data_dir / post.media_path, post.media_type
    return None, "unknown"


def _ask_prompt(v: PromptVariant, intent: dict, kind: str) -> str:
    wants = []
    if intent.get("aspect_ratio"):
        wants.append(f"aspect ratio {intent['aspect_ratio']}")
    if intent.get("duration_s"):
        wants.append(f"about {intent['duration_s']}s long")
    for st in intent.get("styles", []):
        wants.append(f"style: {st}")
    for t in intent.get("text_content", []):
        wants.append(f'must legibly render the text "{t}"')
    for a in intent.get("avoid", []):
        wants.append(f"must NOT contain {a}")
    if intent.get("character_consistency"):
        wants.append("the same character must be recognisable throughout")
    ask = [f"The request was: {v.package.get('original') or v.prompt}",
           f"The prompt sent to the model was: {v.prompt}"]
    if wants:
        ask.append("Explicit requirements: " + "; ".join(wants))
    ask.append(f"You are looking at the generated {kind}. Score it.")
    return "\n".join(ask)


def multimodal_evaluation(s: Session, run: VariantRun) -> dict:
    """Genuine content evaluation, or an honest unavailable report."""
    from . import vision
    v = s.get(PromptVariant, run.variant_id)
    intent = (v.package or {}).get("intent") or {}
    path, kind = _media_for_run(s, run)
    if path is None:
        return {"available": False, "mode": "metadata",
                "reason": "this run produced no artifact to inspect"}

    frames: list[bytes] = []
    transcript = None
    if kind == "image":
        raw = vision.read_image(path)
        frames = [raw] if raw else []
    elif kind == "video":
        frames = vision.video_frames(path, count=3)
    elif kind == "audio":
        return _evaluate_audio(s, path, v, intent)
    elif kind == "3d":
        return _evaluate_3d(path)

    if not frames:
        return {"available": False, "mode": "metadata",
                "reason": f"could not sample the {kind} for inspection "
                          "(is ffmpeg present?)"}
    try:
        raw, backend = vision.look(s, VISION_SYSTEM, _ask_prompt(v, intent, kind), frames)
    except vision.NoEvaluator as e:
        return {"available": False, "mode": "metadata", "reason": str(e)}
    except Exception as e:                      # provider/network/budget
        return {"available": False, "mode": "metadata",
                "reason": f"evaluator call failed: {type(e).__name__}: {e}"}

    parsed = vision.parse_verdict(raw)
    if not parsed:
        return {"available": False, "mode": "metadata", "backend": backend,
                "reason": "the evaluator did not return usable JSON"}
    dims = {k: max(0, min(100, int(x))) for k, x in (parsed.get("dimensions") or {}).items()
            if k in DIMENSION_KEYS and isinstance(x, (int, float))}
    overall = round(sum(dims.values()) / len(dims)) if dims else None
    try:
        confidence = float(parsed.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.7
    return {"available": True, "mode": "multimodal", "backend": backend,
            "frames_examined": len(frames), "overall_score": overall,
            "dimensions": dims,
            "issues": [str(i)[:300] for i in (parsed.get("issues") or [])][:10],
            "recommendations": [str(r)[:300] for r in (parsed.get("recommendations") or [])][:10],
            "evidence": [str(e)[:300] for e in (parsed.get("evidence") or [])][:10],
            "confidence": max(0.0, min(1.0, confidence)),
            "transcript": transcript}


def _evaluate_audio(s: Session, path, v: PromptVariant, intent: dict) -> dict:
    """Audio: transcribe through a configured provider, then compare."""
    from .. import settings_store
    if not settings_store.get(s, "muapi_api_key"):
        return {"available": False, "mode": "metadata",
                "reason": "no connected provider declares transcription or audio "
                          "analysis — connect MuAPI in Settings → AI providers"}
    try:
        import httpx

        from ..generation.muapi import API, extract_text
        key = settings_store.get(s, "muapi_api_key")
        with httpx.Client(timeout=180, headers={"x-api-key": key}) as c:
            up = c.post(f"{API}/upload_file",
                        files={"file": (path.name, path.read_bytes(), "audio/mpeg")})
            body = up.json() if up.content else {}
            url = body if isinstance(body, str) else (body.get("url") or body.get("file_url"))
            if not url:
                raise RuntimeError("upload returned no URL")
            sub = c.post(f"{API}/openai-whisper", json={"audio_url": url},
                         headers={"x-api-key": key, "Content-Type": "application/json"})
            rid = (sub.json() or {}).get("id") or (sub.json() or {}).get("request_id")
            import time
            text = None
            for _ in range(60):
                res = c.get(f"{API}/predictions/{rid}/result")
                data = res.json() if res.content else {}
                st = str(data.get("status") or "").lower()
                if st in ("succeeded", "completed", "success"):
                    text = extract_text(data)
                    break
                if st in ("failed", "error"):
                    raise RuntimeError(str(data.get("error")))
                time.sleep(2)
    except Exception as e:
        return {"available": False, "mode": "metadata",
                "reason": f"transcription failed: {type(e).__name__}: {e}"}
    if text is None:
        return {"available": False, "mode": "metadata",
                "reason": "transcription returned no text"}
    wanted = (v.package or {}).get("original") or v.prompt or ""
    words = [w for w in re.findall(r"[a-z']+", wanted.lower()) if len(w) > 3]
    heard = set(re.findall(r"[a-z']+", (text or "").lower()))
    hit = sum(1 for w in set(words) if w in heard)
    adherence = round(100 * hit / max(1, len(set(words))))
    issues = [] if adherence >= 70 else ["the spoken audio does not closely match the script"]
    return {"available": True, "mode": "multimodal", "backend": "muapi:openai-whisper",
            "overall_score": adherence, "dimensions": {"prompt_adherence": adherence},
            "issues": issues, "recommendations": [],
            "evidence": [f"transcript: {text[:280]}"], "confidence": 0.7,
            "transcript": text}


def _evaluate_3d(path) -> dict:
    """3D: format and payload validity, checked locally — no guessing."""
    suffix = path.suffix.lower()
    size = path.stat().st_size if path.exists() else 0
    issues, dims = [], {}
    valid_ext = suffix in (".glb", ".gltf", ".obj", ".fbx", ".usdz", ".ply", ".zip")
    if not valid_ext:
        issues.append(f"unexpected 3D container '{suffix}'")
    header_ok = True
    if suffix == ".glb":
        header_ok = path.exists() and path.read_bytes()[:4] == b"glTF"
        if not header_ok:
            issues.append("the .glb file does not start with the glTF magic header")
    if size < 1024:
        issues.append("the mesh file is suspiciously small")
    dims["format_validity"] = 100 if (valid_ext and header_ok) else 0
    dims["payload"] = 100 if size >= 1024 else 20
    return {"available": True, "mode": "structural", "backend": "local",
            "overall_score": round(sum(dims.values()) / len(dims)),
            "dimensions": dims, "issues": issues,
            "recommendations": ["open the mesh in a viewer to judge geometry and "
                                "textures — that needs a 3D-capable evaluator"],
            "evidence": [f"{suffix} file, {size} bytes"], "confidence": 0.5}


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
        elif f["kind"] == "content":
            # a real evaluator's issue is advice, not an automatic rewrite —
            # surface it so the user decides
            changes.append(f"evaluator noted: {f['message']}")
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
               create_variant: bool = True, with_multimodal: bool = True) -> dict:
    """Evaluate → propose → (optionally) store the proposal as a NEW variant.
    The evaluation is persisted on the run either way."""
    from . import experiments
    run = s.get(VariantRun, run_id)
    if run is None:
        raise experiments.LabError(f"run {run_id} not found")
    evaluation = evaluate_run(s, run, with_multimodal=with_multimodal)
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
