"""Model Intelligence Registry (spec §2): a normalized, provider-agnostic
catalog of model families merged live with the pricing catalog's offers,
connection state and this library's own observations.

The seed `models_catalog.json` follows the pricing.json lifecycle (D16): it
is copied to DATA_DIR on first boot, the user copy is GUI-editable and wins,
and new seed families/fields merge in additively — a user edit is never
overwritten. Metadata is data, not code: nothing here is hard-coded into UI
components, and unknown stays null rather than invented.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..aliases import display_family
from ..config import get_config
from ..generation import pricing
from ..generation import router as gen_router
from ..knowledge import files as kfiles
from ..models import Post

def _find_seed() -> Path:
    """The repo root differs between a source checkout and the image layout,
    so check both. A missing seed used to silently degrade to 'no models'."""
    here = Path(__file__).resolve()
    for parent in here.parents[2:5]:
        candidate = parent / "models_catalog.json"
        if candidate.exists():
            return candidate
    return here.parents[3] / "models_catalog.json"


_SEED = _find_seed()

MODALITIES = ("image", "video", "audio", "3d")

# Every §2 field the schema carries; _defaults() fills what an entry omits so
# consumers can rely on the shape even for user-added families.
SUPPORT_FLAGS = ("reference_images", "image_to_image", "image_to_video",
                 "start_end_frames", "audio", "multi_reference",
                 "character_consistency", "editing", "enhancement",
                 "negative_prompt")


def _defaults() -> dict:
    return {
        "id": None, "canonical_name": None,
        "display_name": None, "modality": "image", "tasks": [],
        "input_types": ["text"], "output_types": ["image"],
        "availability": "cloud", "free_tier": None, "latency_class": None,
        "quality_prior": None, "context_window": None,
        "aspect_ratios": None, "resolutions": None, "max_duration_s": None,
        "supports": {k: False for k in SUPPORT_FLAGS},
        "licensing": None, "commercial_use": None, "local_hardware": None,
        "prompt": {"style": "natural_language", "camera_language": False,
                   "max_terms": None, "notes": None},
        "strengths": [], "weaknesses": [], "fallback_families": [],
        "api_available": None, "deprecation": None,
        # provenance (Phase 2): where a fact came from and how much to trust it
        "source_urls": [], "evidence": None, "confidence": None,
        "last_verified": None, "source": None,
    }


def catalog_path() -> Path:
    return get_config().data_dir / "models_catalog.json"


def install_catalog() -> None:
    dest = catalog_path()
    if not dest.exists() and _SEED.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_SEED, dest)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text()).get("families", {}) or {}
    except (ValueError, OSError):
        return {}


def load_families() -> dict:
    """User copy merged additively over the seed: seed families the copy
    lacks are added whole; per-family, seed fields the copy lacks are filled
    in (a user-edited value is never replaced)."""
    install_catalog()
    seed = _read(_SEED)
    user = _read(catalog_path()) if catalog_path().exists() else {}
    merged: dict = {}
    for family in {**seed, **user}:
        s_entry = seed.get(family) or {}
        u_entry = user.get(family) if family in user else None
        entry = dict(_defaults())
        for src in (s_entry, u_entry or {}):
            for k, v in src.items():
                if k in ("supports", "prompt") and isinstance(v, dict):
                    entry[k] = {**entry[k], **v}
                else:
                    entry[k] = v
        merged[family] = entry
    return merged


def save_family(family: str, patch: dict) -> dict:
    """Persist a user edit into the DATA_DIR copy (whole-entry replace of the
    known fields; unknown keys are dropped so the schema stays clean)."""
    install_catalog()
    path = catalog_path()
    try:
        doc = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        doc = {}
    doc.setdefault("families", {})
    current = load_families().get(family) or _defaults()
    allowed = set(_defaults())
    for k, v in patch.items():
        if k not in allowed:
            continue
        if k in ("supports", "prompt") and isinstance(v, dict):
            current[k] = {**current[k], **v}
        else:
            current[k] = v
    doc["families"][family] = current
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1))
    return current


# ------------------------------------------------------------- the registry --
def _observed(s: Session) -> dict[str, dict]:
    rows = s.execute(
        select(Post.model_family, func.count(Post.id), func.max(Post.scraped_at))
        .where(Post.model_family.is_not(None)).group_by(Post.model_family)).all()
    return {fam: {"post_count": count, "last_seen": last.isoformat() if last else None}
            for fam, count, last in rows}


def registry(s: Session, modality: str | None = None) -> list[dict]:
    """Every family the intelligence catalog or the pricing catalog knows,
    with metadata + live offers (provider, model id, price, declared modes,
    connected) + what this installation has observed."""
    families = load_families()
    price_cat = pricing.load_catalog()
    connected = set(gen_router.connected_providers(s))
    observed = _observed(s)
    out = []
    for family in sorted({*families, *price_cat}):
        meta = families.get(family) or _defaults()
        p_entry = price_cat.get(family) or {}
        if not meta.get("display_name"):
            meta = {**meta, "display_name": display_family(family)}
        if not meta.get("id"):
            meta = {**meta, "id": family}
        if family in price_cat and family not in families:
            meta = {**meta, "modality": p_entry.get("kind", "image")}
        if modality and meta["modality"] != modality:
            continue
        offers = []
        for provider, offer in (p_entry.get("providers") or {}).items():
            modes = sorted((offer.get("modes") or {}).keys())
            offers.append({
                "provider": provider,
                "provider_model_id": offer.get("model_id"),
                "modes": modes,
                "price_estimate": pricing.estimate(family, provider, None),
                "connected": provider in connected,
            })
        offers.sort(key=lambda o: (not o["connected"],
                                   o["price_estimate"] if o["price_estimate"] is not None else 9e9))
        out.append({
            "family": family, **meta,
            "offers": offers,
            "generatable": any(o["connected"] for o in offers),
            "observed": observed.get(family),
            "knowledge_file": kfiles.model_file_path(family).exists(),
        })
    out.sort(key=lambda e: (e["modality"], e["display_name"] or e["family"]))
    return out


def entry(s: Session, family: str) -> dict | None:
    for e in registry(s):
        if e["family"] == family:
            return e
    return None


# --------------------------------------------------------- capability layer --
def _parse_ratio(value: str) -> float | None:
    try:
        w, h = value.replace("x", ":").split(":")
        return float(w) / float(h)
    except (ValueError, ZeroDivisionError, AttributeError):
        return None


def validate_params(family: str, params: dict, mode: str | None = None) -> dict:
    """ParameterValidator (§2): check requested parameters against what the
    family declares. → {ok, violations, warnings, params} where `params` has
    hard caps applied (the caller decides whether to use the clamped copy).
    Unknown metadata never fails validation — null means unverified."""
    meta = load_families().get(family)
    violations: list[dict] = []
    warnings: list[str] = []
    cleaned = dict(params or {})
    if meta is None:
        return {"ok": True, "violations": [],
                "warnings": [f"'{family}' has no intelligence entry — parameters unchecked"],
                "params": cleaned}

    ar = cleaned.get("aspect_ratio")
    if ar and meta.get("aspect_ratios"):
        supported = meta["aspect_ratios"]
        if ar not in supported:
            want = _parse_ratio(str(ar))
            nearest = None
            if want:
                ratios = [(r, _parse_ratio(r)) for r in supported]
                ratios = [(r, v) for r, v in ratios if v]
                if ratios:
                    nearest = min(ratios, key=lambda rv: abs(rv[1] - want))[0]
            violations.append({"param": "aspect_ratio", "requested": ar,
                               "supported": supported, "nearest": nearest,
                               "message": f"{meta['display_name'] or family} does not list {ar}"
                                          + (f" — nearest supported is {nearest}" if nearest else "")})

    dur = cleaned.get("duration_s") or cleaned.get("duration")
    cap = meta.get("max_duration_s")
    if dur is not None and cap is not None:
        try:
            if float(dur) > float(cap):
                violations.append({"param": "duration_s", "requested": dur, "supported": cap,
                                   "message": f"max duration is {cap}s — request will be clamped"})
                cleaned["duration_s"] = float(cap)
                cleaned.pop("duration", None)
        except (TypeError, ValueError):
            pass

    refs = cleaned.get("_inputs", {}).get("references") if isinstance(cleaned.get("_inputs"), dict) else None
    if refs:
        if not meta["supports"].get("reference_images"):
            violations.append({"param": "references", "requested": len(refs), "supported": 0,
                               "message": "this family does not declare reference-image support"})
        elif len(refs) > 1 and not meta["supports"].get("multi_reference"):
            warnings.append("multiple references given but only single-reference support is declared "
                            "— extras may be ignored")

    neg = cleaned.get("negative_prompt")
    if neg and not meta["supports"].get("negative_prompt"):
        warnings.append("negative prompts are not supported — constraints will be folded into the "
                        "positive prompt instead")

    if mode:
        task_aliases = {"image_to_image": "image_to_image", "image_to_video": "image_to_video",
                        "start_end_to_video": "start_end_frames", "reference_to_image": "reference_images",
                        "reference_to_video": "reference_images"}
        flag = task_aliases.get(mode)
        if flag and not meta["supports"].get(flag):
            warnings.append(f"'{mode}' is not declared in this family's capabilities — "
                            "the provider offer decides at execution time")

    return {"ok": not violations, "violations": violations,
            "warnings": warnings, "params": cleaned}


def providers_overview(s: Session) -> list[dict]:
    """ProviderRegistry (§2/§12): every configured or configurable execution
    backend with its class (paid cloud / free-local LLM / built-in local)."""
    out = []
    for name, p in gen_router.all_providers().items():
        out.append({"name": name, "label": p.label, "kind": "generation",
                    "free": False, "local": False,
                    "configured": p.is_configured(s), "key_setting": p.key_setting,
                    "key_url": p.key_url})
    from ..llm.client import FREE_PROVIDERS
    from .. import settings_store
    llm_provider = settings_store.get(s, "llm_provider") or ""
    for name, label in (("ollama", "Ollama (local)"), ("companion", "Desktop companion"),
                        ("anthropic", "Anthropic"), ("openai", "OpenAI-compatible"),
                        ("grok", "Grok (xAI)")):
        out.append({"name": name, "label": label, "kind": "llm",
                    "free": name in FREE_PROVIDERS, "local": name in ("ollama", "companion"),
                    "configured": llm_provider == name, "key_setting": None, "key_url": None})
    import shutil as _sh
    out.append({"name": "ffmpeg", "label": "Local media tools (ffmpeg + Pillow)", "kind": "local",
                "free": True, "local": True, "configured": _sh.which("ffmpeg") is not None,
                "key_setting": None, "key_url": None})
    return out
