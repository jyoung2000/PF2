"""Intent extraction (spec §3): deterministic, evidence-tagged parsing of a
free-text brief into the constraints that drive routing and compilation.
No LLM here — every inference quotes the text that produced it, matching the
house style of intel/extract.py."""
from __future__ import annotations

import re

VIDEO_RE = re.compile(
    r"\b(video|trailer|clip|animation|animated|footage|b-?roll|shorts?|reel|"
    r"time-?lapse|hyperlapse|cinemagraph|motion)\b", re.I)
# "music player / music app" is a product being depicted, not an audio ask
AUDIO_RE = re.compile(
    r"\b(narrat(?:e|ion)|voice-?over|speech|spoken|song|jingle|sound ?track|audio|"
    r"music(?!\s+(?:player|app|library|store|video)))\b", re.I)
THREED_RE = re.compile(r"\b(3d model|3d asset|mesh|glb|gltf|obj file|point cloud|3d)\b", re.I)
IMAGE_RE = re.compile(
    r"\b(image|photo(?:graph)?|picture|poster|logo|illustration|render|artwork|"
    r"wallpaper|thumbnail|icon|banner|graphic|screenshot|key art)\b", re.I)

DURATION_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*[- ]?(?:s\b|secs?\b|seconds?\b)", re.I)
RATIO_RE = re.compile(r"\b(\d{1,2})\s*[:x]\s*(\d{1,2})\b")
RES_RE = re.compile(r"\b(480p|540p|720p|1080p|1440p|4k|8k)\b", re.I)
COUNT_RE = re.compile(r"\b(\d+)\s+(?:variations?|versions?|options?|images?|frames?)\b", re.I)
BUDGET_CAP_RE = re.compile(r"under\s*\$\s*(\d+(?:\.\d+)?)", re.I)
QUOTED_RE = re.compile(r"[\"“”']([^\"“”']{2,60})[\"“”']")
AVOID_RE = re.compile(r"\b(?:no|without|avoid|never)\s+((?:\w+[ -]?){1,3}\w)", re.I)

# "portrait of a …" is a genre, not an orientation — the lookahead excludes it
RATIO_WORDS = [
    (re.compile(r"\b(vertical|portrait(?!\s+of\b))\b", re.I), "9:16"),
    (re.compile(r"\bsquare\b", re.I), "1:1"),
    (re.compile(r"\b(landscape|widescreen|horizontal)\b", re.I), "16:9"),
    (re.compile(r"\b(anamorphic|ultra-?wide)\b", re.I), "21:9"),
]
CONSISTENCY_RE = re.compile(
    r"(same character|consistent character|character consistency|same person|"
    r"same subject|across (?:all )?(?:the )?(?:shots|scenes|frames|images)|recurring character)", re.I)
REFS_RE = re.compile(
    r"(this image|attached|my (?:photo|logo|product|brand)|based on the|"
    r"reference image|use my|in the style of my)", re.I)
BUDGET_RE = re.compile(r"\b(cheap(?:est|ly)?|budget|low[- ]cost|free|inexpensive)\b", re.I)

STYLES = [
    "cinematic", "photorealistic", "photoreal", "realistic", "anime", "manga",
    "watercolor", "oil painting", "noir", "editorial", "brutalist", "minimalist",
    "pixel art", "low-poly", "isometric", "vaporwave", "cyberpunk", "steampunk",
    "art deco", "vintage", "retro", "surreal", "abstract", "cartoon", "3d render",
    "claymation", "stop motion", "documentary", "hand-drawn", "sketch", "flat design",
]

# things typography-capable models should handle
TEXTY_RE = re.compile(r"\b(text|typography|title|headline|caption|words?|lettering|logo)\b", re.I)


def _ev(match: re.Match | None, text: str) -> str | None:
    if not match:
        return None
    lo = max(0, match.start() - 20)
    return text[lo:match.end() + 20].strip()


def extract(brief: str) -> dict:
    """→ IntentSpec: every inferred field carries the evidence snippet that
    produced it; absent evidence means the field stays null/False."""
    text = brief or ""
    out: dict = {"brief": text, "evidence": {}}

    m3, mv, ma, mi = THREED_RE.search(text), VIDEO_RE.search(text), AUDIO_RE.search(text), IMAGE_RE.search(text)
    dur = DURATION_RE.search(text)
    if m3:
        out["modality"] = "3d"
        out["evidence"]["modality"] = _ev(m3, text)
    elif mv or (dur and not mi and not ma):
        out["modality"] = "video"
        out["evidence"]["modality"] = _ev(mv or dur, text)
    elif ma and not mi:
        out["modality"] = "audio"
        out["evidence"]["modality"] = _ev(ma, text)
    else:
        out["modality"] = "image"
        if mi:
            out["evidence"]["modality"] = _ev(mi, text)

    if dur:
        out["duration_s"] = float(dur.group(1))
        out["evidence"]["duration_s"] = _ev(dur, text)

    ratio = RATIO_RE.search(text)
    if ratio and 1 <= int(ratio.group(1)) <= 32 and 1 <= int(ratio.group(2)) <= 32:
        out["aspect_ratio"] = f"{int(ratio.group(1))}:{int(ratio.group(2))}"
        out["evidence"]["aspect_ratio"] = _ev(ratio, text)
    else:
        # first orientation word by position in the text wins
        hits = [(mw.start(), mw, value) for rx, value in RATIO_WORDS
                if (mw := rx.search(text))]
        if hits:
            _, mw, value = min(hits, key=lambda h: h[0])
            out["aspect_ratio"] = value
            out["evidence"]["aspect_ratio"] = _ev(mw, text)

    res = RES_RE.search(text)
    if res:
        out["resolution"] = res.group(1).lower()
        out["evidence"]["resolution"] = _ev(res, text)

    styles = [st for st in STYLES if re.search(rf"\b{re.escape(st)}\b", text, re.I)]
    if styles:
        out["styles"] = styles
        out["evidence"]["styles"] = styles

    cons = CONSISTENCY_RE.search(text)
    out["character_consistency"] = bool(cons)
    if cons:
        out["evidence"]["character_consistency"] = _ev(cons, text)
    refs = REFS_RE.search(text)
    out["references_needed"] = bool(refs or cons)
    if refs:
        out["evidence"]["references_needed"] = _ev(refs, text)

    cap = BUDGET_CAP_RE.search(text)
    budget = BUDGET_RE.search(text)
    out["budget_sensitive"] = bool(budget or cap)
    if cap:
        out["budget_cap_usd"] = float(cap.group(1))
        out["evidence"]["budget"] = _ev(cap, text)
    elif budget:
        out["evidence"]["budget"] = _ev(budget, text)

    count = COUNT_RE.search(text)
    if count and 1 < int(count.group(1)) <= 20:
        out["count"] = int(count.group(1))
        out["evidence"]["count"] = _ev(count, text)

    quoted = QUOTED_RE.findall(text)
    if quoted and TEXTY_RE.search(text):
        out["text_content"] = quoted[:3]
        out["evidence"]["text_content"] = quoted[:3]
    out["needs_typography"] = bool(out.get("text_content"))

    avoids = [a.strip() for a in AVOID_RE.findall(text)]
    if avoids:
        out["avoid"] = avoids[:6]
        out["evidence"]["avoid"] = avoids[:6]

    return out


def to_params(intent: dict) -> dict:
    """The generation params an intent implies (validated per family later)."""
    params: dict = {}
    for key in ("aspect_ratio", "resolution", "duration_s"):
        if intent.get(key) is not None:
            params[key] = intent[key]
    return params
