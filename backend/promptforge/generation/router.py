"""Provider registry + cheapest-connected routing (8.3, D29)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..aliases import display_family
from .base import GenerationProvider
from .fal import FalProvider
from .muapi import MuAPIProvider
from .pricing import estimate, family_kind, load_catalog
from .replicate_provider import ReplicateProvider
from .wavespeed import WaveSpeedProvider

_providers: dict[str, GenerationProvider] | None = None


def all_providers() -> dict[str, GenerationProvider]:
    global _providers
    if _providers is None:
        _providers = {p.name: p for p in
                      (FalProvider(), ReplicateProvider(), WaveSpeedProvider(),
                       MuAPIProvider())}
    return _providers


def get_provider(name: str) -> GenerationProvider | None:
    return all_providers().get(name)


def connected_providers(s: Session) -> list[str]:
    return [name for name, p in all_providers().items() if p.is_configured(s)]


def model_options(s: Session, params: dict | None = None) -> dict:
    """Everything the Generate dropdown needs: every catalog family with
    per-provider offers, price estimates and connection state."""
    connected = set(connected_providers(s))
    models = []
    for family, entry in load_catalog().items():
        offers = []
        for provider, p_entry in (entry.get("providers") or {}).items():
            offers.append({
                "provider": provider,
                "provider_model_id": p_entry.get("model_id"),
                "kind": entry.get("kind", "image"),
                "price_estimate": estimate(family, provider, params),
                "connected": provider in connected,
            })
        offers.sort(key=lambda o: (not o["connected"],
                                   o["price_estimate"] if o["price_estimate"]
                                   is not None else 9e9))
        models.append({"family": family, "label": display_family(family),
                       "kind": entry.get("kind", "image"), "offers": offers})
    models.sort(key=lambda m: (m["kind"], m["label"]))
    return {"connected_providers": sorted(connected), "models": models}


def route(s: Session, family: str, params: dict | None = None,
          provider_override: str | None = None) -> tuple[str, str, float | None]:
    """→ (provider, provider_model_id, estimate). Default = cheapest CONNECTED
    provider offering the family; override honored when connected."""
    catalog_entry = load_catalog().get(family)
    if not catalog_entry:
        raise LookupError(
            f"'{family}' isn't in the model catalog — add it under Settings → "
            "AI providers → pricing.")
    offers = catalog_entry.get("providers") or {}
    connected = set(connected_providers(s))

    if provider_override:
        if provider_override not in offers:
            raise LookupError(
                f"{provider_override} doesn't offer '{family}' in the catalog.")
        if provider_override not in connected:
            raise LookupError(
                f"{provider_override} isn't connected — add its API key in "
                "Settings → AI providers.")
        return (provider_override, offers[provider_override]["model_id"],
                estimate(family, provider_override, params))

    candidates = [(p, offers[p]["model_id"], estimate(family, p, params))
                  for p in offers if p in connected]
    if not candidates:
        raise LookupError(
            f"No connected provider offers '{family}'. Connect one of: "
            + ", ".join(offers) + " in Settings → AI providers.")
    candidates.sort(key=lambda c: c[2] if c[2] is not None else 9e9)
    return candidates[0]


def kind_of(family: str) -> str:
    return family_kind(family)
