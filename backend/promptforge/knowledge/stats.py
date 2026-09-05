"""Deterministic learning layer (6.3, D11) — zero AI cost, runs on every
ingest. Per-family JSON under DATA_DIR/knowledge/stats/{family}.json:
term/descriptor frequencies (categorized), prompt-length distribution,
parameter histograms. Capped so files stay tiny."""
from __future__ import annotations

import json
import math
import re
import threading
from pathlib import Path
from typing import Any

from ..config import get_config

MAX_TERMS = 300
PRUNE_AT = 450
LEN_BUCKETS = [(0, 25), (25, 50), (50, 100), (100, 200), (200, 400), (400, 10_000)]

STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "with", "and", "or", "for",
    "to", "by", "is", "are", "was", "his", "her", "its", "their", "from",
    "into", "over", "under", "very", "highly", "extremely", "ultra", "super",
}

# category → seed phrases (matched as substrings of extracted phrases).
CATEGORY_LEXICON: dict[str, list[str]] = {
    "lighting": ["light", "lighting", "lit", "golden hour", "blue hour", "neon",
                 "candle", "sunset", "sunrise", "moonlight", "rim", "backlit",
                 "glow", "shadows", "chiaroscuro", "volumetric", "god rays",
                 "overcast", "studio", "sunlight", "luminescent", "lantern"],
    "palette": ["palette", "color", "monochrome", "pastel", "saturated",
                "muted", "teal", "orange", "crimson", "golden", "silver",
                "iridescent", "duotone", "sepia", "vibrant", "desaturated",
                "earth tones", "jewel tones", "chrome", "grade", "graded"],
    "camera": ["shot", "angle", "close-up", "closeup", "wide", "macro", "lens",
               "85mm", "35mm", "50mm", "24mm", "14mm", "135mm", "200mm", "bokeh",
               "depth of field", "fisheye", "anamorphic", "aerial", "drone", "pov",
               "top-down", "isometric", "portrait", "profile", "framing", "f/1",
               "f/2", "f/4", "telephoto", "establishing", "over the shoulder",
               "dutch", "low angle", "high angle", "eye level", "rack focus",
               "dolly", "tracking", "crane", "handheld", "orbit", "push in"],
    "motion": ["motion", "dolly", "pan", "zoom", "orbit", "tracking",
               "timelapse", "slow motion", "hyperlapse", "fpv", "handheld",
               "whip", "loop", "speed ramp", "crane", "tilt"],
    "mood": ["moody", "dreamy", "melancholic", "serene", "ominous", "cozy",
             "ethereal", "dramatic", "mysterious", "whimsical", "nostalgic",
             "eerie", "tranquil", "epic", "intimate", "somber", "playful",
             "haunting", "atmospheric", "brooding"],
    "style": ["style", "watercolor", "oil painting", "ink", "pixel", "low-poly",
              "cinematic", "photorealistic", "anime", "realistic", "render",
              "illustration", "concept art", "sketch", "vaporwave", "cyberpunk",
              "art nouveau", "brutalist", "film still", "risograph", "ukiyo",
              "claymation", "papercraft", "y2k", "retro", "vintage", "noir",
              "surreal", "minimalist", "baroque", "gothic", "film grain"],
    "subject": [],  # fallback bucket
}

_phrase_re = re.compile(r"[^\w\s'/-]+")
_lock = threading.Lock()


def stats_path(family: str) -> Path:
    return get_config().knowledge_dir / "stats" / f"{family}.json"


def load_stats(family: str) -> dict:
    p = stats_path(family)
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except ValueError:
            pass
    return {
        "family": family, "count": 0, "media": {"image": 0, "video": 0},
        "prompt_len": {"sum": 0, "buckets": [0] * len(LEN_BUCKETS)},
        "terms": {}, "categories": {c: {} for c in CATEGORY_LEXICON},
        "params": {}, "last_analyzed_post_id": 0,
    }


def save_stats(family: str, data: dict) -> None:
    p = stats_path(family)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=0, default=str))


def extract_phrases(prompt: str) -> list[str]:
    """Comma-separated clauses → cleaned phrases (≤4 words) + salient words."""
    phrases: list[str] = []
    for chunk in re.split(r"[,;.\n]+", prompt.lower()):
        cleaned = _phrase_re.sub(" ", chunk)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            continue
        words = [w for w in cleaned.split() if w not in STOPWORDS]
        if not words:
            continue
        if len(words) <= 4:
            phrases.append(" ".join(words))
        else:
            # long clause: keep 2-word shingles of adjacent salient words
            phrases.extend(f"{a} {b}" for a, b in zip(words, words[1:])
                           if len(a) > 2 and len(b) > 2)
    return [p for p in phrases if len(p) >= 3]


