"""AI Director (spec §13, B, M, R-lite): Direct Story / Direct Scene / Direct
Shot / Production Plan. Every action produces a PROPOSAL (stored as a
film_jobs row) that is applied only on Accept — edited or not — and never
touches locked properties. The LLM path goes through the central client
(budgeted); when no provider is configured a deterministic fallback keeps
the workflow usable and tests reproducible. Costs come from the pricing
catalog or are marked unavailable — never invented."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..generation import pricing
from ..generation import router as gen_router
from ..llm import client as llm_client
from . import assets as asset_svc
from . import attributes, events, presets
from . import projects as proj_svc
from . import shotctx, story
from .models import (MEDIA_STRATEGIES, FilmAsset, FilmJob, FilmProject, FilmScene,
                     FilmShot)

PROPOSAL_KINDS = ("director_story", "director_scene", "director_shot", "production_plan",
                  "reference_proposal")
SHOT_TYPE_KEYS = [st["key"] for st in presets.SHOT_TYPES]
LIGHTING_KEYS = [lp["key"] for lp in presets.LIGHTING_PRESETS]
_MAX_SCENES, _MAX_SHOTS = 40, 20

SYSTEM_STORY = """You are the AI Director of a film studio. Break the story into scenes and shots.
Respond with ONE JSON object only, no prose, using exactly this shape:
{"scenes":[{"title":str,"intent":str,"summary":str,"location":str,"time_of_day":str,"weather":str,
 "mood":str,"lighting_preset":one of %s,
 "characters":[str],"props":[str],
 "shots":[{"title":str,"action":str,"shot_type":one of %s,
  "camera":{"lens_mm":int,"movement":one of %s,"angle":one of %s},
  "lighting_preset":str,"duration_s":number,"media_strategy":one of %s,
  "characters":[str],"keyframe":str,"reason":str}]}],
 "assets":{"characters":[{"name":str,"description":str,"data":{"age":str,"role":str,"hair":str,"eyes":str,
  "eye_color":str,"body_type":str,"distinctive_features":str}}],
  "locations":[{"name":str,"description":str,"data":{"architecture":str,"layout":str,"materials":str,
  "lighting":str,"atmosphere":str,"color_palette":str}}],
  "props":[{"name":str,"description":str}]},
 "notes":str}
Rules: keep existing asset names when they match; pick the cheapest medium that satisfies the brief;
durations follow the pacing profile; give a one-line reason per shot.""" % (
    LIGHTING_KEYS, SHOT_TYPE_KEYS, [m["key"] for m in presets.CAMERA_MOVES], presets.ANGLES,
    list(MEDIA_STRATEGIES))

SYSTEM_SCENE = """You are the AI Director. Break ONE scene into shots. Respond with ONE JSON object only:
{"shots":[{"title":str,"action":str,"shot_type":one of %s,
 "camera":{"lens_mm":int,"movement":one of %s,"angle":one of %s},"lighting_preset":one of %s,
 "duration_s":number,"media_strategy":one of %s,"characters":[str],"keyframe":str,"reason":str}],"notes":str}""" % (
    SHOT_TYPE_KEYS, [m["key"] for m in presets.CAMERA_MOVES], presets.ANGLES, LIGHTING_KEYS,
    list(MEDIA_STRATEGIES))

SYSTEM_SHOT = """You are the AI Director improving ONE shot from a natural-language note.
Respect every LOCKED property listed — never propose changing it. Respond with ONE JSON object only:
{"changes":{"shot_type":str,"camera":{"lens_mm":int,"movement":str,"movement_speed":str,"angle":str,
 "height_m":number,"depth_of_field":str,"focus_target":str,"composition":str},
 "lighting_preset":str,"lighting":{"direction":str,"color_temp_k":int,"contrast":str,"practicals":str,"mood":str},
 "environment":{"atmosphere":str,"weather":str,"time_of_day":str},"color":{"palette":str,"contrast":str,
 "saturation":str,"film_grain":str},"motion":{"character_motion":str,"environmental_motion":str,"pacing":str},
 "action":str,"expression":str,"pose":str,"duration_s":number,"media_strategy":str},
 "explanation":str}
