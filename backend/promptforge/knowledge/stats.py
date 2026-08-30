"""Deterministic learning layer (6.3, D11) — zero AI cost, runs on every
ingest. Per-family JSON under DATA_DIR/knowledge/stats/{family}.json:
term/descriptor frequencies (categorized), prompt-length distribution,
parameter histograms. Capped so files stay tiny."""
from __future__ import annotations

import json
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
               "85mm", "35mm", "50mm", "24mm", "bokeh", "depth of field",
               "fisheye", "anamorphic", "aerial", "drone", "pov", "top-down",
               "isometric", "portrait", "profile", "framing", "f/1", "f/2"],
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


_PARAM_TRACK = ("steps", "cfg_scale", "sampler", "size", "scheduler")


def update_family_stats(family: str, prompt: str | None, params: dict | None,
                        media_type: str, post_id: int | None = None) -> dict:
    with _lock:
        data = load_stats(family)
        data["count"] += 1
        data["media"][media_type] = data["media"].get(media_type, 0) + 1
        if prompt:
            words = len(prompt.split())
            data["prompt_len"]["sum"] += words
            for i, (lo, hi) in enumerate(LEN_BUCKETS):
                if lo <= words < hi:
                    data["prompt_len"]["buckets"][i] += 1
                    break
            for phrase in extract_phrases(prompt):
                _bump(data["terms"], phrase)
                _bump(data["categories"].setdefault(categorize(phrase), {}), phrase,
                      cap=120, prune_at=200)
        for key in _PARAM_TRACK:
            val = (params or {}).get(key)
            if val in (None, ""):
                continue
            bucket = data["params"].setdefault(key, {})
            _bump(bucket, str(val), cap=40, prune_at=60)
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
    lines = [f"- Posts seen: {data['count']} "
             f"({data['media'].get('image', 0)} images, "
             f"{data['media'].get('video', 0)} videos)"]
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
