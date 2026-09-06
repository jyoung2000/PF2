"""Platform-neutral prompt intelligence (Inspiration 2.0, I9/I11;
spec §19–§25, §92, §117–§123, §156–§159).

The deterministic prompt miner every source shares. It grew out of the
X-only `scrapers/x_text.py` (which now delegates here) and understands:

- labelled prompts ("Prompt:", "full prompt —", "positive:"), fenced blocks,
  long quoted blocks, structured source fields;
- negative prompts and inline parameters (seed/steps/cfg/sampler/--ar/--v…);
- model names + versions through the existing alias vocabulary;
- LOOSE prompt-shaped prose (§118) — scored, never promoted to "the prompt";
- FRAGMENTS across a caption + its replies/comments, assembled with
  per-fragment provenance (§22, §92);
- video vs image component vocabulary (§23/§24) for downstream knowledge.

Two absolutes:
  1. NEVER invent a prompt (§21). Text that was not published stays absent;
     what we assemble is labelled `reconstructed`, what a model guesses is
     labelled `inferred`, and both keep the source fragments.
  2. Source precedence (§122) is enforced by `stronger_source()` — a weaker
     writer never overwrites a stronger one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..aliases import normalize_model
from ..knowledge import techniques

# ---- prompt source ladder (§20/§122): strongest first ----------------------
PROMPT_SOURCES = (
    "embedded_metadata",     # PNG/EXIF/ComfyUI workflow shipped with the media
    "structured_api",        # a real prompt field in the source's own API
    "explicit_workflow",     # a linked/attached workflow file
    "explicit_caption",      # labelled prompt in the post text
    "explicit_thread",       # labelled prompt in the CREATOR's own reply/thread
    "explicit_comment",      # labelled prompt in someone else's comment
    "assembled",             # fragments joined by us (reconstructed)
    "deterministic_inference",  # prompt-shaped prose, rules only
    "ai_extraction",         # an LLM read the page and quoted text
    "ai_inference",          # an LLM guessed a plausible prompt
    "unknown",
)
_RANK = {name: len(PROMPT_SOURCES) - i for i, name in enumerate(PROMPT_SOURCES)}

# confidence attached to each source when we assert a prompt
SOURCE_CONFIDENCE = {
    "embedded_metadata": 1.0, "structured_api": 0.98, "explicit_workflow": 0.97,
    "explicit_caption": 0.95, "explicit_thread": 0.92, "explicit_comment": 0.85,
    "assembled": 0.8, "deterministic_inference": 0.45, "ai_extraction": 0.55,
    "ai_inference": 0.3, "unknown": 0.2,
}


def stronger_source(new: str | None, existing: str | None) -> bool:
    """True when `new` may overwrite `existing` (§122)."""
    return _RANK.get(new or "unknown", 0) > _RANK.get(existing or "unknown", 0)


# ---- regexes ---------------------------------------------------------------
_URL_RE = re.compile(r"https?://\S+")
_WS_RE = re.compile(r"[ \t]+")
_HASHTAG_RE = re.compile(r"#(\w+)")
_MENTION_EDGE_RE = re.compile(r"^(?:@\w+\s+)+")
_FENCE_RE = re.compile(r"```(?:\w+\n)?(.+?)```", re.S)
_LABEL_RE = re.compile(
    r"(?:^|\n|[—–|•]\s*|\.\s+)\s*(?:full\s+|positive\s+|final\s+)?(?:prompt|prompts)\s*(?:used|text)?\s*"
    r"[:\-–>]\s*(.+?)"
    r"(?=\n\s*(?:negative|neg|model|settings|seed|params|cfg|steps|ar|sref|sampler|"
    r"scheduler|lora|workflow)\s*[:\-–]|\n\n|\Z)", re.I | re.S)
_NEG_LABEL_RE = re.compile(
    r"(?:^|\n|[—–|•]\s*)\s*(?:negative|neg)(?:\s+prompt)?\s*[:\-–]\s*(.+?)"
    r"(?=\n\n|\n\s*\w+\s*[:\-–]|\Z)", re.I | re.S)
_CURLY_QUOTE_RE = re.compile(r"[“\"']([^”\"']{25,900})[”\"']", re.S)
# "prompt in the comments" / "workflow on my site" pointers (§76)
_POINTER_RE = re.compile(
    r"\b(prompt|prompts|workflow|settings|recipe)\b[^.\n]{0,30}\b"
    r"(in|below|under|see)\b[^.\n]{0,20}\b(comment|comments|reply|replies|thread|bio|link)\b",
    re.I)

_PARAM_RES: list[tuple[str, re.Pattern]] = [
    ("seed", re.compile(r"\bseed\s*[:=]?\s*(\d{1,20})\b", re.I)),
    ("steps", re.compile(r"\bsteps?\s*[:=]?\s*(\d{1,3})\b", re.I)),
    ("cfg_scale", re.compile(r"\b(?:cfg|guidance)(?:\s*scale)?\s*[:=]?\s*(\d{1,2}(?:\.\d)?)\b", re.I)),
    ("sampler", re.compile(r"\bsampler\s*[:=]?\s*([\w+ .-]{3,30})", re.I)),
    ("scheduler", re.compile(r"\bscheduler\s*[:=]?\s*([\w+ .-]{3,20})", re.I)),
    ("aspect_ratio", re.compile(r"(?:--ar|\baspect(?:\s*ratio)?\s*[:=]?)\s*(\d{1,2}\s*[:x]\s*\d{1,2})", re.I)),
    ("denoise", re.compile(r"\bdenois(?:e|ing)(?:\s*strength)?\s*[:=]?\s*(0?\.\d+|\d)\b", re.I)),
    ("duration_s", re.compile(r"\b(\d{1,3})\s*(?:s|sec|secs|seconds)\b(?=[^\w]|$)", re.I)),
    ("fps", re.compile(r"\b(\d{1,3})\s*fps\b", re.I)),
]
_MJ_FLAG_RE = re.compile(r"--(\w+)(?:\s+([^\s-][^\s]*))?")
_LORA_RE = re.compile(r"<lora:([^:>]+)(?::([\d.]+))?>|(?:\blora\s*[:=]\s*)([\w .-]{3,40})", re.I)

# §23 video-first components / §24 image components — vocabulary only, the
# knowledge engine owns their meaning
_VIDEO_HINTS = re.compile(
    r"\b(dolly|truck|pan|tilt|crane|jib|handheld|steadicam|gimbal|orbit|"
    r"push in|pull out|zoom|tracking shot|slow motion|timelapse|time-lapse|"
    r"hyperlapse|first frame|last frame|start frame|end frame|i2v|img2vid|"
    r"image to video|video to video|v2v|keyframe|loop|transition|camera move)\b", re.I)
_IMAGE_HINTS = re.compile(
    r"\b(controlnet|lora|checkpoint|vae|upscal|inpaint|outpaint|img2img|"
    r"txt2img|refiner|clip skip|hires fix|sref|cref|style ref)\b", re.I)


@dataclass
class Fragment:
    """One piece of published evidence for a prompt (§22/§92)."""
    text: str
    source: str                      # explicit_caption | explicit_comment | …
    location: str = "caption"        # caption | comment | reply | description | metadata
    confidence: float = 0.9
    ref: str | None = None           # comment id / url of the exact fragment
    author_is_creator: bool | None = None

    def as_dict(self) -> dict:
        return {"text": self.text[:2000], "source": self.source, "location": self.location,
                "confidence": round(self.confidence, 2), "ref": self.ref,
                "author_is_creator": self.author_is_creator}


@dataclass
class ParsedPrompt:
    prompt: str | None = None
    negative: str | None = None
    model_name: str | None = None
    model_family: str | None = None
    model_stated: bool = False
    prompt_source: str = "unknown"
    confidence: float = 0.0
    method: str = "none"             # labelled | fenced | quoted | paragraph | assembled | none
    params: dict = field(default_factory=dict)
    components: dict = field(default_factory=dict)
    hashtags: list[str] = field(default_factory=list)
    fragments: list[Fragment] = field(default_factory=list)
    wants_comments: bool = False     # the post says the prompt lives in replies
    notes: list[str] = field(default_factory=list)

    @property
    def is_explicit(self) -> bool:
        return self.prompt_source.startswith("explicit") or self.prompt_source in (
            "embedded_metadata", "structured_api", "explicit_workflow")

    def as_dict(self) -> dict:
        return {"prompt": self.prompt, "negative_prompt": self.negative,
                "model_name": self.model_name, "model_family": self.model_family,
                "model_stated": self.model_stated, "prompt_source": self.prompt_source,
                "confidence": round(self.confidence, 2), "method": self.method,
                "params": self.params, "components": self.components,
                "hashtags": self.hashtags, "wants_comments": self.wants_comments,
                "fragments": [f.as_dict() for f in self.fragments], "notes": self.notes}


# ---- cleaning --------------------------------------------------------------
def clean(text: str | None) -> str:
    text = _URL_RE.sub("", text or "")
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'"))
    text = _WS_RE.sub(" ", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def strip_decorations(text: str) -> str:
    text = _MENTION_EDGE_RE.sub("", (text or "").strip())
    lines = text.split("\n")
    while lines and lines[-1].strip() and all(
            tok.startswith(("#", "@")) for tok in lines[-1].split()):
        lines.pop()
    text = "\n".join(lines).strip()
    text = re.sub(r"(?:\s+[#@]\w+)+\s*$", "", text).strip()
    return text.strip(" -–—:")


# ---- model detection (shared vocabulary) -----------------------------------
def detect_model(*texts: str | None) -> str | None:
    from ..scrapers.x_text import MODEL_KEYWORDS
    blob = " " + " ".join(t.lower() for t in texts if t) + " "
    blob = re.sub(r"[^\w#.\- ]+", " ", blob)
    for keyword, name in MODEL_KEYWORDS:
        if keyword.startswith("#"):
            if re.search(rf"{re.escape(keyword)}\b", blob):
                return name
        elif keyword.startswith(" "):
            if f" {keyword.strip()} " in blob:
                return name
        elif keyword in blob:
            return name
    return None


# ---- parameters + components ----------------------------------------------
def detect_params(text: str | None) -> dict:
    out: dict = {}
    if not text:
        return out
    for key, pat in _PARAM_RES:
        m = pat.search(text)
        if not m:
            continue
        raw = m.group(1).strip()
        if key in ("seed", "steps", "fps", "duration_s"):
            try:
                out[key] = int(raw)
            except ValueError:
                continue
        elif key in ("cfg_scale", "denoise"):
            try:
                out[key] = float(raw)
            except ValueError:
                continue
        else:
            out[key] = raw
    for flag, value in _MJ_FLAG_RE.findall(text):
        low = flag.lower()
        if low in ("ar", "v", "niji", "s", "stylize", "chaos", "c", "q", "seed", "sref", "cref", "no"):
            out.setdefault("mj_flags", {})[low] = value or True
    loras = [m[0] or m[2] for m in _LORA_RE.findall(text) if (m[0] or m[2])]
    if loras:
        out["loras"] = sorted({l.strip() for l in loras})[:8]
    return out


def detect_components(text: str | None) -> dict:
    """Video/image vocabulary present in the text (§23/§24). Evidence only —
    the knowledge engine decides what it means."""
    if not text:
        return {}
    from . import extract as intel_extract
    out: dict = {}
    camera = intel_extract.detect_camera(text)
    if camera:
        out["camera"] = camera
    lighting = [x["value"] for x in intel_extract.detect_lighting(text)]
    if lighting:
        out["lighting"] = lighting
    composition = [x["value"] for x in intel_extract.detect_composition(text)]
    if composition:
        out["composition"] = composition
    tech = techniques.detect_techniques(text)
    if tech:
        out["techniques"] = tech
    motion = sorted({m.group(0).lower() for m in _VIDEO_HINTS.finditer(text)})
    if motion:
        out["motion"] = motion[:10]
    image_terms = sorted({m.group(0).lower() for m in _IMAGE_HINTS.finditer(text)})
    if image_terms:
        out["image_pipeline"] = image_terms[:10]
    return out


# ---- loose prompt scoring (§118) -------------------------------------------
_PROMPT_ISH = re.compile(
    r"\b(cinematic|photoreal|photorealistic|render|4k|8k|hdr|bokeh|depth of field|"
    r"volumetric|anamorphic|lens|shot on|wide angle|close-up|portrait of|"
    r"in the style of|highly detailed|masterpiece|ultra detailed|golden hour|"
    r"neon|studio lighting|rim light|film grain|35mm|50mm|85mm)\b", re.I)


def loose_prompt_score(text: str | None) -> float:
    """0–1: how prompt-shaped is this prose? Used ONLY to decide whether to
    keep a low-confidence `deterministic_inference` candidate (§118)."""
    if not text:
        return 0.0
    words = text.split()
    if len(words) < 5:
        return 0.0
    score = 0.0
    hits = len(set(m.group(0).lower() for m in _PROMPT_ISH.finditer(text)))
    score += min(0.5, hits * 0.12)
    commas = text.count(",")
    if commas >= 3:
        score += 0.2
    elif commas >= 1:
        score += 0.1
    if 8 <= len(words) <= 120:
        score += 0.15
    if not re.search(r"[?!]|\b(I|we|you|my|our)\b", text):
        score += 0.1                      # descriptive, not conversational
    if re.search(r"\b(check|thread|follow|link in bio|retweet|subscribe)\b", text, re.I):
        score -= 0.25
    return max(0.0, min(1.0, score))


# ---- the parser ------------------------------------------------------------
def _find_labelled(source: str) -> tuple[str, str] | None:
    """(prompt, method) from the strongest labelled form present."""
    m = _FENCE_RE.search(source)
    if m and len(m.group(1).strip()) >= 12:
        return strip_decorations(m.group(1)), "fenced"
    m = _LABEL_RE.search(source)
    if m and len(m.group(1).strip()) >= 8:
        return strip_decorations(m.group(1)), "labelled"
    m = _CURLY_QUOTE_RE.search(source)
    if m:
        return strip_decorations(m.group(1)), "quoted"
    return None


def parse(text: str | None, *, quoted_text: str | None = None,
          location: str = "caption", platform: str | None = None,
          allow_loose: bool = True, ref: str | None = None) -> ParsedPrompt:
    """Mine ONE piece of text. `location` becomes the fragment/source label."""
    out = ParsedPrompt()
    raw = text or ""
    out.hashtags = [h.lower() for h in _HASHTAG_RE.findall(raw)]
    cleaned = clean(raw)
    quoted_clean = clean(quoted_text) if quoted_text else None
    blob = "\n".join(x for x in (cleaned, quoted_clean) if x)

    model = detect_model(cleaned, quoted_clean, " ".join("#" + h for h in out.hashtags))
    if model:
        out.model_name = model
        out.model_family = normalize_model(model)
        out.model_stated = True

    out.params = detect_params(blob)
    out.components = detect_components(blob)
    out.wants_comments = bool(_POINTER_RE.search(blob))

    explicit_source = {"caption": "explicit_caption", "comment": "explicit_comment",
                       "reply": "explicit_comment", "thread": "explicit_thread",
                       "description": "explicit_caption",
                       "metadata": "embedded_metadata"}.get(location, "explicit_caption")

    for source_text in (cleaned, quoted_clean):
        if not source_text:
            continue
        found = _find_labelled(source_text)
        if found:
            out.prompt, out.method = found
            out.prompt_source = explicit_source
            out.confidence = SOURCE_CONFIDENCE[explicit_source]
            break

    for source_text in (cleaned, quoted_clean):
        if not source_text:
            continue
        m = _NEG_LABEL_RE.search(source_text)
        if m and m.group(1).strip():
            out.negative = strip_decorations(m.group(1))
            break

    if out.prompt is None and allow_loose:
        candidate = strip_decorations(cleaned)
        score = loose_prompt_score(candidate)
        if candidate and score >= 0.35:
            out.prompt = candidate
            out.method = "paragraph"
            out.prompt_source = "deterministic_inference"
            out.confidence = round(min(0.6, 0.3 + score * 0.4), 2)
            out.notes.append(
                f"prompt-shaped text (score {score:.2f}) — not a labelled prompt")
        elif candidate:
            out.notes.append("no prompt evidence in this text")

    if out.prompt:
        out.fragments.append(Fragment(
            text=out.prompt, source=out.prompt_source, location=location,
            confidence=out.confidence, ref=ref))
        # a prompt body can carry params/components the surrounding text lacked
        out.params = {**detect_params(out.prompt), **out.params}
        out.components = {**detect_components(out.prompt), **out.components}
    return out


def parse_thread(caption: str | None, replies: list[dict] | None = None, *,
                 platform: str | None = None, quoted_text: str | None = None,
                 creator: str | None = None) -> ParsedPrompt:
    """Caption + its replies/comments → one ParsedPrompt with fragments and,
    when the pieces are genuinely split, an ASSEMBLED prompt (§22).

    `replies` are dicts like {text, author, id, url, is_creator}. Only the
    creator's own replies may contribute prompt text; other people's comments
    can still supply model/params evidence but never the prompt itself."""
    base = parse(caption, quoted_text=quoted_text, location="caption", platform=platform)
    creator_low = (creator or "").lstrip("@").lower()
    author_pieces: list[ParsedPrompt] = []

    for r in replies or []:
        rtext = r.get("text") or ""
        if not rtext.strip():
            continue
        is_creator = r.get("is_creator")
        if is_creator is None and creator_low:
            is_creator = (r.get("author") or "").lstrip("@").lower() == creator_low
        loc = "thread" if is_creator else "comment"
        sub = parse(rtext, location=loc, platform=platform,
                    allow_loose=bool(is_creator) and base.prompt is None,
                    ref=str(r.get("id") or r.get("url") or "") or None)
        for frag in sub.fragments:
            frag.author_is_creator = bool(is_creator)
        # model/params evidence is welcome from anyone
        if sub.model_name and not base.model_name:
            base.model_name, base.model_family = sub.model_name, sub.model_family
            base.model_stated = True
        base.params = {**sub.params, **base.params}
        for k, v in sub.components.items():
            base.components.setdefault(k, v)
        if not base.negative and sub.negative:
            base.negative = sub.negative
        if sub.prompt and is_creator:
            author_pieces.append(sub)
            base.fragments.extend(sub.fragments)

    if not author_pieces:
        return base

    if base.prompt is None:
        best = max(author_pieces, key=lambda p: (p.is_explicit, p.confidence, len(p.prompt or "")))
        base.prompt, base.method = best.prompt, best.method
        base.prompt_source = best.prompt_source
        base.confidence = best.confidence
        base.notes.append("prompt came from the creator's own reply, not the post")
        return base

    # genuinely split across post + author replies ⇒ reconstruct, and say so
    extra = [p for p in author_pieces
             if p.prompt and p.prompt.strip() not in (base.prompt or "")
             and p.is_explicit]
    if extra:
        parts = [base.prompt] + [p.prompt for p in extra if p.prompt]
        base.prompt = "\n".join(dict.fromkeys(parts))
        base.prompt_source = "assembled"
        base.method = "assembled"
        base.confidence = min(SOURCE_CONFIDENCE["assembled"], base.confidence)
        base.notes.append(
            f"reconstructed from {len(parts)} published fragments (post + "
            f"{len(parts) - 1} creator repl{'y' if len(parts) == 2 else 'ies'})")
    return base


def extract_prompt(content: dict, context: dict | None = None) -> ParsedPrompt:
    """The public entry (§159). `content` may carry any of:
        text/caption/title/description, quoted_text, replies[], structured
        (a source's own prompt fields), metadata (embedded generation data).
    `context` may carry platform, creator, media_type, is_ai_native.

    Precedence is enforced: an embedded/structured prompt wins over anything
    mined from text, and the mined evidence is still recorded as fragments."""
    context = context or {}
    platform = context.get("platform")
    creator = context.get("creator")
    text = "\n\n".join(x for x in (
        content.get("title"), content.get("text") or content.get("caption"),
        content.get("description")) if x)
    out = parse_thread(text, content.get("replies"), platform=platform,
                       quoted_text=content.get("quoted_text"), creator=creator)

    structured = content.get("structured") or {}
    metadata = content.get("metadata") or {}
    for payload, source in ((metadata, "embedded_metadata"), (structured, "structured_api")):
        prompt = (payload.get("prompt") or "").strip() if payload.get("prompt") else None
        if not prompt:
            continue
        if stronger_source(source, out.prompt_source):
            if out.prompt and out.prompt.strip() != prompt:
                out.fragments.append(Fragment(
                    text=out.prompt, source=out.prompt_source, location="caption",
                    confidence=out.confidence))
            out.prompt = prompt
            out.prompt_source = source
            out.method = "structured"
            out.confidence = SOURCE_CONFIDENCE[source]
            out.fragments.insert(0, Fragment(text=prompt, source=source, location="metadata",
                                             confidence=out.confidence))
        if payload.get("negative_prompt") and not out.negative:
            out.negative = payload["negative_prompt"]
        for key in ("seed", "steps", "cfg_scale", "sampler", "scheduler", "model", "loras"):
            if payload.get(key) is not None:
                out.params.setdefault(key, payload[key])
        if payload.get("model") and not out.model_stated:
            out.model_name = str(payload["model"])
            out.model_family = normalize_model(out.model_name)
            out.model_stated = True
    if out.prompt:
        out.components = {**detect_components(out.prompt), **out.components}
    return out
