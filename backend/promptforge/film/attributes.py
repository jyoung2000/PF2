"""Per-type structured attribute schemas (spec §4–6, §10, AH): sections and
fields drive the visual editors, lock groups drive the 🔒 toggles and the
Director's constraints, reference kinds drive the reference tabs. Versions
store `data` as a flat {field: value} dict — unknown keys are kept, never
discarded."""
from __future__ import annotations

from copy import deepcopy

TIME_OF_DAY = ["dawn", "morning", "midday", "afternoon", "golden hour", "dusk",
               "blue hour", "night", "late night"]
WEATHER = ["clear", "overcast", "fog", "rain", "storm", "snow", "wind", "haze", "smoke"]


def _f(key: str, label: str, kind: str = "text", **extra) -> dict:
    d = {"key": key, "label": label, "type": kind}
    d.update(extra)
    return d


ASSET_SCHEMAS: dict[str, dict] = {
    "character": {
        "label": "Character", "plural": "Characters", "children": "outfit",
        "sections": [
            {"key": "identity", "label": "Identity", "fields": [
                _f("age", "Age"), _f("role", "Role"),
                _f("personality", "Personality", "textarea"),
                _f("description", "Description", "textarea")]},
            {"key": "appearance", "label": "Appearance", "fields": [
                _f("face_shape", "Face shape"), _f("eyes", "Eyes"),
                _f("eye_color", "Eye color"), _f("brows", "Brows"), _f("nose", "Nose"),
                _f("mouth", "Mouth"), _f("skin", "Skin"), _f("hair", "Hair"),
                _f("facial_hair", "Facial hair"),
                _f("distinctive_features", "Distinctive features", "textarea"),
                _f("height", "Height"), _f("body_type", "Body type"), _f("posture", "Posture")]},
            {"key": "clothing", "label": "Clothing", "fields": [
                _f("default_outfit", "Default outfit", "asset", asset_type="outfit")]},
        ],
        "lock_groups": [
            {"key": "face", "label": "Face", "default": True,
             "fields": ["face_shape", "eyes", "eye_color", "brows", "nose", "mouth",
                        "skin", "distinctive_features"]},
            {"key": "hair", "label": "Hair", "default": True, "fields": ["hair", "facial_hair"]},
            {"key": "body", "label": "Body", "default": True,
             "fields": ["height", "body_type", "posture"]},
            {"key": "clothing", "label": "Clothing", "default": False, "fields": ["default_outfit"]},
            {"key": "expression", "label": "Expression", "default": False, "fields": [], "shot_level": True},
            {"key": "pose", "label": "Pose", "default": False, "fields": [], "shot_level": True},
        ],
        "ref_kinds": ["portrait", "front", "three_quarter", "side", "back", "full_body",
                      "expression_sheet", "character_sheet", "custom"],
    },
    "location": {
        "label": "Location", "plural": "Locations",
        "sections": [
            {"key": "structure", "label": "Structure", "fields": [
                _f("architecture", "Architecture", "textarea"), _f("layout", "Layout", "textarea"),
                _f("materials", "Materials"), _f("furniture", "Furniture", "textarea"),
                _f("windows", "Windows"), _f("doors", "Doors")]},
            {"key": "conditions", "label": "Conditions", "fields": [
                _f("environment", "Environment", "textarea"),
                _f("time_of_day", "Time of day", "select", options=TIME_OF_DAY),
                _f("weather", "Weather", "select", options=WEATHER),
                _f("lighting", "Lighting", "textarea"), _f("atmosphere", "Atmosphere"),
                _f("color_palette", "Color palette")]},
            {"key": "world", "label": "World reference", "fields": [
                _f("zones", "Zones / rooms", "list"), _f("entrances", "Entrances / exits", "list"),
                _f("landmarks", "Landmarks", "list"), _f("camera_areas", "Camera-friendly areas", "list"),
                _f("map_ref_id", "Map / diagram reference", "ref")]},
        ],
        "lock_groups": [
            {"key": "architecture", "label": "Architecture", "default": True, "fields": ["architecture"]},
            {"key": "layout", "label": "Layout", "default": True,
             "fields": ["layout", "zones", "entrances", "landmarks", "map_ref_id"]},
            {"key": "materials", "label": "Materials", "default": True, "fields": ["materials"]},
            {"key": "furniture", "label": "Furniture", "default": True, "fields": ["furniture", "windows", "doors"]},
            {"key": "environment", "label": "Environment", "default": False, "fields": ["environment"]},
            {"key": "lighting", "label": "Lighting", "default": False, "fields": ["lighting"]},
            {"key": "weather", "label": "Weather", "default": False, "fields": ["weather"]},
            {"key": "time_of_day", "label": "Time of day", "default": False, "fields": ["time_of_day"]},
            {"key": "atmosphere", "label": "Atmosphere", "default": False, "fields": ["atmosphere"]},
            {"key": "palette", "label": "Palette", "default": False, "fields": ["color_palette"]},
        ],
        "ref_kinds": ["exterior", "interior", "wide", "close_detail", "alternate_angle",
                      "day", "night", "map", "custom"],
    },
    "prop": {
        "label": "Prop", "plural": "Props",
        "sections": [{"key": "appearance", "label": "Appearance", "fields": [
            _f("description", "Description", "textarea"), _f("material", "Material"),
            _f("color", "Color"), _f("size", "Size"), _f("condition", "Condition"),
            _f("distinctive_features", "Distinctive features"), _f("usage", "How it is used")]}],
        "lock_groups": [
            {"key": "appearance", "label": "Appearance", "default": True,
             "fields": ["description", "material", "color", "size", "distinctive_features"]},
            {"key": "condition", "label": "Condition", "default": False, "fields": ["condition"]}],
        "ref_kinds": ["main", "detail", "alternate", "custom"],
    },
    "vehicle": {
        "label": "Vehicle", "plural": "Vehicles",
        "sections": [{"key": "appearance", "label": "Appearance", "fields": [
            _f("vehicle_type", "Type"), _f("make_model", "Make / model"), _f("era", "Era"),
            _f("color", "Color"), _f("condition", "Condition"), _f("interior", "Interior", "textarea"),
            _f("distinctive_features", "Distinctive features")]}],
        "lock_groups": [
            {"key": "appearance", "label": "Appearance", "default": True,
             "fields": ["vehicle_type", "make_model", "era", "color", "distinctive_features"]},
            {"key": "interior", "label": "Interior", "default": True, "fields": ["interior"]},
            {"key": "condition", "label": "Condition", "default": False, "fields": ["condition"]}],
        "ref_kinds": ["exterior", "interior", "detail", "alternate", "custom"],
    },
    "outfit": {
        "label": "Outfit", "plural": "Outfits", "parent": "character",
        "sections": [{"key": "garments", "label": "Garments", "fields": [
            _f("description", "Description", "textarea"), _f("garments", "Garments", "list"),
            _f("colors", "Colors"), _f("materials", "Materials"), _f("accessories", "Accessories"),
            _f("condition", "Condition"),
            _f("is_default", "Default outfit for the character", "bool")]}],
        "lock_groups": [
            {"key": "appearance", "label": "Appearance", "default": True,
             "fields": ["description", "garments", "colors", "materials", "accessories"]},
            {"key": "condition", "label": "Condition", "default": False, "fields": ["condition"]}],
        "ref_kinds": ["front", "back", "detail", "custom"],
    },
    "style": {
        "label": "Style", "plural": "Styles",
        "sections": [{"key": "look", "label": "Look", "fields": [
            _f("medium", "Medium"), _f("rendering_style", "Rendering style"),
            _f("palette", "Palette"), _f("contrast", "Contrast"), _f("saturation", "Saturation"),
            _f("film_grain", "Film grain"), _f("lighting_style", "Lighting style"),
            _f("camera_style", "Camera style"), _f("lens_style", "Lens style"), _f("era", "Era"),
            _f("references_text", "Reference notes", "textarea"),
            _f("negative_style", "Avoid", "textarea")]}],
        "lock_groups": [
            {"key": "look", "label": "Look", "default": True,
             "fields": ["medium", "rendering_style", "palette", "contrast", "saturation",
                        "film_grain", "lighting_style", "camera_style", "lens_style", "era"]}],
        "ref_kinds": ["mood", "frame", "palette", "custom"],
    },
}

