"""Deterministic extraction with provenance (I3): prompts, models (+versions),
techniques, camera and lighting vocabulary, and a heuristic AI-likelihood —
all evidence-tagged, all before any LLM is involved."""
from __future__ import annotations

import re
from typing import Any

from ..aliases import DISPLAY_NAMES, normalize_model
from ..knowledge import techniques
from ..scrapers import x_text
from . import provenance, scoring

AI_NATIVE = scoring.AI_NATIVE_PLATFORMS

# family → version pattern (first group = version)
MODEL_VERSION_RES: dict[str, re.Pattern] = {
    "midjourney": re.compile(r"(?:--v\s*|\bv|version\s*)(\d(?:\.\d)?)\b", re.I),
    "niji": re.compile(r"--niji\s*(\d)", re.I),
    "kling": re.compile(r"kling\s*(?:ai\s*)?v?(\d(?:\.\d)?)", re.I),
    "veo": re.compile(r"veo\s*-?(\d(?:\.\d)?)", re.I),
    "sora": re.compile(r"sora\s*-?(\d(?:\.\d)?)", re.I),
    "wan": re.compile(r"wan\s*-?(\d(?:\.\d)?)", re.I),
    "seedance": re.compile(r"seedance\s*-?(\d(?:\.\d)?)", re.I),
    "seedream": re.compile(r"seedream\s*-?(\d(?:\.\d)?)", re.I),
    "hailuo": re.compile(r"hailuo\s*-?(\d\d?)", re.I),
    "runway": re.compile(r"gen-?\s*(\d(?:\.\d)?)", re.I),
    "luma": re.compile(r"ray\s*-?(\d(?:\.\d)?)", re.I),
    "flux": re.compile(r"flux(?:\.1)?\s*-?(kontext|krea|dev|schnell|pro|ultra|2)\b", re.I),
    "hunyuan": re.compile(r"hunyuan\s*(?:video)?\s*-?(\d(?:\.\d)?)", re.I),
    "ltx-video": re.compile(r"ltx\s*-?v?(\d(?:\.\d)?)", re.I),
    "pika": re.compile(r"pika\s*-?(\d(?:\.\d)?)", re.I),
    "imagen": re.compile(r"imagen\s*-?(\d)", re.I),
    "ideogram": re.compile(r"ideogram\s*-?v?(\d(?:\.\d)?)", re.I),
    "recraft": re.compile(r"recraft\s*-?v?(\d)", re.I),
    "gpt-image": re.compile(r"gpt[\s-]*image[\s-]*(\d(?:\.\d)?)", re.I),
    "pixverse": re.compile(r"pixverse\s*-?v?(\d(?:\.\d)?)", re.I),
    "vidu": re.compile(r"vidu\s*-?q?(\d(?:\.\d)?)", re.I),
}

