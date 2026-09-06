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
    ("pixverse", "PixVerse"),
    ("vidu", "Vidu"),
    ("higgsfield", "Higgsfield"),
    ("moonvalley", "Marey"),
    (" marey ", "Marey"),
    ("omnihuman", "OmniHuman"),
    ("skyreels", "SkyReels"),
    ("framepack", "FramePack"),
    ("gpt image", "GPT Image"),
    ("gpt-image", "GPT Image"),
    ("z-image", "Z-Image"),
    ("flux kontext", "Flux"),
    ("flux krea", "Flux"),
    ("magi-1", "MAGI"),
]


# --- X-specific surface, now backed by the shared parser (I9, spec §156) ----
# The generic miner lives in intel/prompt_parser.py; X keeps this thin module
# so the adapter and its tests stay unchanged while every source shares one
# implementation. MODEL_KEYWORDS above is the vocabulary the shared detector
# reads, so extending it benefits every platform at once.


@dataclass
class ExtractedPrompt:
    prompt: str | None = None
    negative: str | None = None
    model_name: str | None = None
    model_stated: bool = False
    prompt_confidence: str = "low"   # high | low
    hashtags: list[str] = field(default_factory=list)


def detect_model(*texts: str | None) -> str | None:
    from ..intel import prompt_parser
    return prompt_parser.detect_model(*texts)


def extract(text: str, quoted_text: str | None = None) -> ExtractedPrompt:
    """Mine tweet text (+ quoted tweet text) for prompt/negative/model."""
    from ..intel import prompt_parser
    parsed = prompt_parser.parse(text, quoted_text=quoted_text, location="caption",
                                 platform="x")
    prompt = parsed.prompt
    if prompt is None:
        # X historically always kept a low-confidence fallback: the whole
        # tweet text with decorations stripped.
        prompt = prompt_parser.strip_decorations(prompt_parser.clean(text)) or None
    return ExtractedPrompt(
        prompt=prompt, negative=parsed.negative, model_name=parsed.model_name,
        model_stated=parsed.model_stated,
        prompt_confidence="high" if parsed.is_explicit else "low",
        hashtags=parsed.hashtags)
