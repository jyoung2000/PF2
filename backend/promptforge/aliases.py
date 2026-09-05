"""Model alias normalization (D7): map the many spellings of a model name to
one canonical family slug. Seeded defaults + user rules from settings
(`model_aliases`: {"substring": "family"}). Unknown models fall back to a slug
of their own cleaned name, so brand-new models become their own family with
zero code changes."""
from __future__ import annotations

import re

# Ordered: first match wins. Keys are substrings matched against the cleaned
# (lowercase, punctuation→space) name.
DEFAULT_RULES: list[tuple[str, str]] = [
    ("flux", "flux"),
    ("niji", "niji"),
    ("midjourney", "midjourney"),
    (" mj ", "midjourney"),
    ("pony", "pony"),
    ("illustrious", "illustrious"),
    ("noobai", "noobai"),
    ("sdxl", "sdxl"),
    ("sd xl", "sdxl"),
    ("stable diffusion xl", "sdxl"),
    ("stable diffusion 3", "sd3"),
    ("sd3", "sd3"),
    ("sd 3", "sd3"),
    ("stable diffusion 1", "sd15"),
    ("sd 1 5", "sd15"),
    ("sd1 5", "sd15"),
    ("sd15", "sd15"),
    ("stable diffusion 2", "sd2"),
    ("stable diffusion", "sd15"),
    ("stable cascade", "stable-cascade"),
    ("cascade", "stable-cascade"),
    ("dall e", "dall-e"),
    ("dalle", "dall-e"),
    ("gpt image", "gpt-image"),
    ("imagen", "imagen"),
    ("ideogram", "ideogram"),
    ("recraft", "recraft"),
    ("seedream", "seedream"),
    ("seedance", "seedance"),
    ("qwen", "qwen-image"),
    ("chroma", "chroma"),
    ("auraflow", "auraflow"),
    ("aura flow", "auraflow"),
    ("kolors", "kolors"),
    ("playground", "playground"),
    ("hidream", "hidream"),
    ("grok imagine", "grok-imagine"),
    ("grok image", "grok-imagine"),
    ("aurora", "grok-imagine"),
    ("nano banana", "nano-banana"),
    ("nanobanana", "nano-banana"),
    ("firefly", "firefly"),
    ("lumina", "lumina"),
    ("pixart", "pixart"),
    ("sana", "sana"),
    ("sora", "sora"),
    ("veo", "veo"),
    ("kling", "kling"),
    ("runway", "runway"),
    ("gen 3", "runway"),
    ("gen 4", "runway"),
    ("pika", "pika"),
    ("hunyuan", "hunyuan"),
    ("wan", "wan"),
    ("luma", "luma"),
    ("dream machine", "luma"),
    ("ray2", "luma"),
    ("hailuo", "hailuo"),
    ("minimax", "hailuo"),
    ("mochi", "mochi"),
    ("ltx", "ltx-video"),
    ("cogvideo", "cogvideo"),
    ("animatediff", "animatediff"),
    ("svd", "svd"),
    ("stable video", "svd"),
    ("pixverse", "pixverse"),
    ("vidu", "vidu"),
    ("higgsfield", "higgsfield"),
    ("marey", "marey"),
    ("moonvalley", "marey"),
    ("omnihuman", "omnihuman"),
    ("magi", "magi"),
    ("skyreels", "skyreels"),
    ("framepack", "framepack"),
    ("cosmos", "cosmos"),
    ("z image", "z-image"),
    ("zimage", "z-image"),
]

DISPLAY_NAMES = {
    "flux": "Flux", "sdxl": "SDXL", "sd15": "SD 1.5", "sd2": "SD 2.x",
    "sd3": "SD 3.x", "midjourney": "Midjourney", "niji": "Niji",
    "pony": "Pony", "illustrious": "Illustrious", "noobai": "NoobAI",
    "dall-e": "DALL·E", "gpt-image": "GPT Image", "imagen": "Imagen",
    "ideogram": "Ideogram", "recraft": "Recraft", "seedream": "Seedream",
    "seedance": "Seedance", "qwen-image": "Qwen Image", "chroma": "Chroma",
    "auraflow": "AuraFlow", "kolors": "Kolors", "playground": "Playground",
    "hidream": "HiDream", "lumina": "Lumina", "pixart": "PixArt",
    "sana": "Sana", "sora": "Sora", "veo": "Veo", "kling": "Kling",
    "runway": "Runway", "pika": "Pika", "hunyuan": "Hunyuan", "wan": "Wan",
    "pixverse": "PixVerse", "vidu": "Vidu", "higgsfield": "Higgsfield",
    "marey": "Marey (Moonvalley)", "omnihuman": "OmniHuman", "magi": "MAGI",
    "skyreels": "SkyReels", "framepack": "FramePack", "cosmos": "Cosmos",
    "z-image": "Z-Image",
    "luma": "Luma", "hailuo": "Hailuo", "mochi": "Mochi",
    "ltx-video": "LTX Video", "cogvideo": "CogVideo",
    "animatediff": "AnimateDiff", "svd": "SVD",
    "stable-cascade": "Stable Cascade",
    "grok-imagine": "Grok Imagine", "nano-banana": "Nano Banana",
    "firefly": "Firefly",
}

_clean_re = re.compile(r"[^a-z0-9]+")


def _clean(name: str) -> str:
    return " " + _clean_re.sub(" ", name.lower()).strip() + " "


def normalize_model(name: str | None, user_rules: dict[str, str] | None = None) -> str | None:
    """Return the canonical family slug for a raw model name, or None."""
    if not name or not name.strip():
        return None
    cleaned = _clean(name)
    if user_rules:
        for sub, family in user_rules.items():
            if _clean(sub).strip() and _clean(sub).strip() in cleaned:
                return family.strip().lower()
    for sub, family in DEFAULT_RULES:
        needle = sub if sub.startswith(" ") else sub.strip()
        if f" {needle} " in cleaned or needle in cleaned.strip():
            # substring match against cleaned text
            if needle in cleaned or f" {needle} " in cleaned:
                return family
    # Unknown model: it becomes its own family (slug of cleaned name)
    slug = _clean_re.sub("-", name.lower()).strip("-")
    return slug or None


def display_family(family: str | None) -> str:
    if not family:
        return "Unknown"
    return DISPLAY_NAMES.get(family, family.replace("-", " ").title())
