"""Adapter registry. To add a new site: create the adapter file, then add one
line to _ADAPTER_CLASSES below — pipeline, GUI and schema pick it up untouched."""
from __future__ import annotations

from .base import ScrapedPost, SourceAdapter  # noqa: F401


def _adapter_classes() -> list[type[SourceAdapter]]:
    from .civitai import CivitaiAdapter
    from .lexica import LexicaAdapter
    classes: list[type[SourceAdapter]] = [CivitaiAdapter, LexicaAdapter]
    try:
        from .midjourney import MidjourneyAdapter
        from .tensorart import TensorArtAdapter
        from .seaart import SeaArtAdapter
        from .pixai import PixAIAdapter
        classes += [MidjourneyAdapter, TensorArtAdapter, SeaArtAdapter, PixAIAdapter]
    except ImportError:
        pass  # Tier 2 files land in Phase 5
    return classes


_instances: dict[str, SourceAdapter] | None = None


def all_adapters() -> dict[str, SourceAdapter]:
    global _instances
    if _instances is None:
        _instances = {}
        for cls in _adapter_classes():
            inst = cls()
            _instances[inst.name] = inst
    return _instances


def get_adapter(name: str) -> SourceAdapter | None:
    return all_adapters().get(name)
