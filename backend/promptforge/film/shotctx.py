"""ShotContextBuilder + GenerationContextBuilder (spec §11, §17, §18, §19):

    scene_context + shot_overrides (+ presets, project style) = effective_shot_context

Nothing is copied into shots; every effective field carries its source
(project | scene | shot | preset:<key>) so the UI can show what is inherited.
Locks come from the shot AND from the pinned asset versions; the prompt
assembler puts locked facts first and never drops them. Regeneration adds
explicit change/preserve constraints instead of rebuilding the shot."""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import assets as asset_svc
from . import context as ctx_mod
from . import presets
from . import projects as proj_svc
from .models import FilmProject, FilmScene, FilmShot

GROUPS = ("action", "camera", "lighting", "environment", "color", "motion", "style")
_SIZE_LABEL = {"extreme_wide": "extreme wide shot", "wide": "wide shot", "full": "full shot",
               "medium_wide": "medium wide shot", "medium": "medium shot",
               "medium_close": "medium close-up", "close_up": "close-up",
               "extreme_close_up": "extreme close-up"}
_ANGLE_LABEL = {"eye_level": "eye-level", "low": "low angle", "high": "high angle",
                "overhead": "top-down overhead", "dutch": "dutch angle"}
_MOVE_LABEL = {m["key"]: m["label"].lower() for m in presets.CAMERA_MOVES}


def _layer(target: dict, sources: dict, group: str, values: dict | None, source: str) -> None:
    for k, v in (values or {}).items():
        if v in (None, "", [], {}):
            continue
        target[k] = v
        sources[f"{group}.{k}"] = source


def effective_context(s: Session, shot: FilmShot, scene: FilmScene | None = None,
                      project: FilmProject | None = None) -> dict:
    scene = scene or s.get(FilmScene, shot.scene_id)
    project = project or s.get(FilmProject, shot.project_id)
    settings = proj_svc.merge_settings(project.settings if project else None, None)
    ov = shot.overrides or {}
    sd = (scene.defaults or {}) if scene else {}
    sources: dict[str, str] = {}
    groups: dict[str, dict] = {g: {} for g in GROUPS}

    # camera: shot-type preset → scene camera → shot camera
    st_key = ov.get("shot_type") or sd.get("shot_type")
    st = presets.resolve_shot_type(s, st_key) if st_key else None
    if st:
        _layer(groups["camera"], sources, "camera", st["camera"], f"preset:{st['key']}")
    _layer(groups["camera"], sources, "camera", sd.get("camera"), "scene")
    _layer(groups["camera"], sources, "camera", ov.get("camera"), "shot")

    # lighting: preset → scene → shot
    lp_key = ov.get("lighting_preset") or sd.get("lighting_preset")
    lp = presets.lighting_preset(lp_key) if lp_key else None
    if lp:
        _layer(groups["lighting"], sources, "lighting",
               {k: v for k, v in lp.items() if k not in ("key", "label")}, f"preset:{lp['key']}")
    _layer(groups["lighting"], sources, "lighting", sd.get("lighting"), "scene")
    _layer(groups["lighting"], sources, "lighting", ov.get("lighting"), "shot")

    # environment: scene scalars + scene env dict → shot env
    _layer(groups["environment"], sources, "environment",
           {"time_of_day": sd.get("time_of_day"), "weather": sd.get("weather"),
            "atmosphere": sd.get("atmosphere")}, "scene")
    _layer(groups["environment"], sources, "environment", sd.get("environment"), "scene")
    _layer(groups["environment"], sources, "environment", ov.get("environment"), "shot")

    for g in ("color", "motion"):
        _layer(groups[g], sources, g, sd.get(g), "scene")
        _layer(groups[g], sources, g, ov.get(g), "shot")

    # style: project visual style → scene → shot
    _layer(groups["style"], sources, "style", {"visual_style": settings.get("visual_style"),
                                               "tone": settings.get("tone")}, "project")
    _layer(groups["style"], sources, "style", sd.get("style") if isinstance(sd.get("style"), dict)
           else ({"visual_style": sd.get("style")} if sd.get("style") else None), "scene")
    _layer(groups["style"], sources, "style", ov.get("style") if isinstance(ov.get("style"), dict)
           else ({"visual_style": ov.get("style")} if ov.get("style") else None), "shot")

    # action / subject: shot only (scene summary is context, not action)
    _layer(groups["action"], sources, "action",
           {"action": ov.get("action"), "subject": ov.get("subject"),
            "expression": ov.get("expression"), "pose": ov.get("pose")}, "shot")

    # assets with exact versions → canonical contexts
    eff_assets = proj_svc.effective_assets(s, shot, scene)
    asset_ctx = []
    for e in eff_assets:
        a = asset_svc.get_asset(s, e["asset_id"])
        if a is None:
            continue
        c = asset_svc.context_for(s, a, e["version_id"])
        c["role"] = e["role"]
        c["source"] = e["source"]
        asset_ctx.append(c)
    present = ov.get("characters")
    if isinstance(present, list) and present:
        wanted = {str(n).strip().lower() for n in present}
        for c in asset_ctx:
            if c["type"] == "character":
                c["present"] = c["name"].lower() in wanted
    else:
        for c in asset_ctx:
            c["present"] = True

    locks = list(shot.locks or [])
    asset_locks = [f"{c['name']}:{g}" for c in asset_ctx for g in c["locked_groups"]]
    constraints = ([f"{c['name']}: {a['label'].lower()} = {ctx_mod._fmt(a['value'])}"
                    for c in asset_ctx for a in c["locked_attributes"]]
                   + [f"{c['name']}: {r}" for c in asset_ctx for r in c["continuity_rules"]])

    return {
        "shot_id": shot.id, "scene_id": shot.scene_id, "project_id": shot.project_id,
        "project": {"title": project.title if project else None,
                    "aspect_ratio": settings.get("aspect_ratio"),
                    "visual_style": settings.get("visual_style"), "tone": settings.get("tone"),
                    "continuity_mode": settings.get("continuity_mode")},
        "scene": {"id": scene.id if scene else None, "title": scene.title if scene else None,
                  "intent": scene.intent if scene else None,
                  "summary": scene.summary if scene else None,
                  "location_name": sd.get("location_name"), "mood": sd.get("mood")},
        "shot": {"title": shot.title, "shot_type": st_key, "shot_type_label": st["label"] if st else None,
                 "duration_s": shot.duration_s, "media_strategy": shot.media_strategy,
                 "prompt_override": ov.get("prompt"), "negative_override": ov.get("negative"),
                 "generation": ov.get("generation") or {},
                 "start_frame": shot.start_frame, "end_frame": shot.end_frame,
                 "chain_from_previous": bool(shot.chain_from_previous),
                 "characters": present if isinstance(present, list) else None},
        **groups,
        "assets": asset_ctx,
        "asset_versions": [{"asset_id": c["asset_id"], "version_id": c["version_id"],
                            "name": c["name"], "type": c["type"], "version": c["version"]}
                           for c in asset_ctx],
        "locks": locks, "asset_locks": asset_locks, "constraints": constraints,
        "sources": sources,
    }


