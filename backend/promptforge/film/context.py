"""Canonical visual context (spec §11): the machine-readable, per-version
description that the Storyboard and Director consume — never just a
paragraph. Deterministic, so the same version always yields the same
context and the same prose."""
from __future__ import annotations

from . import attributes, storage


def _present(v) -> bool:
    return v not in (None, "", [], {})


def _fmt(v) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {x}" for k, x in v.items())
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def build(asset, version, refs: list | None = None) -> dict:
    """asset: FilmAsset, version: FilmAssetVersion, refs: FilmAssetRef rows
    visible to this version (asset-wide + version-specific)."""
    atype = asset.type
    data = dict(version.data or {})
    locked_groups = attributes.valid_locks(atype, version.locks)
    group_of = attributes.field_group_map(atype)
    labels = {f["key"]: f["label"] for f in attributes.known_fields(atype)}

    locked_attrs: list[dict] = []
    for g in locked_groups:
        for f in attributes.fields_of_group(atype, g):
            if _present(data.get(f)):
                locked_attrs.append({"group": g, "field": f,
                                     "label": labels.get(f, f), "value": data[f]})
    variable_attrs = [{"field": f, "label": labels.get(f, f), "value": v,
                       "group": group_of.get(f)}
                      for f, v in data.items()
                      if _present(v) and group_of.get(f) not in locked_groups]

    anchors = [a for a in (version.identity_anchors or []) if isinstance(a, str) and a.strip()]
    if not anchors:
        anchors = [asset.name] + [f"{a['label'].lower()}: {_fmt(a['value'])}"
                                  for a in locked_attrs][:8]

    ref_rows = refs or []
    references = [{"id": r.id, "kind": r.kind, "label": r.label,
                   "url": storage.url_for(r.path), "thumb_url": storage.url_for(r.thumb_path),
                   "primary": r.id == version.primary_ref_id}
                  for r in ref_rows]
    primary = next((r for r in references if r["primary"]), references[0] if references else None)

    return {
        "asset_id": asset.id,
        "version_id": version.id,
        "version": version.number,
        "version_label": version.label or f"v{version.number}",
        "type": atype,
        "name": asset.name,
        "description": asset.description,
        "identity_anchors": anchors,
        "visual_description": {f: v for f, v in data.items() if _present(v)},
        "references": references,
        "primary_reference": primary,
        "locked_groups": locked_groups,
        "locked_attributes": locked_attrs,
        "variable_attributes": variable_attrs,
        "continuity_rules": list(version.continuity_rules or []),
        "negative_constraints": list(version.negative_constraints or []),
        "frozen": bool(version.frozen),
        "provenance": dict(version.provenance or {}),
    }


def describe(ctx: dict, include_variables: bool = True, max_chars: int = 1200) -> str:
    """One deterministic paragraph for prompts: name, locked attributes
    first (they are constraints), then variable attributes, rules."""
    parts: list[str] = [f"{ctx['name']} ({ctx['type']} {ctx.get('version_label', '')}".rstrip() + ")"]
    if ctx.get("description"):
        parts.append(str(ctx["description"]).strip())
    locked = [f"{a['label'].lower()}: {_fmt(a['value'])}" for a in ctx.get("locked_attributes", [])]
    if locked:
        parts.append("LOCKED — " + "; ".join(locked))
    if include_variables:
        var = [f"{a['label'].lower()}: {_fmt(a['value'])}" for a in ctx.get("variable_attributes", [])]
        if var:
            parts.append("; ".join(var))
    if ctx.get("continuity_rules"):
        parts.append("Continuity: " + "; ".join(str(r) for r in ctx["continuity_rules"]))
    if ctx.get("negative_constraints"):
        parts.append("Never: " + "; ".join(str(r) for r in ctx["negative_constraints"]))
    text = ". ".join(p.rstrip(".") for p in parts if p) + "."
    return text[:max_chars]