_LENS_RE = re.compile(r"\b(\d{2,3})\s?mm\b")
_SHOT_SIZES = [
    ("extreme close-up", ("extreme close-up", "extreme closeup", "ecu")),
    ("close-up", ("close-up", "close up", "closeup")),
    ("medium close-up", ("medium close-up", "medium closeup", "mcu")),
    ("medium shot", ("medium shot", "mid shot", "waist up", "waist-up")),
    ("medium wide", ("medium wide", "medium-wide", "cowboy shot")),
    ("full shot", ("full shot", "full body", "full-body", "head to toe")),
    ("wide shot", ("wide shot", "wide-shot", "long shot")),
    ("extreme wide", ("extreme wide", "extreme long shot", "vast landscape shot")),
    ("establishing", ("establishing shot",)),
    ("two shot", ("two shot", "two-shot")),
    ("over-the-shoulder", ("over the shoulder", "over-the-shoulder", "ots shot")),
    ("pov", ("pov", "point of view", "first person")),
    ("insert", ("insert shot", "detail shot")),
]
_ANGLES = [
    ("low angle", ("low angle", "low-angle", "worm's eye", "from below")),
    ("high angle", ("high angle", "high-angle", "from above", "looking down")),
    ("dutch angle", ("dutch angle", "dutch tilt", "canted")),
    ("top-down", ("top-down", "top down", "overhead", "bird's-eye", "birds eye")),
    ("eye level", ("eye level", "eye-level")),
]
_LIGHTING = [
    ("golden hour", ("golden hour", "magic hour")), ("blue hour", ("blue hour", "twilight")),
    ("neon", ("neon",)), ("volumetric", ("volumetric", "god rays", "light shafts")),
    ("rim light", ("rim light", "rim-lit", "backlit")), ("soft light", ("soft light", "softbox", "diffused")),
    ("hard light", ("hard light", "harsh light", "hard shadows")), ("low-key", ("low-key", "low key", "chiaroscuro")),
    ("high-key", ("high-key", "high key")), ("candlelight", ("candle", "candlelight", "firelight")),
    ("moonlight", ("moonlight", "moonlit")), ("studio", ("studio lighting", "studio light")),
    ("overcast", ("overcast", "cloudy light")), ("practical", ("practical light", "practicals", "lamp light")),
]
_COMPOSITION = [
    ("rule of thirds", ("rule of thirds",)), ("symmetry", ("symmetrical", "symmetry", "centered composition")),
    ("leading lines", ("leading lines",)), ("negative space", ("negative space",)),
    ("framing", ("framed by", "natural frame")), ("silhouette", ("silhouette",)),
    ("reflection", ("reflection", "mirrored")), ("foreground", ("foreground element", "foreground blur")),
]
_AI_HINT_RE = re.compile(r"#?(ai\s?art|aiart|aivideo|ai\s?video|midjourney|stablediffusion|comfyui|"
                         r"genai|generative|prompt|text\s?to\s?video|img2vid|i2v)", re.I)
_HUMAN_HINT_RE = re.compile(r"\b(shot on|filmed on|photographed|my camera|behind the scenes|"
                            r"no ai|not ai|real photo|iphone \d+|sony a7|canon r\d)\b", re.I)