MAX_VALUE_CHARS = 4000
MAX_LIST_ITEMS = 60


def asset_types() -> list[str]:
    return list(ASSET_SCHEMAS)


def schema_for(asset_type: str) -> dict:
    if asset_type not in ASSET_SCHEMAS:
        raise ValueError(f"unknown asset type {asset_type!r}")
    return ASSET_SCHEMAS[asset_type]


def public_schema() -> dict:
    return deepcopy(ASSET_SCHEMAS)


def known_fields(asset_type: str) -> list[dict]:
    return [f for sec in schema_for(asset_type)["sections"] for f in sec["fields"]]


def lock_groups(asset_type: str) -> list[dict]:
    return schema_for(asset_type)["lock_groups"]


def default_locks(asset_type: str) -> list[str]:
    return [g["key"] for g in lock_groups(asset_type) if g.get("default")]


def field_group_map(asset_type: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for g in lock_groups(asset_type):
        for f in g["fields"]:
            out[f] = g["key"]
    return out


def fields_of_group(asset_type: str, group: str) -> list[str]:
    for g in lock_groups(asset_type):
        if g["key"] == group:
            return list(g["fields"])
    return []


def valid_locks(asset_type: str, locks) -> list[str]:
    allowed = {g["key"] for g in lock_groups(asset_type)}
    seen: list[str] = []
    for k in locks or []:
        if isinstance(k, str) and k in allowed and k not in seen:
            seen.append(k)
    return seen


def ref_kinds(asset_type: str) -> list[str]:
    return list(schema_for(asset_type)["ref_kinds"])


def clean_value(v):
    """Bound values without changing their meaning: strings capped, lists of
    scalars capped, dicts kept shallow."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        return v.strip()[:MAX_VALUE_CHARS]
    if isinstance(v, list):
        return [clean_value(x) for x in v[:MAX_LIST_ITEMS] if x not in (None, "")]
    if isinstance(v, dict):
        return {str(k)[:100]: clean_value(x) for k, x in list(v.items())[:MAX_LIST_ITEMS]}
    return str(v)[:MAX_VALUE_CHARS]


def clean_data(asset_type: str, data: dict | None) -> dict:
    """Validate + bound a version's data. Unknown keys survive (they may come
    from the Director or an import) — nothing is silently discarded."""
    schema_for(asset_type)
    out: dict = {}
    for k, v in (data or {}).items():
        if not isinstance(k, str) or not k or len(k) > 100:
            continue
        cv = clean_value(v)
        if cv in (None, "", [], {}):
            continue
        out[k] = cv
    return out


def merge_data(asset_type: str, base: dict | None, changes: dict | None) -> dict:
    """Apply a partial update: keys set to None/'' are removed."""
    merged = dict(base or {})
    for k, v in (changes or {}).items():
        if v in (None, ""):
            merged.pop(k, None)
        else:
            merged[k] = v
    return clean_data(asset_type, merged)