Only include keys you actually change."""

SYSTEM_PLAN = """You are the AI Director drafting a production plan before any expensive generation.
Respond with ONE JSON object only:
{"objective":str,"audience":str,"narrative_structure":str,"visual_style":str,"audio_strategy":str,
 "media_strategy":{"summary":str,"by_kind":{"ai_video":int,"image_animation":int,"stock":int,
 "archival":int,"motion_graphics":int,"still":int,"user_footage":int}},
 "provider_strategy":str,"pacing_profile":one of %s,"scene_count":int,"shot_count":int,
 "risks":[str],"notes":str}""" % list(presets.PACING_PROFILES)


# ------------------------------------------------------------ LLM helpers --
def _parse(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw or "", flags=re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _llm_json(purpose: str, system: str, user: str, max_tokens: int) -> dict | None:
    """→ parsed dict, or None when no LLM is configured (fallback path).
    Budget/LLM errors propagate so the API can report them honestly."""
    try:
        raw = llm_client.run_llm(purpose, system, user, max_tokens=max_tokens)
    except llm_client.LLMNotConfigured:
        return None
    data = _parse(raw)
    if data is None:
        raise llm_client.LLMError("The AI Director returned no usable JSON — try again or edit manually.")
    return data


def _s(v, n: int = 400) -> str | None:
    if v in (None, "", [], {}):
        return None
    return str(v).strip()[:n] or None


def _names(v) -> list[str]:
    if isinstance(v, str):
        v = [x for x in re.split(r"[,;/]", v)]
    return [str(x).strip()[:80] for x in (v or []) if str(x).strip()][:12]


def _num(v, default: float | None, lo: float, hi: float) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, f))


# ------------------------------------------------------------- normalise --
def _norm_shot(sh: dict, project: FilmProject | None, dialogue_words: int = 0) -> dict:
    st = sh.get("shot_type") if sh.get("shot_type") in SHOT_TYPE_KEYS else None
    if st is None:
        raw = str(sh.get("shot_type") or "").lower().replace("-", "_").replace(" ", "_")
        st = next((k for k in SHOT_TYPE_KEYS if k in raw or raw in k and raw), None) or "medium"
    cam = sh.get("camera") if isinstance(sh.get("camera"), dict) else {}
    camera = {}
    if _num(cam.get("lens_mm"), None, 8, 800) is not None:
        camera["lens_mm"] = int(_num(cam.get("lens_mm"), 50, 8, 800))
    if cam.get("movement") in {m["key"] for m in presets.CAMERA_MOVES}:
        camera["movement"] = cam["movement"]
    if cam.get("angle") in presets.ANGLES:
        camera["angle"] = cam["angle"]
    for k in ("movement_speed", "depth_of_field", "focus_target", "composition"):
        if _s(cam.get(k), 120):
            camera[k] = _s(cam.get(k), 120)
    if _num(cam.get("height_m"), None, 0, 50) is not None:
        camera["height_m"] = _num(cam.get("height_m"), 1.5, 0, 50)
    strategy = sh.get("media_strategy") if sh.get("media_strategy") in MEDIA_STRATEGIES else None
    duration = _num(sh.get("duration_s"), None, 0.1, 600)
    if duration is None:
        duration = story.duration_for(st, project, dialogue_words=dialogue_words)
    return {"title": _s(sh.get("title"), 120), "action": _s(sh.get("action"), 1200),
            "shot_type": st, "camera": camera,
            "lighting_preset": sh.get("lighting_preset") if sh.get("lighting_preset") in LIGHTING_KEYS else None,
            "duration_s": round(duration * 2) / 2, "media_strategy": strategy or "ai_video",
            "characters": _names(sh.get("characters")), "keyframe": _s(sh.get("keyframe"), 400),
            "reason": _s(sh.get("reason"), 300), "expression": _s(sh.get("expression"), 120),
            "pose": _s(sh.get("pose"), 120)}


def _norm_scene(sc: dict, project: FilmProject | None) -> dict:
    words = int(sc.get("dialogue_words") or 0)
    shots = [_norm_shot(x, project, words) for x in (sc.get("shots") or [])[:_MAX_SHOTS] if isinstance(x, dict)]
    return {"title": _s(sc.get("title"), 120) or "Scene", "intent": _s(sc.get("intent"), 400),
            "summary": _s(sc.get("summary"), 800), "script_text": _s(sc.get("script_text"), 8000),
            "location": _s(sc.get("location"), 120),
            "time_of_day": _s(sc.get("time_of_day"), 40), "weather": _s(sc.get("weather"), 40),
            "mood": _s(sc.get("mood"), 120),
            "lighting_preset": sc.get("lighting_preset") if sc.get("lighting_preset") in LIGHTING_KEYS else None,
            "characters": _names(sc.get("characters")), "props": _names(sc.get("props")),
            "shots": shots}


def _norm_assets(raw: dict | None) -> dict:
    out = {"characters": [], "locations": [], "props": []}
    for key, atype in (("characters", "character"), ("locations", "location"), ("props", "prop")):
        for item in (raw or {}).get(key) or []:
            if not isinstance(item, dict) or not _s(item.get("name"), 120):
                continue
            data = attributes.clean_data(atype, item.get("data") if isinstance(item.get("data"), dict) else {})
            out[key].append({"name": _s(item["name"], 120), "type": atype,
                             "description": _s(item.get("description"), 1000), "data": data})
    return out


def _norm_story(raw: dict, project: FilmProject | None) -> dict:
    scenes = [_norm_scene(sc, project) for sc in (raw.get("scenes") or [])[:_MAX_SCENES]
              if isinstance(sc, dict)]
    assets = _norm_assets(raw.get("assets"))
    # every character/location named in scenes exists as an asset proposal
    known = {(a["type"], a["name"].lower()) for k in assets.values() for a in k}
    for sc in scenes:
        for n in sc["characters"]:
            if ("character", n.lower()) not in known:
                assets["characters"].append({"name": n, "type": "character", "description": None, "data": {}})
                known.add(("character", n.lower()))
        if sc["location"] and ("location", sc["location"].lower()) not in known:
            assets["locations"].append({"name": sc["location"], "type": "location", "description": None,
                                        "data": {k: v for k, v in (("time_of_day", sc["time_of_day"]),
                                                                   ("weather", sc["weather"])) if v}})
            known.add(("location", sc["location"].lower()))
        for n in sc["props"]:
            if ("prop", n.lower()) not in known:
                assets["props"].append({"name": n, "type": "prop", "description": None, "data": {}})
                known.add(("prop", n.lower()))
    return {"scenes": scenes, "assets": assets, "notes": _s(raw.get("notes"), 1000),
            "shot_count": sum(len(sc["shots"]) for sc in scenes),
            "runtime_s": round(sum(sh["duration_s"] for sc in scenes for sh in sc["shots"]), 1)}


# ------------------------------------------------------------- fallbacks --
def _fallback_shots(parsed: story.ParsedScene | None, project: FilmProject | None,
                    characters: list[str], location: str | None, summary: str | None) -> list[dict]:
    words = parsed.dialogue_words if parsed else 0
    subject = characters[0] if characters else (location or "the scene")
    plan = [("establishing", f"Establishing {location or 'the location'} — orient the audience.",
             "Opens the scene: geography first."),
            ("medium" if characters else "wide",
             (f"{subject} in the space; the scene's main action begins." if characters
              else f"Wide view of {location or 'the space'} as the action begins."),
             "Neutral coverage of the main beat."),
            ("close_up" if characters else "insert",
             (f"Close on {subject}'s reaction to the scene's turning point." if characters
              else "Detail that carries the scene's meaning."),
             "Emphasis on the turning point.")]
    if len(characters) >= 2:
        plan.insert(2, ("two_shot", f"{characters[0]} and {characters[1]} face each other.",
                        "Two characters share the frame at the exchange."))
    out = []
    for i, (st, action, reason) in enumerate(plan):
        out.append(_norm_shot({"title": presets.shot_type(st)["label"], "action": action,
                               "shot_type": st, "characters": characters if st != "establishing" else [],
                               "media_strategy": "ai_video", "reason": reason,
                               "duration_s": story.duration_for(st, project, dialogue_words=words if i == 1 else 0)},
                              project, words))
    return out


def fallback_story(project: FilmProject) -> dict:
    text = project.script or project.synopsis or project.logline or ""
    parsed = story.parse_script(text) if text.strip() else []
    if not parsed:
        parsed = [story.ParsedScene(title=project.title, text=text)]
    scenes = []
    for ps in parsed:
        scenes.append({"title": ps.title, "intent": None, "summary": story._summary(ps.text),
                       "script_text": ps.text or None, "location": ps.location,
                       "time_of_day": ps.time_of_day, "weather": ps.weather, "mood": None,
                       "lighting_preset": _lighting_for(ps.time_of_day, ps.weather),
                       "characters": ps.characters, "props": [], "dialogue_words": ps.dialogue_words,
                       "shots": _fallback_shots(ps, project, ps.characters, ps.location, None)})
    return _norm_story({"scenes": scenes, "assets": {}, "notes": "Deterministic breakdown (no AI provider configured)."},
                       project)


def _lighting_for(tod: str | None, weather: str | None) -> str | None:
    if weather in ("overcast", "fog", "rain", "storm"):
        return "overcast"
    return {"night": "neon_night", "late night": "horror_low_key", "dawn": "blue_hour", "dusk": "golden_hour",
            "golden hour": "golden_hour", "blue hour": "blue_hour", "midday": "hard_noon"}.get(tod or "", None)


_SHOT_HINTS = [
    (("tense", "tension", "suspense", "threat"), {"shot_type": "close_up", "lighting_preset": "horror_low_key",
                                                  "camera": {"movement": "push_in", "movement_speed": "slow"},
                                                  "color": {"contrast": "high"}}),
    (("intimate", "tender", "quiet"), {"shot_type": "close_up", "camera": {"lens_mm": 85, "depth_of_field": "shallow"},
                                       "lighting_preset": "cinematic_soft"}),
    (("expensive", "premium", "polished", "luxury"), {"lighting_preset": "cinematic_soft",
                                                      "color": {"film_grain": "fine", "saturation": "rich"}}),
    (("epic", "grand", "scale", "vast"), {"shot_type": "extreme_wide", "camera": {"lens_mm": 18, "movement": "crane"}}),
    (("wide", "establish", "geography"), {"shot_type": "wide"}),
    (("handheld", "chaotic", "frantic", "panic"), {"camera": {"movement": "handheld", "movement_speed": "fast"},
                                                   "shot_type": "medium_close"}),
    (("dutch", "unease", "disorient"), {"shot_type": "dutch"}),
    (("low angle", "powerful", "menacing", "dominant"), {"shot_type": "low_angle"}),
    (("high angle", "vulnerable", "small"), {"shot_type": "high_angle"}),
    (("golden", "warm", "nostalgic"), {"lighting_preset": "golden_hour"}),
    (("neon", "noir"), {"lighting_preset": "neon_night"}),
    (("rain",), {"environment": {"weather": "rain"}}),
    (("fog", "mist"), {"environment": {"atmosphere": "fog"}}),
    (("slow", "linger"), {"camera": {"movement_speed": "slow"}, "motion": {"pacing": "slow"}}),
    (("fast", "quick", "snappy"), {"camera": {"movement_speed": "fast"}, "motion": {"pacing": "fast"}}),
    (("orbit", "circle"), {"camera": {"movement": "orbit"}}),
    (("tracking", "follow"), {"camera": {"movement": "tracking"}}),
    (("static", "locked"), {"camera": {"movement": "static"}}),
    (("longer",), {"duration_delta": 2.0}), (("shorter",), {"duration_delta": -1.5}),
]


def fallback_shot(ctx: dict, instruction: str) -> dict:
    low = (instruction or "").lower()
    changes: dict = {}
    matched: list[str] = []
    for words, patch in _SHOT_HINTS:
        if any(w in low for w in words):
            matched.append(words[0])
            for k, v in patch.items():
                if isinstance(v, dict):
                    changes.setdefault(k, {}).update(v)
                elif k == "duration_delta":
                    changes["duration_s"] = max(0.5, float(ctx["shot"]["duration_s"] or 4) + v)
                else:
                    changes[k] = v
    explanation = ("Adjusted " + ", ".join(matched) + " from your note (deterministic presets — no AI provider configured)."
                   if matched else "No recognisable direction in the note; nothing proposed. Configure an AI provider "
                                   "in Settings → Knowledge engine for free-form direction.")
    return {"changes": changes, "explanation": explanation}


# ----------------------------------------------------------- cost basis ---
def estimate_costs(s: Session, shots: list[dict]) -> dict:
    """Catalog-based estimate for a list of {duration_s, media_strategy}.
    Marks cost unavailable when the catalog has no price — never invents."""
    video_family = (settings_store.get(s, "film_video_family") or "kling").lower()
    image_family = (settings_store.get(s, "film_image_family") or "flux").lower()
    connected = set(gen_router.connected_providers(s))

    def offer(family: str, params: dict) -> tuple[str | None, float | None, bool]:
        offers = (pricing.load_catalog().get(family) or {}).get("providers") or {}
        cands = [(p, pricing.estimate(family, p, params)) for p in offers]
        cands = [(p, e) for p, e in cands if e is not None]
        if not cands:
            return None, None, False
        live = [c for c in cands if c[0] in connected]
        pick = min(live or cands, key=lambda c: c[1])
        return pick[0], pick[1], pick[0] in connected

    per_shot = []
    total = 0.0
    unknown = 0
    video_provider = frame_provider = None
    any_connected = False
    for sh in shots:
        strategy = sh.get("media_strategy") or "ai_video"
        dur = float(sh.get("duration_s") or 4)
        cost = 0.0
        parts = {}
        if strategy in ("ai_video", "image_animation", "talking_head"):
            p, est, live = offer(video_family, {"duration_s": dur, "resolution": "720p"})
            video_provider = p or video_provider
            any_connected = any_connected or live
            if est is None:
                unknown += 1
            else:
                parts["video"] = est
                cost += est
        if strategy in ("ai_video", "image_animation", "still", "talking_head"):
            p, est, live = offer(image_family, {"size": "1024x1024"})
            frame_provider = p or frame_provider
            frames = 1 if strategy == "still" else 2
            if est is not None:
                parts["frames"] = round(est * frames, 4)
                cost += est * frames
        per_shot.append({"shot": sh.get("label") or sh.get("title"), "media_strategy": strategy,
                         "duration_s": dur, "usd": round(cost, 4) if parts else None, "parts": parts})
        total += cost
    basis = "catalog" if unknown == 0 and shots else ("partial" if shots and unknown < len(shots) else "unavailable")
    return {"total_usd": round(total, 4) if basis != "unavailable" else None, "basis": basis,
            "video_family": video_family, "video_provider": video_provider,
            "image_family": image_family, "frame_provider": frame_provider,
            "providers_connected": any_connected, "unpriced_shots": unknown, "per_shot": per_shot,
            "render_minutes_est": round(len(shots) * 1.5, 1)}


# -------------------------------------------------------------- proposals --
def _store(s: Session, project_id: int | None, kind: str, proposal: dict, source: str,
           target: dict, stage: str) -> FilmJob:
    j = FilmJob(project_id=project_id, kind=kind, status="done", stage=stage,
                payload={"target": target},
                result={"proposal": proposal, "source": source, "applied": False, "rejected": False},
                finished_at=datetime.now(timezone.utc))
    s.add(j)
    s.flush()
    events.log(s, project_id, f"Director proposal: {kind.replace('_', ' ')} ({source})", kind="director",
               stage=stage, actor="director", entity=("job", j.id),
               data={"target": target, "summary": _summary_of(kind, proposal)})
    return j


def _summary_of(kind: str, proposal: dict) -> dict:
    if kind == "director_story":
        return {"scenes": len(proposal.get("scenes", [])), "shots": proposal.get("shot_count"),
                "assets": {k: len(v) for k, v in (proposal.get("assets") or {}).items()}}
    if kind == "director_scene":
        return {"shots": len(proposal.get("shots", []))}
    if kind == "director_shot":
        return {"changed": sorted((proposal.get("changes") or {}).keys()),
                "blocked": proposal.get("blocked", [])}
    if kind == "reference_proposal":
        return {"beats": len(proposal.get("scenes") or []), "pacing_profile": proposal.get("pacing_profile"),
                "estimated_cost_usd": proposal.get("estimated_cost_usd")}
    return {"scene_count": proposal.get("scene_count"), "shot_count": proposal.get("shot_count"),
            "estimated_cost_usd": (proposal.get("estimates") or {}).get("total_usd")}


def proposal_dict(j: FilmJob) -> dict:
    r = j.result or {}
    return {"id": j.id, "kind": j.kind, "project_id": j.project_id, "stage": j.stage,
            "target": (j.payload or {}).get("target", {}), "proposal": r.get("proposal"),
            "source": r.get("source"), "applied": bool(r.get("applied")),
            "rejected": bool(r.get("rejected")), "applied_result": r.get("applied_result"),
            "note": r.get("note"), "status": j.status,
            "created_at": j.created_at.isoformat() if j.created_at else None}


def list_proposals(s: Session, project_id: int, pending_only: bool = False, limit: int = 50) -> list[dict]:
    rows = s.execute(select(FilmJob).where(FilmJob.project_id == project_id, FilmJob.kind.in_(PROPOSAL_KINDS))
                     .order_by(FilmJob.id.desc()).limit(limit)).scalars()
    out = [proposal_dict(j) for j in rows]
    if pending_only:
        out = [p for p in out if not p["applied"] and not p["rejected"]]
    return out


def _asset_names(s: Session) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for a in s.execute(select(FilmAsset).where(FilmAsset.owner_asset_id.is_(None))).scalars():
        out.setdefault(a.type, []).append(a.name)
    return out


def _project_brief(s: Session, project: FilmProject) -> str:
    st = proj_svc.merge_settings(project.settings, None)
    names = _asset_names(s)
    lines = [f"Title: {project.title}"]
    if project.logline:
        lines.append(f"Logline: {project.logline}")
    if st.get("visual_style"):
        lines.append(f"Visual style: {st['visual_style']}")
    if st.get("tone"):
        lines.append(f"Tone: {st['tone']}")
    lines.append(f"Aspect ratio {st['aspect_ratio']}; target runtime {st['target_runtime_s']}s; "
                 f"pacing profile {st['pacing_profile']}; pipeline template {st['pipeline_template']}.")
    for t, ns in names.items():
        lines.append(f"Existing {t}s: {', '.join(ns[:20])}")
    if project.plan and project.plan.get("objective"):
        lines.append(f"Plan objective: {project.plan['objective']}")
    return "\n".join(lines)


# ------------------------------------------------------------- directing --
def direct_story(s: Session, project: FilmProject, use_llm: bool = True) -> FilmJob:
    text = project.script or project.synopsis or project.logline or ""
    data = None
    if use_llm and text.strip():
        data = _llm_json("film-director-story", SYSTEM_STORY,
                         _project_brief(s, project) + "\n\nSTORY / SCRIPT:\n" + text[:12000], 3500)
    if data is not None:
        proposal, source = _norm_story(data, project), "llm"
    else:
        proposal, source = fallback_story(project), "fallback"
    proposal["estimates"] = estimate_costs(s, [sh for sc in proposal["scenes"] for sh in sc["shots"]])
    return _store(s, project.id, "director_story", proposal, source, {"project_id": project.id}, "story")


def direct_scene(s: Session, scene: FilmScene, use_llm: bool = True) -> FilmJob:
    project = s.get(FilmProject, scene.project_id)
    sd = scene.defaults or {}
    chars = sd.get("characters") or [a["name"] for a in _scene_assets(s, scene) if a["type"] == "character"]
    location = sd.get("location_name") or next((a["name"] for a in _scene_assets(s, scene) if a["type"] == "location"), None)
    data = None
    if use_llm:
        user = (_project_brief(s, project) + f"\n\nSCENE: {scene.title}\nIntent: {scene.intent or '-'}\n"
                f"Summary: {scene.summary or '-'}\nLocation: {location or '-'}; time {sd.get('time_of_day') or '-'}; "
                f"weather {sd.get('weather') or '-'}\nCharacters: {', '.join(chars) or '-'}\n\nSCRIPT:\n"
                + (scene.script_text or "")[:8000])
        data = _llm_json("film-director-scene", SYSTEM_SCENE, user, 2000)
    if data is not None:
        words = story._characters_and_dialogue(scene.script_text or "")[1]
        shots = [_norm_shot(x, project, words) for x in (data.get("shots") or [])[:_MAX_SHOTS] if isinstance(x, dict)]
        proposal, source = {"shots": shots, "notes": _s(data.get("notes"), 800)}, "llm"
    else:
        parsed = story.ParsedScene(title=scene.title, text=scene.script_text or "", characters=chars,
                                   location=location)
        parsed.characters, parsed.dialogue_words = (chars, story._characters_and_dialogue(scene.script_text or "")[1])
        proposal, source = {"shots": _fallback_shots(parsed, project, chars, location, scene.summary),
                            "notes": "Deterministic coverage (no AI provider configured)."}, "fallback"
    proposal["estimates"] = estimate_costs(s, proposal["shots"])
    return _store(s, scene.project_id, "director_scene", proposal, source,
                  {"scene_id": scene.id, "project_id": scene.project_id}, "storyboard")


def _scene_assets(s: Session, scene: FilmScene) -> list[dict]:
    out = []
    for x in (scene.defaults or {}).get("assets", []) or []:
        a = s.get(FilmAsset, int(x.get("asset_id") or 0)) if isinstance(x, dict) else None
        if a is not None:
            out.append({"name": a.name, "type": a.type, "asset_id": a.id})
    return out


_LOCK_MAP = {  # proposal change key → the shot/asset lock group that protects it
    "shot_type": "camera", "camera": "camera", "lighting": "lighting", "lighting_preset": "lighting",
    "environment": "environment", "color": "color", "motion": "motion", "action": "action",
    "expression": "expression", "pose": "pose", "duration_s": "timing", "media_strategy": "media_strategy",
}


def _filter_locked(changes: dict, ctx: dict) -> tuple[dict, list[dict]]:
    locked_shot = set(ctx.get("locks") or [])
    locked_assets = {}
    for l in ctx.get("asset_locks") or []:
        name, group = l.split(":", 1)
        locked_assets.setdefault(group, []).append(name)
    kept, blocked = {}, []
    for k, v in (changes or {}).items():
        group = _LOCK_MAP.get(k)
        if group in locked_shot:
            blocked.append({"key": k, "reason": f"{group} is locked on this shot"})
        elif group in ("expression", "pose") and locked_assets.get(group):
            blocked.append({"key": k, "reason": f"{group} is locked on {', '.join(locked_assets[group])}"})
        else:
            kept[k] = v
    return kept, blocked


def direct_shot(s: Session, shot: FilmShot, instruction: str, use_llm: bool = True) -> FilmJob:
    ctx = shotctx.effective_context(s, shot)
    data = None
    if use_llm and instruction.strip():
        locked = ", ".join(list(ctx["locks"]) + list(ctx["asset_locks"])) or "none"
        current = {k: ctx.get(k) for k in ("camera", "lighting", "environment", "color", "motion", "action")}
        user = (f"SHOT {ctx['scene'].get('title')} / {shot.title or shot.id}\nLOCKED: {locked}\n"
                f"Current: {json.dumps(current, default=str)[:3000]}\nDuration: {shot.duration_s}s; "
                f"media: {shot.media_strategy}\nAssets: "
                + "; ".join(f"{a['name']} ({a['type']})" for a in ctx["assets"])
                + f"\n\nDIRECTION: {instruction.strip()[:1500]}")
        data = _llm_json("film-director-shot", SYSTEM_SHOT, user, 1200)
    if data is not None:
        raw_changes = data.get("changes") if isinstance(data.get("changes"), dict) else {}
        explanation = _s(data.get("explanation"), 800) or ""
        source = "llm"
    else:
        fb = fallback_shot(ctx, instruction)
        raw_changes, explanation, source = fb["changes"], fb["explanation"], "fallback"
    norm = _norm_shot({**raw_changes, "shot_type": raw_changes.get("shot_type") or ctx["shot"].get("shot_type") or "medium"},
                      s.get(FilmProject, shot.project_id))
    changes: dict = {}
    if raw_changes.get("shot_type") and norm["shot_type"] != ctx["shot"].get("shot_type"):
        changes["shot_type"] = norm["shot_type"]
    if norm["camera"]:
        changes["camera"] = norm["camera"]
    for k in ("lighting", "environment", "color", "motion"):
        if isinstance(raw_changes.get(k), dict):
            cleaned = {str(a)[:60]: _s(b, 200) for a, b in raw_changes[k].items() if _s(b, 200)}
            if cleaned:
                changes[k] = cleaned
    if norm["lighting_preset"]:
        changes["lighting_preset"] = norm["lighting_preset"]
    for k in ("action", "expression", "pose"):
        if norm.get(k):
            changes[k] = norm[k]
    if raw_changes.get("duration_s") is not None:
        changes["duration_s"] = norm["duration_s"]
    if raw_changes.get("media_strategy") in MEDIA_STRATEGIES:
        changes["media_strategy"] = raw_changes["media_strategy"]
    kept, blocked = _filter_locked(changes, ctx)
    proposal = {"instruction": instruction.strip()[:1500], "changes": kept, "blocked": blocked,
                "explanation": explanation, "before": {k: ctx.get(k) for k in ("camera", "lighting", "environment",
                                                                                "color", "motion", "action")},
                "before_shot": {"shot_type": ctx["shot"].get("shot_type"), "duration_s": shot.duration_s,
                                "media_strategy": shot.media_strategy}}
    return _store(s, shot.project_id, "director_shot", proposal, source,
                  {"shot_id": shot.id, "scene_id": shot.scene_id, "project_id": shot.project_id}, "storyboard")


def production_plan(s: Session, project: FilmProject, use_llm: bool = True) -> FilmJob:
    st = proj_svc.merge_settings(project.settings, None)
    shots = [{"label": f"{sc.position + 1}.{sh.position + 1}", "duration_s": sh.duration_s,
              "media_strategy": sh.media_strategy} for sh, sc in proj_svc.ordered_shots(s, project.id)]
    scene_count = len(proj_svc.scenes_of(s, project.id))
    tmpl = presets.PIPELINE_TEMPLATES.get(st.get("pipeline_template"), presets.PIPELINE_TEMPLATES["cinematic_narrative"])
    if not shots:
        # nothing framed yet → estimate from the target runtime and pacing
        base = presets.pacing(st.get("pacing_profile")).get("base_s", 4.0)
        n = max(1, int(round(float(st.get("target_runtime_s", 60)) / base)))
        shots = [{"label": f"est.{i + 1}", "duration_s": base, "media_strategy": tmpl["media_strategy"]}
                 for i in range(n)]
        scene_count = scene_count or max(1, n // 4)
    data = None
    if use_llm:
        user = (_project_brief(s, project) + f"\n\nScenes: {scene_count}; shots: {len(shots)}; "
                f"pipeline template: {tmpl['label']} (default medium {tmpl['media_strategy']}).\n"
                f"Story:\n{(project.script or project.synopsis or project.logline or '')[:6000]}")
        data = _llm_json("film-director-plan", SYSTEM_PLAN, user, 1500)
    est = estimate_costs(s, shots)
    by_kind: dict[str, int] = {}
    for sh in shots:
        by_kind[sh["media_strategy"]] = by_kind.get(sh["media_strategy"], 0) + 1
    plan = {
        "objective": _s((data or {}).get("objective"), 400) or st.get("objective") or project.logline or f"Produce “{project.title}”",
        "audience": _s((data or {}).get("audience"), 200) or st.get("audience") or "general",
        "target_runtime_s": st.get("target_runtime_s"),
        "aspect_ratio": st.get("aspect_ratio"),
        "visual_style": _s((data or {}).get("visual_style"), 400) or st.get("visual_style") or tmpl["label"],
        "narrative_structure": _s((data or {}).get("narrative_structure"), 400) or
        ("three-act" if scene_count >= 3 else "single-sequence"),
        "scene_count": int((data or {}).get("scene_count") or scene_count),
        "shot_count": int((data or {}).get("shot_count") or len(shots)),
        "pacing_profile": (data or {}).get("pacing_profile") if (data or {}).get("pacing_profile") in presets.PACING_PROFILES
        else st.get("pacing_profile"),
        "media_strategy": {"summary": _s(((data or {}).get("media_strategy") or {}).get("summary"), 400)
                           if isinstance((data or {}).get("media_strategy"), dict) else
                           f"{tmpl['media_strategy']} by default; cheaper media where the brief allows",
                           "by_kind": by_kind},
        "audio_strategy": _s((data or {}).get("audio_strategy"), 400) or ", ".join(tmpl["audio"]),
        "provider_strategy": _s((data or {}).get("provider_strategy"), 400) or
        (f"{est['video_provider'] or 'no provider'} for {est['video_family']} video, "
         f"{est['frame_provider'] or 'no provider'} for {est['image_family']} frames"
         + ("" if est["providers_connected"] else " — connect a provider in Settings → AI providers")),
        "estimates": est,
        "estimated_cost_usd": est["total_usd"],
        "estimated_render_min": est["render_minutes_est"],
        "pipeline_template": st.get("pipeline_template"),
        "risks": [_s(r, 200) for r in ((data or {}).get("risks") or []) if _s(r, 200)][:8],
        "notes": _s((data or {}).get("notes"), 800),
        "shots_basis": "framed shots" if any(not str(x["label"]).startswith("est.") for x in shots) else "estimated from runtime",
    }
    return _store(s, project.id, "production_plan", plan, "llm" if data is not None else "fallback",
                  {"project_id": project.id}, "plan")


# --------------------------------------------------------------- applying --
def _find_or_create_asset(s: Session, spec: dict, project: FilmProject, job_id: int) -> FilmAsset:
    name, atype = spec["name"], spec["type"]
    existing = s.execute(select(FilmAsset).where(FilmAsset.type == atype,
                                                 FilmAsset.owner_asset_id.is_(None))).scalars()
    for a in existing:
        if a.name.strip().lower() == name.strip().lower():
            return a
    return asset_svc.create_asset(s, atype, name, description=spec.get("description"),
                                  data=spec.get("data"), project_id=project.id,
                                  provenance={"origin": "director", "job_id": job_id}, actor="director")


def _apply_shot_spec(s: Session, scene: FilmScene, spec: dict, job_id: int) -> FilmShot:
    overrides = {k: v for k, v in (("shot_type", spec.get("shot_type")), ("camera", spec.get("camera")),
                                   ("lighting_preset", spec.get("lighting_preset")),
                                   ("action", spec.get("action")), ("characters", spec.get("characters") or None),
                                   ("expression", spec.get("expression")), ("pose", spec.get("pose"))) if v}
    sh = proj_svc.create_shot(s, scene, title=spec.get("title"), duration_s=spec.get("duration_s"),
                              media_strategy=spec.get("media_strategy"), overrides=overrides,
                              notes=spec.get("keyframe"))
    reason = spec.get("reason")
    events.log(s, scene.project_id, f"Shot {scene.position + 1}.{sh.position + 1}: {spec.get('shot_type')} · "
               f"{spec.get('media_strategy')} · {spec.get('duration_s')}s",
               kind="decision", stage="storyboard", actor="director", reason=reason,
               entity=("shot", sh.id), data={"job_id": job_id, "shot_type": spec.get("shot_type"),
                                             "media_strategy": spec.get("media_strategy"),
                                             "duration_s": spec.get("duration_s")})
    return sh


def apply(s: Session, job: FilmJob, edits: dict | None = None, mode: str = "append",
          actor: str = "user") -> dict:
    """Accept a proposal (optionally edited). Locked properties are never
    changed; blocked keys are reported, not applied."""
    if job.kind not in PROPOSAL_KINDS:
        raise ValueError("not a director proposal")
    r = dict(job.result or {})
    if r.get("applied"):
        raise ValueError("proposal already applied")
    if r.get("rejected"):
        raise ValueError("proposal was rejected")
    proposal = dict(r.get("proposal") or {})
    if edits:
        proposal.update(edits)
    target = (job.payload or {}).get("target", {})
    project = s.get(FilmProject, job.project_id)
    result: dict = {}

    if job.kind == "director_story":
        proposal = _norm_story(proposal, project)
        if mode == "replace":
            for sc in proj_svc.scenes_of(s, project.id):
                proj_svc.delete_scene(s, sc)
        created_assets: dict[tuple[str, str], FilmAsset] = {}
        for key in ("characters", "locations", "props"):
            for spec in proposal["assets"].get(key, []):
                a = _find_or_create_asset(s, spec, project, job.id)
                created_assets[(a.type, a.name.lower())] = a
        scene_ids, shot_ids = [], []
        for sc_spec in proposal["scenes"]:
            assets = []
            for n in sc_spec["characters"]:
                a = created_assets.get(("character", n.lower()))
                if a:
                    assets.append({"asset_id": a.id, "role": "character"})
            if sc_spec["location"]:
                a = created_assets.get(("location", sc_spec["location"].lower()))
                if a:
                    assets.append({"asset_id": a.id, "role": "location"})
            for n in sc_spec["props"]:
                a = created_assets.get(("prop", n.lower()))
                if a:
                    assets.append({"asset_id": a.id, "role": "prop"})
            defaults = {k: v for k, v in (("time_of_day", sc_spec["time_of_day"]), ("weather", sc_spec["weather"]),
                                          ("mood", sc_spec["mood"]), ("lighting_preset", sc_spec["lighting_preset"]),
                                          ("location_name", sc_spec["location"]),
                                          ("characters", sc_spec["characters"] or None)) if v}
            defaults["assets"] = assets
            sc = proj_svc.create_scene(s, project, title=sc_spec["title"], intent=sc_spec["intent"],
                                       summary=sc_spec["summary"], script_text=sc_spec["script_text"],
                                       defaults=defaults)
            scene_ids.append(sc.id)
            for sh_spec in sc_spec["shots"]:
                shot_ids.append(_apply_shot_spec(s, sc, sh_spec, job.id).id)
        if project.status == "draft":
            project.status = "planning"
        result = {"scene_ids": scene_ids, "shot_ids": shot_ids,
                  "asset_ids": sorted({a.id for a in created_assets.values()}), "mode": mode}

    elif job.kind == "director_scene":
        scene = s.get(FilmScene, target.get("scene_id"))
        if scene is None:
            raise ValueError("scene no longer exists")
        if mode == "replace":
            for sh in proj_svc.shots_of(s, scene.id):
                proj_svc.delete_shot(s, sh)
        shot_ids = [_apply_shot_spec(s, scene, _norm_shot(x, project), job.id).id
                    for x in proposal.get("shots", []) if isinstance(x, dict)]
        result = {"scene_id": scene.id, "shot_ids": shot_ids, "mode": mode}

    elif job.kind == "director_shot":
        shot = s.get(FilmShot, target.get("shot_id"))
        if shot is None:
            raise ValueError("shot no longer exists")
        ctx = shotctx.effective_context(s, shot)
        changes, blocked = _filter_locked(dict(proposal.get("changes") or {}), ctx)
        ov = dict(shot.overrides or {})
        fields: dict = {}
        for k, v in changes.items():
            if k == "duration_s":
                fields["duration_s"] = v
            elif k == "media_strategy":
                fields["media_strategy"] = v
            elif isinstance(v, dict) and isinstance(ov.get(k), dict):
                ov[k] = {**ov[k], **v}
            else:
                ov[k] = v
        fields["overrides"] = ov
        proj_svc.update_shot(s, shot, **fields)
        if shot.status == "planned" and changes:
            shot.status = "framed"
        events.log(s, shot.project_id, f"Shot {shot.position + 1}: direction applied",
                   kind="decision", stage="storyboard", actor=actor,
                   reason=proposal.get("explanation"), entity=("shot", shot.id),
                   data={"changed": sorted(changes.keys()), "blocked": blocked, "job_id": job.id})
        result = {"shot_id": shot.id, "changed": sorted(changes.keys()), "blocked": blocked}

    elif job.kind == "production_plan":
        plan = dict(proposal)
        plan.pop("approved", None)
        plan["approved"] = False
        plan["proposed_by"] = r.get("source")
        plan["accepted_at"] = datetime.now(timezone.utc).isoformat()
        project.plan = plan
        settings_patch = {k: plan[k] for k in ("pacing_profile", "aspect_ratio", "target_runtime_s",
                                               "pipeline_template") if plan.get(k)}
        if plan.get("visual_style"):
            settings_patch["visual_style"] = plan["visual_style"]
        if plan.get("objective"):
            settings_patch["objective"] = plan["objective"]
        if plan.get("audience"):
            settings_patch["audience"] = plan["audience"]
        proj_svc.update_project(s, project, settings=settings_patch)
        if project.status == "draft":
            project.status = "planning"
        # accepting the plan resets its approval gate — approval is a separate, explicit act
        from . import gates
        g = gates._row(s, project.id, "plan", None)
        if g is not None and g.status == "approved":
            g.status = "pending"
            g.decided_at = None
        result = {"plan_keys": sorted(plan.keys()), "estimated_cost_usd": plan.get("estimated_cost_usd")}

    elif job.kind == "reference_proposal":
        settings_patch = {k: proposal[k] for k in ("pacing_profile", "aspect_ratio", "target_runtime_s") if proposal.get(k)}
        proj_svc.update_project(s, project, settings=settings_patch)
        ref = dict(project.reference or {})
        ref["proposal_accepted"] = {"job_id": job.id, "at": datetime.now(timezone.utc).isoformat(),
                                   "retained": proposal.get("retained"), "changed": proposal.get("changed")}
        project.reference = ref
        plan = dict(project.plan or {})
        plan.update({"narrative_structure": proposal.get("structure"), "media_strategy": {"summary": proposal.get("media_strategy")},
                     "audio_strategy": proposal.get("audio_strategy"), "target_runtime_s": proposal.get("target_runtime_s"),
                     "aspect_ratio": proposal.get("aspect_ratio"), "pacing_profile": proposal.get("pacing_profile"),
                     "reference": {"source": proposal.get("source"), "retained": proposal.get("retained")},
                     "estimated_cost_usd": proposal.get("estimated_cost_usd"), "approved": False})
        project.plan = plan
        created_scenes: list[int] = []
        if (edits or {}).get("create_structure", not proj_svc.scenes_of(s, project.id)):
            for i, beat in enumerate(proposal.get("scenes") or []):
                sc = proj_svc.create_scene(s, project, title=beat.get("title") or f"Beat {i + 1}", intent=beat.get("intent"))
                created_scenes.append(sc.id)
                for j, d in enumerate(beat.get("shot_durations_s") or [beat.get("duration_s") or 4]):
                    st_key = "establishing" if j == 0 else ("medium" if j % 2 else "close_up")
                    proj_svc.create_shot(s, sc, title=f"{beat.get('title') or 'Beat'} · {j + 1}", duration_s=d,
                                         overrides={"shot_type": st_key})
        if project.status == "draft":
            project.status = "planning"
        result = {"settings": settings_patch, "scene_ids": created_scenes,
                  "structure_created": bool(created_scenes)}

    r["applied"] = True
    r["applied_at"] = datetime.now(timezone.utc).isoformat()
    r["applied_result"] = result
    if edits:
        r["edited"] = True
    job.result = r
    s.flush()
    events.log(s, job.project_id, f"Accepted director proposal ({job.kind.replace('_', ' ')})",
               kind="decision", stage=job.stage, actor=actor, entity=("job", job.id),
               data={"edited": bool(edits), "mode": mode, "result": result})
    return result


def reject(s: Session, job: FilmJob, note: str | None = None, actor: str = "user") -> dict:
    r = dict(job.result or {})
    if r.get("applied"):
        raise ValueError("proposal already applied")
    r["rejected"] = True
    r["note"] = note
    job.result = r
    job.status = "cancelled"
    s.flush()
    events.log(s, job.project_id, f"Rejected director proposal ({job.kind.replace('_', ' ')})",
               kind="decision", stage=job.stage, actor=actor, reason=note, entity=("job", job.id))
    return proposal_dict(job)
