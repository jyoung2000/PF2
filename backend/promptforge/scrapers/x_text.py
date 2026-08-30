"""Deterministic prompt/model extraction from freeform tweet text (X1.2, D51).

X strips image metadata and rarely carries structured prompts, so this module
mines the tweet text (+ quoted text) with rules only — labels, fenced/quoted
blocks, model keywords, hashtags. NO LLM here, ever (iron rule); optional AI
cleanup of low-confidence prompts belongs to the knowledge engine."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# keyword -> canonical model name. Prefix semantics (see detect_model):
#   "#word"  = exact hashtag   |   " word " (leading space) = whole-word token
#   bare     = substring (safe only for distinctive multi-char names)
MODEL_KEYWORDS: list[tuple[str, str]] = [
    ("midjourney", "Midjourney"),
    (" niji ", "Niji"),
    (" mj ", "Midjourney"),
    ("#mj", "Midjourney"),
    (" flux ", "Flux"),          # token: 'influx' must not match
    ("flux.1", "Flux"),
    ("#flux", "Flux"),
    (" sora ", "Sora"),
    ("#sora", "Sora"),
    (" veo ", "Veo"),
    ("veo 3", "Veo"),
    ("veo3", "Veo"),
    (" kling ", "Kling"),        # token: 'sparkling' must not match
    ("#kling", "Kling"),
    ("wan 2", "Wan"),
    ("wan2", "Wan"),
    ("#wan", "Wan"),
    ("seedance", "Seedance"),
    ("seedream", "Seedream"),
    ("grok imagine", "Grok Imagine"),
    ("nano banana", "Nano Banana"),
    ("nanobanana", "Nano Banana"),
    ("hailuo", "Hailuo"),
    ("minimax", "Hailuo"),
    ("runway", "Runway"),
    ("gen-3", "Runway"),
    ("gen-4", "Runway"),
    (" pika ", "Pika"),          # token: 'pikachu' must not match
    ("#pika", "Pika"),
    (" luma ", "Luma"),
    ("dream machine", "Luma"),
    ("hunyuan", "Hunyuan"),
    ("sdxl", "SDXL"),
    ("stable diffusion", "Stable Diffusion"),
    ("dall-e", "DALL·E"),
    ("dalle", "DALL·E"),
    ("ideogram", "Ideogram"),
    ("recraft", "Recraft"),
    (" imagen ", "Imagen"),
    ("firefly", "Firefly"),
    (" ltx ", "LTX Video"),
    ("cogvideo", "CogVideo"),
    (" pony ", "Pony"),          # token: 'ponytail' must not match
    ("illustrious", "Illustrious"),
    (" qwen ", "Qwen Image"),
    ("hidream", "HiDream"),
]

_URL_RE = re.compile(r"https?://\S+")
_WS_RE = re.compile(r"[ \t]+")
_HASHTAG_RE = re.compile(r"#(\w+)")
_MENTION_EDGE_RE = re.compile(r"^(?:@\w+\s+)+")
_FENCE_RE = re.compile(r"```(?:\w+\n)?(.+?)```", re.S)
_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:full\s+)?(?:prompt|prompts)\s*(?:used)?\s*[:\-–>]\s*(.+?)"
    r"(?=\n\s*(?:negative|neg|model|settings|seed|params|cfg|steps|ar|sref)\s*[:\-–]|\n\n|\Z)",
    re.I | re.S)
_NEG_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:negative|neg)(?:\s+prompt)?\s*[:\-–]\s*(.+?)(?=\n\n|\n\s*\w+\s*[:\-–]|\Z)",
    re.I | re.S)
_CURLY_QUOTE_RE = re.compile(r"[“\"']([^”\"']{25,900})[”\"']", re.S)


@dataclass
class ExtractedPrompt:
    prompt: str | None = None
    negative: str | None = None
    model_name: str | None = None
    model_stated: bool = False
    prompt_confidence: str = "low"   # high | low
    hashtags: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    text = _URL_RE.sub("", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = _WS_RE.sub(" ", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _strip_decorations(text: str) -> str:
    """Drop leading mentions and pure-hashtag tails from a prompt candidate."""
    text = _MENTION_EDGE_RE.sub("", text.strip())
    lines = text.split("\n")
    while lines and lines[-1].strip() and all(
            tok.startswith(("#", "@")) for tok in lines[-1].split()):
        lines.pop()
    text = "\n".join(lines).strip()
    # trailing run of hashtags on the same line
    text = re.sub(r"(?:\s+[#@]\w+)+\s*$", "", text).strip()
    return text.strip(" -–—:")


def detect_model(*texts: str | None) -> str | None:
    blob = " " + " ".join(t.lower() for t in texts if t) + " "
    blob = re.sub(r"[^\w#.\- ]+", " ", blob)
    for keyword, name in MODEL_KEYWORDS:
        if keyword.startswith("#"):          # exact hashtag
            if re.search(rf"{re.escape(keyword)}\b", blob):
                return name
        elif keyword.startswith(" "):        # whole-word token
            if f" {keyword.strip()} " in blob:
                return name
        elif keyword in blob:                # plain substring
            return name
    return None


def extract(text: str, quoted_text: str | None = None) -> ExtractedPrompt:
    """Mine tweet text (+ quoted tweet text) for prompt/negative/model."""
    out = ExtractedPrompt()
    raw = text or ""
    out.hashtags = [h.lower() for h in _HASHTAG_RE.findall(raw)]
    cleaned = _clean(raw)
    quoted_clean = _clean(quoted_text) if quoted_text else None

    model = detect_model(cleaned, quoted_clean,
                         " ".join("#" + h for h in out.hashtags))
    if model:
        out.model_name = model
        out.model_stated = True

    for source in (cleaned, quoted_clean):
        if not source:
            continue
        # 1) fenced block
        m = _FENCE_RE.search(source)
        if m and len(m.group(1).strip()) >= 12:
            out.prompt = _strip_decorations(m.group(1))
            out.prompt_confidence = "high"
            break
        # 2) "Prompt:" label
        m = _LABEL_RE.search(source)
        if m and len(m.group(1).strip()) >= 8:
            out.prompt = _strip_decorations(m.group(1))
            out.prompt_confidence = "high"
            break
        # 3) long quoted block
        m = _CURLY_QUOTE_RE.search(source)
        if m:
            out.prompt = _strip_decorations(m.group(1))
            out.prompt_confidence = "high"
            break

    # negative prompt label anywhere
    for source in (cleaned, quoted_clean):
        if not source:
            continue
        m = _NEG_LABEL_RE.search(source)
        if m and m.group(1).strip():
            out.negative = _strip_decorations(m.group(1))
            break

    if out.prompt is None:
        # fallback: the whole tweet text, decorations stripped — low confidence
        fallback = _strip_decorations(cleaned)
        out.prompt = fallback or None
        out.prompt_confidence = "low"
    return out