def _find_terms(text: str, table: list[tuple[str, tuple[str, ...]]]) -> list[dict]:
    low = text.lower()
    out = []
    for label, variants in table:
        for v in variants:
            idx = low.find(v)
            if idx >= 0 and (len(v) > 3 or re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", low)):
                out.append({"value": label, "evidence": text[max(0, idx - 20): idx + len(v) + 20].strip()})
                break
    return out


def detect_camera(text: str | None) -> dict:
    """{lens_mm: [..], shot_size: [..], angle: [..]} with evidence."""
    if not text:
        return {}
    out: dict[str, Any] = {}
    lenses = sorted({int(m) for m in _LENS_RE.findall(text) if 8 <= int(m) <= 800})
    if lenses:
        out["lens_mm"] = lenses
    shots = _find_terms(text, _SHOT_SIZES)
    if shots:
        out["shot_size"] = shots
    angles = _find_terms(text, _ANGLES)
    if angles:
        out["angle"] = angles
    return out


def detect_lighting(text: str | None) -> list[dict]:
    return _find_terms(text or "", _LIGHTING)


def detect_composition(text: str | None) -> list[dict]:
    return _find_terms(text or "", _COMPOSITION)


def detect_model_version(text: str | None, family: str | None) -> str | None:
    if not text or not family:
        return None
    pat = MODEL_VERSION_RES.get(family)
    if not pat:
        return None
    m = pat.search(text)
    return m.group(1).lower() if m else None


def classify_heuristic(post: Any) -> tuple[str, float, str]:
    """Deterministic AI-likelihood (5-level) from platform + evidence. Never
    deletes anything; the LLM pass may refine later."""
    params = post.params or {}
    observed = post.observed or {}
    text = " ".join(x for x in (post.prompt, (observed.get("text") or {}).get("body"),
                                " ".join((observed.get("text") or {}).get("hashtags") or []))
                    if x)
    if post.platform in AI_NATIVE or getattr(post, "origin", "") == "generated":
        return "definitely_ai", 0.95, f"{post.platform} hosts AI generations only"
    if params.get("workflow") or params.get("metadata_format") or params.get("declared_ai_generated"):
        return "definitely_ai", 0.97, "embedded generation metadata present"
    if _HUMAN_HINT_RE.search(text) and not _AI_HINT_RE.search(text):
        return "probably_not_ai", 0.7, "text claims a real camera / non-AI origin"
    if provenance.source_of(post.assertions, "model") in ("observed", "extracted", "metadata"):
        return "probably_ai", 0.8, "generation model named in the post"
    if _AI_HINT_RE.search(text):
        return "probably_ai", 0.7, "AI-related hashtags/terms in the text"
    if post.prompt and provenance.is_high_confidence(post.assertions, "prompt"):
        return "probably_ai", 0.65, "a labelled prompt was posted with the media"
    return "uncertain", 0.5, "no explicit AI evidence either way"


def apply_extraction(post: Any) -> dict:
    """Run every deterministic extractor over a stored post: fills assertions
    (techniques/camera/lighting/composition/model_version), technique_tags,
    model_version, heuristic ai_status. Returns a summary for analysis[]."""
    assertions = dict(post.assertions or {})
    observed = post.observed or {}
    body = (observed.get("text") or {}).get("body") or ""
    text = "\n".join(x for x in (post.prompt, post.negative_prompt, body) if x)
    family = post.model_family or (normalize_model(post.model_name) if post.model_name else None)

    summary: dict[str, Any] = {"method": "deterministic"}
    version = post.model_version or detect_model_version(text, family)
    if version and not post.model_version:
        post.model_version = version
    if version:
        provenance.assert_field(assertions, "model_version", version, "extracted", 0.8,
                                "version pattern in text/metadata")

    tech = techniques.detect_techniques(text)
    if tech:
        post.technique_tags = sorted(set((post.technique_tags or []) + tech))
        provenance.assert_field(assertions, "techniques", tech, "extracted", 0.85,
                                "taxonomy keywords in prompt/text")
    camera = detect_camera(text)
    if camera:
        provenance.assert_field(assertions, "camera", camera, "extracted", 0.8,
                                "camera vocabulary in prompt/text")
    lighting = detect_lighting(text)
    if lighting:
        provenance.assert_field(assertions, "lighting", [l["value"] for l in lighting],
                                "extracted", 0.8, "; ".join(l["evidence"] for l in lighting[:3]))
    composition = detect_composition(text)
    if composition:
        provenance.assert_field(assertions, "composition", [c["value"] for c in composition],
                                "extracted", 0.75, "; ".join(c["evidence"] for c in composition[:3]))
    if family and family in DISPLAY_NAMES:
        provenance.assert_field(assertions, "model_family", family, "extracted", 0.9,
                                "alias normalisation of the model name")

    status, conf, reason = classify_heuristic(post)
    if post.ai_status is None or (post.analysis or {}).get("ai", {}).get("source") in (None, "heuristic"):
        post.ai_status, post.ai_confidence = status, conf
        analysis = dict(post.analysis or {})
        analysis["ai"] = {"status": status, "confidence": conf, "reason": reason,
                          "source": "heuristic"}
        post.analysis = analysis
    post.assertions = assertions
    summary.update({"techniques": tech, "camera": camera,
                    "lighting": [l["value"] for l in lighting],
                    "composition": [c["value"] for c in composition],
                    "model_version": version, "ai_status": status})
    return summary


def extract_from_text(text: str, quoted: str | None = None) -> dict:
    """Freeform text → structured extraction dict (wraps x_text, the
    deterministic miner) + version/camera/lighting."""
    ex = x_text.extract(text, quoted)
    family = normalize_model(ex.model_name) if ex.model_name else None
    method = "labelled" if ex.prompt and ex.prompt_confidence == "high" else (
        "paragraph" if ex.prompt else "none")
    return {
        "prompt": ex.prompt, "negative_prompt": ex.negative,
        "prompt_method": method, "prompt_confidence": ex.prompt_confidence,
        "model_name": ex.model_name, "model_family": family,
        "model_version": detect_model_version(text, family),
        "model_stated": ex.model_stated, "hashtags": ex.hashtags,
        "camera": detect_camera(text), "lighting": [l["value"] for l in detect_lighting(text)],
        "techniques": techniques.detect_techniques(text),
    }