def _short(text: str | None, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def _camera_phrase(cam: dict) -> str:
    bits = []
    if cam.get("shot_size"):
        bits.append(_SIZE_LABEL.get(cam["shot_size"], str(cam["shot_size"]).replace("_", " ")))
    if cam.get("angle") and cam["angle"] != "eye_level":
        bits.append(_ANGLE_LABEL.get(cam["angle"], cam["angle"]))
    if cam.get("lens_mm"):
        bits.append(f"{cam['lens_mm']}mm lens")
    if cam.get("depth_of_field"):
        bits.append(f"{cam['depth_of_field']} depth of field")
    if cam.get("focus_target"):
        bits.append(f"focus on {cam['focus_target']}")
    if cam.get("movement") and cam["movement"] != "static":
        speed = f"{cam['movement_speed']} " if cam.get("movement_speed") else ""
        bits.append(f"{speed}{_MOVE_LABEL.get(cam['movement'], cam['movement'])} camera move")
    elif cam.get("movement") == "static":
        bits.append("static camera")
    if cam.get("height_m"):
        bits.append(f"camera height {cam['height_m']}m")
    if cam.get("composition"):
        bits.append(str(cam["composition"]))
    return ", ".join(bits)


def _lighting_phrase(lt: dict) -> str:
    bits = []
    if lt.get("mood"):
        bits.append(f"{lt['mood']} lighting")
    if lt.get("direction"):
        bits.append(f"key light from {lt['direction']}")
    if lt.get("color_temp_k"):
        bits.append(f"{lt['color_temp_k']}K")
    if lt.get("contrast"):
        bits.append(f"{lt['contrast']} contrast")
    if lt.get("practicals"):
        bits.append(str(lt["practicals"]))
    for k in ("key", "fill", "rim"):
        if lt.get(k):
            bits.append(f"{k} light: {lt[k]}")
    if lt.get("rim_intensity") and float(lt.get("rim_intensity") or 0) >= 0.7:
        bits.append("strong rim light")
    return ", ".join(bits)


def _env_phrase(env: dict) -> str:
    bits = [str(env[k]) for k in ("time_of_day", "weather", "atmosphere") if env.get(k)]
    for k in ("fog", "smoke", "dust", "rain"):
        if env.get(k) and k not in " ".join(bits):
            bits.append(k if env[k] is True else f"{k}: {env[k]}")
    if env.get("environmental_animation"):
        bits.append(str(env["environmental_animation"]))
    return ", ".join(bits)


def _color_phrase(col: dict) -> str:
    return ", ".join(str(col[k]) if k in ("palette", "rendering_style") else f"{k.replace('_', ' ')}: {col[k]}"
                     for k in ("palette", "rendering_style", "contrast", "saturation", "film_grain")
                     if col.get(k))


def _motion_phrase(mo: dict) -> str:
    return ", ".join(str(mo[k]) for k in ("character_motion", "environmental_motion",
                                          "camera_motion", "pacing") if mo.get(k))


def build_prompt(ctx: dict, kind: str = "video") -> dict:
    """Deterministic prompt + negative from an effective context. Locked
    facts are emitted first inside each asset block (constraints), then the
    variable ones; a raw prompt override replaces the assembled body but
    keeps the constraint block."""
    style = ctx.get("style") or {}
    parts: list[str] = []
    style_bits = [str(style[k]) for k in ("visual_style", "rendering_style", "tone") if style.get(k)]
    style_assets = [c for c in ctx["assets"] if c["type"] == "style"]
    for c in style_assets:
        style_bits.append(_short(ctx_mod.describe(c, max_chars=400), 400))
    if style_bits:
        parts.append(", ".join(style_bits))

    cam = _camera_phrase(ctx.get("camera") or {})
    if cam:
        parts.append(cam)

    action = ctx.get("action") or {}
    body = ctx["shot"].get("prompt_override") or action.get("action") or action.get("subject") \
        or ctx["scene"].get("summary") or ctx["shot"].get("title") or ""
    if body:
        parts.append(_short(body, 800))
    for k in ("expression", "pose"):
        if action.get(k):
            parts.append(f"{k}: {action[k]}")

    for c in ctx["assets"]:
        if c["type"] == "character" and c.get("present", True):
            parts.append(_short(ctx_mod.describe(c, max_chars=600), 600))
    for c in ctx["assets"]:
        if c["type"] == "outfit":
            parts.append(_short(ctx_mod.describe(c, max_chars=300), 300))
    loc_name = None
    for c in ctx["assets"]:
        if c["type"] == "location":
            loc_name = c["name"]
            parts.append("Location — " + _short(ctx_mod.describe(c, max_chars=600), 600))
    if not loc_name and ctx["scene"].get("location_name"):
        parts.append(f"Location: {ctx['scene']['location_name']}")
    for c in ctx["assets"]:
        if c["type"] in ("prop", "vehicle"):
            parts.append(_short(ctx_mod.describe(c, include_variables=False, max_chars=240), 240))

    for phrase in (_lighting_phrase(ctx.get("lighting") or {}), _env_phrase(ctx.get("environment") or {}),
                   _color_phrase(ctx.get("color") or {}), _motion_phrase(ctx.get("motion") or {})):
        if phrase:
            parts.append(phrase)
    aspect = ctx["project"].get("aspect_ratio")
    parts.append(("cinematic video" if kind == "video" else "cinematic film still")
                 + (f", {aspect}" if aspect else ""))

    negatives: list[str] = []
    for c in ctx["assets"]:
        negatives += [n for n in c.get("negative_constraints", []) if n not in negatives]
    if style.get("negative_style"):
        negatives.append(str(style["negative_style"]))
    for c in style_assets:
        ns = (c.get("visual_description") or {}).get("negative_style")
        if ns and str(ns) not in negatives:
            negatives.append(str(ns))
    if ctx["shot"].get("negative_override"):
        negatives.append(str(ctx["shot"]["negative_override"]))
    prompt = ". ".join(p.rstrip(". ") for p in parts if p).strip()
    return {"prompt": prompt, "negative": ", ".join(dict.fromkeys(n.strip() for n in negatives if n.strip())),
            "constraints": ctx.get("constraints", []), "locks": ctx.get("locks", []) + ctx.get("asset_locks", [])}


REGEN_GROUPS = ("face", "hair", "body", "clothing", "expression", "pose", "location",
                "architecture", "layout", "furniture", "camera", "lighting", "environment",
                "color", "motion", "action", "style", "props")


def regeneration_prompt(ctx: dict, change: list[str], preserve: list[str],
                        instruction: str | None = None, kind: str = "video") -> dict:
    """Targeted regeneration (spec §19): the base prompt plus explicit
    change/preserve lines. Locked groups can never appear in `change` —
    they are moved to `preserve` and reported in `blocked`."""
    base = build_prompt(ctx, kind)
    locked = set(ctx.get("locks") or []) | {l.split(":", 1)[1] for l in ctx.get("asset_locks") or []}
    change_ok = [c for c in change if c not in locked]
    blocked = [c for c in change if c in locked]
    keep = list(dict.fromkeys(list(preserve) + blocked + [l for l in locked if l not in change_ok]))
    lines = [base["prompt"]]
    if instruction:
        lines.append(f"Requested change: {instruction.strip()}")
    if change_ok:
        lines.append("Change only: " + ", ".join(change_ok))
    if keep:
        lines.append("Keep exactly as in the reference: " + ", ".join(keep))
    return {**base, "prompt": ". ".join(lines), "change": change_ok, "preserve": keep,
            "blocked": blocked}
