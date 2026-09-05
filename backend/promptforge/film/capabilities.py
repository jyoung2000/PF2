"""Provider capability matrix (spec §8, §22, N, P): what each CONNECTED
provider can actually do, read from the pricing catalog's declared `modes`.
A mode that no connected provider declares is reported as unsupported with
the reason — never faked. Audio/talking-head/lip-sync flags are false until
a provider adapter declares them."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..aliases import display_family
from ..generation import pricing
from ..generation import router as gen_router

MODES: list[dict] = [
    {"key": "text_to_image", "label": "Text → Image", "kind": "image", "needs": []},
    {"key": "image_to_image", "label": "Image → Image", "kind": "image", "needs": ["image"]},
    {"key": "reference_to_image", "label": "Reference → Image", "kind": "image", "needs": ["references"]},
    {"key": "storyboard_to_image", "label": "Storyboard → Image", "kind": "image", "needs": ["image"]},
    {"key": "text_to_video", "label": "Text → Video", "kind": "video", "needs": []},
    {"key": "image_to_video", "label": "Image → Video", "kind": "video", "needs": ["image"]},
    {"key": "start_end_to_video", "label": "Start/End → Video", "kind": "video", "needs": ["image", "end_image"]},
    {"key": "reference_to_video", "label": "Reference → Video", "kind": "video", "needs": ["references"]},
    {"key": "storyboard_to_video", "label": "Storyboard/Grid → Video", "kind": "video", "needs": ["image"]},
]
MODE_KINDS = {m["key"]: m["kind"] for m in MODES}
# served by the same provider endpoint, with the storyboard frame / reference as the image input
ALIASES = {"storyboard_to_image": "image_to_image", "storyboard_to_video": "image_to_video",
           "reference_to_video": "image_to_video"}
BASE_MODE = {"image": "text_to_image", "video": "text_to_video"}

# capabilities no shipped adapter declares yet — reported honestly as unsupported
EXTRA_CAPABILITIES = {
    "tts": "No configured provider declares text-to-speech.",
    "music": "No configured provider declares music generation.",
    "sfx": "No configured provider declares sound-effect generation.",
    "audio_enhance": "No configured provider declares audio enhancement.",
    "talking_head": "No configured provider declares talking-head / avatar generation.",
    "lip_sync": "No configured provider declares lip sync.",
    "inpainting": "No configured provider declares masked inpainting.",
    "upscale": "No configured provider declares upscaling.",
    "remove_background": "No configured provider declares background removal.",
    "transcription": "No configured provider declares speech-to-text.",
}
LOCAL_CAPABILITIES = {   # things PF2 does itself with ffmpeg/Pillow — always available when ffmpeg is present
    "still_to_video": "Ken Burns still → video (ffmpeg)",
    "motion_graphics": "Title cards, lower thirds, captions (Pillow + ffmpeg)",
    "concat_export": "Timeline export with gaps, fades, dissolves, audio mix (ffmpeg)",
    "subtitles": "SRT/VTT + burn-in (ffmpeg)",
    "last_frame": "Previous-shot last-frame extraction (ffmpeg)",
    "technical_qa": "ffprobe / black-frame / freeze detection (ffmpeg)",
}


def resolve_mode(mode: str) -> str:
    return ALIASES.get(mode, mode)


def offers(s: Session, kind: str | None = None) -> list[dict]:
    """Every family × provider in the catalog with its declared modes."""
    connected = set(gen_router.connected_providers(s))
    out = []
    for family, entry in pricing.load_catalog().items():
        fkind = entry.get("kind", "image")
        if kind and fkind != kind:
            continue
        for provider, p_entry in (entry.get("providers") or {}).items():
            modes = {BASE_MODE[fkind]: p_entry.get("model_id")}
            for mkey, m in (p_entry.get("modes") or {}).items():
                if isinstance(m, dict) and m.get("model_id"):
                    modes[mkey] = m["model_id"]
            out.append({"family": family, "label": display_family(family), "kind": fkind,
                        "provider": provider, "connected": provider in connected,
                        "modes": modes, "base_model_id": p_entry.get("model_id")})
    return out


def supports(s: Session, family: str, provider: str, mode: str) -> str | None:
    """Model id when this offer declares the (aliased) mode, else None."""
    real = resolve_mode(mode)
    for o in offers(s):
        if o["family"] == family and o["provider"] == provider:
            return o["modes"].get(real)
    return None


def inputs_map(family: str, provider: str, mode: str) -> dict:
    m = pricing.modes_for(family, provider).get(resolve_mode(mode)) or {}
    return dict(m.get("inputs") or {})


def modes_available(s: Session, kind: str | None = None, connected_only: bool = True) -> dict[str, list[str]]:
    """mode → [families] for connected providers (plus aliases)."""
    out: dict[str, set[str]] = {}
    for o in offers(s, kind):
        if connected_only and not o["connected"]:
            continue
        for m in o["modes"]:
            out.setdefault(m, set()).add(o["family"])
    for alias, real in ALIASES.items():
        if real in out and (kind is None or MODE_KINDS[alias] == kind):
            out.setdefault(alias, set()).update(out[real])
    return {k: sorted(v) for k, v in out.items()}


def matrix(s: Session) -> dict:
    providers = {}
    for name, p in gen_router.all_providers().items():
        providers[name] = {"label": p.label, "connected": p.is_configured(s), "key_url": p.key_url}
    available = modes_available(s)
    modes = []
    for m in MODES:
        fams = available.get(m["key"], [])
        modes.append({**m, "supported": bool(fams), "families": fams,
                      "reason": None if fams else "No connected provider declares this mode — connect one in "
                                                  "Settings → AI providers or add it to the pricing catalog."})
    import shutil
    ffmpeg = shutil.which("ffmpeg") is not None
    return {"providers": providers, "modes": modes, "offers": offers(s),
            "extra": {k: {"supported": False, "reason": v} for k, v in EXTRA_CAPABILITIES.items()},
            "local": {k: {"supported": ffmpeg, "what": v} for k, v in LOCAL_CAPABILITIES.items()},
            "ffmpeg": ffmpeg}
