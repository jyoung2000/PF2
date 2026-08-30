"""Model catalog + pricing (8.2, D16): seeded pricing.json copied to DATA_DIR
on first boot (GUI-editable copy wins). Estimate math: images per-image or
per-megapixel; video per-second × resolution tier."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..config import get_config

_SEED = Path(__file__).resolve().parents[3] / "pricing.json"


def pricing_path() -> Path:
    return get_config().data_dir / "pricing.json"


def install_pricing() -> None:
    dest = pricing_path()
    if not dest.exists() and _SEED.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_SEED, dest)


def load_catalog() -> dict:
    install_pricing()
    path = pricing_path() if pricing_path().exists() else _SEED
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        data = {}
    return data.get("families", {})


def save_catalog(families: dict) -> None:
    path = pricing_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text())
        except ValueError:
            current = {}
    current["families"] = families
    path.write_text(json.dumps(current, indent=2))


def family_kind(family: str) -> str:
    entry = load_catalog().get(family) or {}
    return entry.get("kind", "image")


def _nearest_resolution_price(prices: dict, resolution: str | None) -> float | None:
    """prices: {"720p": 0.1, ...}. Falls back to the closest available tier."""
    if not prices:
        return None
    if resolution and resolution in prices:
        return float(prices[resolution])
    def tier(res: str) -> int:
        digits = "".join(ch for ch in res if ch.isdigit())
        return int(digits) if digits else 0
    want = tier(resolution or "720p")
    best = min(prices, key=lambda r: abs(tier(r) - want))
    return float(prices[best])


def estimate(family: str, provider: str, params: dict | None = None) -> float | None:
    """Expected price for one generation, or None when unknown."""
    params = params or {}
    entry = (load_catalog().get(family) or {}).get("providers", {}).get(provider)
    if not entry:
        return None
    kind = family_kind(family)
    if kind == "video":
        duration = float(params.get("duration_s") or params.get("duration") or 5)
        per_second = entry.get("price_per_second")
        if isinstance(per_second, dict):
            unit = _nearest_resolution_price(per_second, params.get("resolution"))
        else:
            unit = float(per_second) if per_second is not None else None
        if unit is None:
            return None
        return round(unit * duration, 4)
    if entry.get("price_per_image") is not None:
        return round(float(entry["price_per_image"]), 4)
    if entry.get("price_per_mp") is not None:
        size = str(params.get("size") or "1024x1024")
        try:
            w, h = (int(x) for x in size.lower().split("x"))
        except ValueError:
            w = h = 1024
        return round(float(entry["price_per_mp"]) * (w * h) / 1_000_000, 4)
    return None