def categorize(phrase: str) -> str:
    for category, needles in CATEGORY_LEXICON.items():
        for needle in needles:
            if needle in phrase:
                return category
    return "subject"


def _bump(counter: dict, key: str, cap: int = MAX_TERMS, prune_at: int = PRUNE_AT) -> None:
    counter[key] = int(counter.get(key, 0)) + 1
    if len(counter) > prune_at:
        keep = sorted(counter.items(), key=lambda kv: -kv[1])[:cap]
        counter.clear()
        counter.update(keep)


_PARAM_TRACK = ("steps", "cfg_scale", "sampler", "size", "scheduler", "guidance", "fps")
_ASPECTS = [("1:1", 1.0), ("4:5", 0.8), ("5:4", 1.25), ("3:2", 1.5), ("2:3", 0.667),
            ("4:3", 1.333), ("3:4", 0.75), ("16:9", 1.778), ("9:16", 0.5625),
            ("21:9", 2.333), ("2.39:1", 2.39)]


def aspect_bucket(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    r = width / height
    return min(_ASPECTS, key=lambda a: abs(a[1] - r))[0]


def prompt_structure(prompt: str) -> str:
    """tag-list (comma-heavy fragments) vs natural (sentences) vs mixed."""
    commas = prompt.count(",")
    words = max(1, len(prompt.split()))
    sentences = len(re.findall(r"[.!?](\s|$)", prompt))
    if commas / words > 0.12 and sentences <= 1:
        return "tag-list"
    if sentences >= 2 and commas / words < 0.08:
        return "natural"
    return "mixed"


def _ensure_keys(data: dict) -> None:
    for key, default in (("aspects", {}), ("techniques", {}), ("structure", {}),
                         ("weighted_terms", {}), ("creators", {}), ("weekly", {}),
                         ("references", {"with": 0, "without": 0}), ("sources", {})):
        data.setdefault(key, dict(default) if isinstance(default, dict) else default)


def update_family_stats(family: str, prompt: str | None, params: dict | None,
                        media_type: str, post_id: int | None = None,
                        extra: dict | None = None) -> dict:
    """Deterministic per-family stats (free, every ingest). `extra` (I3):
    {engagement, technique_tags, width, height, creator, week, references,
    source} feeds aspect ratios, technique counts, engagement-weighted
    terms, creator patterns and weekly trends."""
    extra = extra or {}
    with _lock:
        data = load_stats(family)
        _ensure_keys(data)
        data["count"] += 1
        data["media"][media_type] = data["media"].get(media_type, 0) + 1
        weight = 1 + (math.log10(extra["engagement"] + 1)
                      if isinstance(extra.get("engagement"), (int, float)) and extra["engagement"] > 0 else 0)
        if prompt:
            words = len(prompt.split())
            data["prompt_len"]["sum"] += words
            for i, (lo, hi) in enumerate(LEN_BUCKETS):
                if lo <= words < hi:
                    data["prompt_len"]["buckets"][i] += 1
                    break
            _bump(data["structure"], prompt_structure(prompt), cap=5, prune_at=10)
            for phrase in extract_phrases(prompt):
                _bump(data["terms"], phrase)
                _bump(data["categories"].setdefault(categorize(phrase), {}), phrase,
                      cap=120, prune_at=200)
                data["weighted_terms"][phrase] = round(
                    data["weighted_terms"].get(phrase, 0) + weight, 2)
            if len(data["weighted_terms"]) > PRUNE_AT:
                keep = sorted(data["weighted_terms"].items(), key=lambda kv: -kv[1])[:MAX_TERMS]
                data["weighted_terms"] = dict(keep)
        for key in _PARAM_TRACK:
            val = (params or {}).get(key)
            if val in (None, ""):
                continue
            bucket = data["params"].setdefault(key, {})
            _bump(bucket, str(val), cap=40, prune_at=60)
        aspect = aspect_bucket(extra.get("width"), extra.get("height"))
        if aspect:
            _bump(data["aspects"], aspect, cap=12, prune_at=20)
        for slug in extra.get("technique_tags") or []:
            _bump(data["techniques"], slug, cap=80, prune_at=120)
        if extra.get("creator"):
            _bump(data["creators"], str(extra["creator"]), cap=60, prune_at=100)
        if extra.get("week"):
            _bump(data["weekly"], str(extra["week"]), cap=104, prune_at=130)
        if extra.get("source"):
            _bump(data["sources"], str(extra["source"]), cap=20, prune_at=30)
        if "references" in extra:
            data["references"]["with" if extra["references"] else "without"] += 1
        save_stats(family, data)
        return data


def top_terms(data: dict, n: int = 25) -> list[tuple[str, int]]:
    return sorted(data.get("terms", {}).items(), key=lambda kv: -kv[1])[:n]


def top_category(data: dict, category: str, n: int = 12) -> list[str]:
    cat = data.get("categories", {}).get(category, {})
    return [k for k, _ in sorted(cat.items(), key=lambda kv: -kv[1])[:n]]


def avg_prompt_len(data: dict) -> int:
    prompted = sum(data["prompt_len"]["buckets"])
    if not prompted:
        return 0
    return round(data["prompt_len"]["sum"] / prompted)


def render_stats_section(data: dict) -> str:
    """Human-readable digest rendered into the model md (D11)."""
    _ensure_keys(data)
    lines = [f"- Posts seen: {data['count']} "
             f"({data['media'].get('image', 0)} images, "
             f"{data['media'].get('video', 0)} videos)"]
    lines.extend(_render_intel_lines(data))
    avg = avg_prompt_len(data)
    if avg:
        lines.append(f"- Average prompt length: ~{avg} words")
    labels = ["<25", "25–50", "50–100", "100–200", "200–400", "400+"]
    buckets = data["prompt_len"]["buckets"]
    if sum(buckets):
        dist = ", ".join(f"{lab}: {n}" for lab, n in zip(labels, buckets) if n)
        lines.append(f"- Length distribution (words): {dist}")
    for key in ("sampler", "steps", "cfg_scale", "size"):
        hist = data.get("params", {}).get(key)
        if hist:
            top = sorted(hist.items(), key=lambda kv: -kv[1])[:4]
            lines.append(f"- Common {key}: "
                         + ", ".join(f"{v} (×{n})" for v, n in top))
    terms = top_terms(data, 18)
    if terms:
        lines.append("- Frequent descriptors: "
                     + ", ".join(t for t, _ in terms))
    for cat in ("lighting", "palette", "camera", "mood", "style"):
        top_c = top_category(data, cat, 8)
        if top_c:
            lines.append(f"- {cat.title()} vocabulary: " + ", ".join(top_c))
    return "\n".join(lines)


def _top(d: dict, n: int) -> list[tuple[str, int]]:
    return sorted(d.items(), key=lambda kv: -kv[1])[:n]


def _render_intel_lines(data: dict) -> list[str]:
    out = []
    if data.get("structure"):
        total = sum(data["structure"].values()) or 1
        out.append("- Prompt structure: " + ", ".join(
            f"{k} {round(100 * v / total)}%" for k, v in _top(data["structure"], 3)))
    if data.get("aspects"):
        out.append("- Aspect ratios: " + ", ".join(f"{k} ({v})" for k, v in _top(data["aspects"], 5)))
    if data.get("techniques"):
        out.append("- Techniques: " + ", ".join(f"{k} ({v})" for k, v in _top(data["techniques"], 10)))
    cam = _top(data.get("categories", {}).get("camera", {}), 8)
    if cam:
        out.append("- Camera vocabulary: " + ", ".join(k for k, _ in cam))
    light = _top(data.get("categories", {}).get("lighting", {}), 8)
    if light:
        out.append("- Lighting vocabulary: " + ", ".join(k for k, _ in light))
    if data.get("weighted_terms"):
        out.append("- Engagement-weighted terms: " + ", ".join(
            k for k, _ in _top(data["weighted_terms"], 10)))
    refs = data.get("references") or {}
    if refs.get("with") or refs.get("without"):
        out.append(f"- Reference images used in {refs.get('with', 0)} of "
                   f"{refs.get('with', 0) + refs.get('without', 0)} posts")
    if data.get("creators"):
        out.append("- Frequent creators: " + ", ".join(k for k, _ in _top(data["creators"], 6)))
    if data.get("weekly"):
        weeks = sorted(data["weekly"].items())[-6:]
        out.append("- Recent weeks: " + ", ".join(f"{w} {n}" for w, n in weeks))
    return out
