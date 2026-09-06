"""Tiny shared helpers for engine schemas (I8).

Extraction schemas travel through PF2 as plain dicts:
    {"fields": {"title": "string", "url": "string", "likes": "integer"},
     "many": true}
and are turned into pydantic models for the engines that want typed output.
"""
from __future__ import annotations

from pydantic import BaseModel, create_model

_TYPES = {"string": (str | None, None), "integer": (int | None, None),
          "number": (float | None, None), "boolean": (bool | None, None),
          "list": (list | None, None)}


def field_model(name: str, fields: dict) -> type[BaseModel]:
    spec = {k: _TYPES.get(str(v).lower(), (str | None, None)) for k, v in (fields or {}).items()}
    if not spec:
        spec = {"text": (str | None, None)}
    return create_model(name, **spec)  # type: ignore[call-overload]


def result_model(schema: dict | None) -> type[BaseModel]:
    """The model an engine should return: {"items": [Row, ...]} when
    schema.many, else a single Row."""
    schema = schema or {}
    row = field_model("Row", schema.get("fields") or {})
    if schema.get("many", True):
        return create_model("Rows", items=(list[row], ...))  # type: ignore[call-overload]
    return row


def rows_from(data, schema: dict | None) -> list[dict]:
    """Normalise engine output back to a list of dicts."""
    if data is None:
        return []
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        return [r for r in data["items"] if isinstance(r, dict)]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []
