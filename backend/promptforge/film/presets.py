"""Built-in creative presets (spec I, J, K, M, W): shot types with camera
defaults + plain-language use cases, lens strip, camera motions, lighting
presets, pacing profiles, pipeline templates. Visual examples are drawn by
the frontend as original diagrams from these descriptors (no film stills).
User favourites/customisations live in settings `film_presets` and are
merged on read."""
from __future__ import annotations

from copy import deepcopy

from sqlalchemy.orm import Session

from .. import settings_store

SHOT_TYPES: list[dict] = [
    {"key": "extreme_wide", "label": "Extreme Wide Shot", "abbr": "EWS",
     "what": "The subject is tiny inside a vast environment.",
     "use": "Scale, isolation, the world before the story.",
     "camera": {"shot_size": "extreme_wide", "angle": "eye_level", "lens_mm": 18, "height_m": 1.6, "movement": "static"},
     "figure": 0.12},
    {"key": "wide", "label": "Wide Shot", "abbr": "WS",
     "what": "Full environment with the subject clearly placed in it.",
     "use": "Geography, entrances, group action.",
     "camera": {"shot_size": "wide", "angle": "eye_level", "lens_mm": 24, "height_m": 1.5, "movement": "static"},
     "figure": 0.3},
    {"key": "full", "label": "Full Shot", "abbr": "FS",
     "what": "Head to toe, body language readable.",
     "use": "Costume, posture, physical performance.",
     "camera": {"shot_size": "full", "angle": "eye_level", "lens_mm": 35, "height_m": 1.4, "movement": "static"},
     "figure": 0.5},
    {"key": "medium_wide", "label": "Medium Wide Shot", "abbr": "MWS",
     "what": "Knees up (the classic cowboy shot).",
     "use": "Standoffs, walking-and-talking, hands and face together.",
     "camera": {"shot_size": "medium_wide", "angle": "eye_level", "lens_mm": 35, "height_m": 1.4, "movement": "static"},
     "figure": 0.62},
    {"key": "medium", "label": "Medium Shot", "abbr": "MS",
     "what": "Waist up — the conversational default.",
     "use": "Dialogue, neutral coverage.",
     "camera": {"shot_size": "medium", "angle": "eye_level", "lens_mm": 50, "height_m": 1.5, "movement": "static"},
     "figure": 0.72},
    {"key": "medium_close", "label": "Medium Close-Up", "abbr": "MCU",
     "what": "Chest up; expression dominates, context remains.",
     "use": "Emotional dialogue, reactions.",
     "camera": {"shot_size": "medium_close", "angle": "eye_level", "lens_mm": 50, "height_m": 1.55, "movement": "static"},
     "figure": 0.85},
    {"key": "close_up", "label": "Close-Up", "abbr": "CU",
     "what": "The face fills the frame.",
     "use": "Intimacy, decision moments, tension.",
     "camera": {"shot_size": "close_up", "angle": "eye_level", "lens_mm": 85, "height_m": 1.6, "movement": "static"},
     "figure": 1.0},
    {"key": "extreme_close_up", "label": "Extreme Close-Up", "abbr": "ECU",
     "what": "Eyes, lips, a hand — one detail.",
     "use": "Micro-emotion, texture, dread.",
     "camera": {"shot_size": "extreme_close_up", "angle": "eye_level", "lens_mm": 100, "height_m": 1.6, "movement": "static"},
     "figure": 1.4},
    {"key": "two_shot", "label": "Two Shot", "abbr": "2S",
     "what": "Two subjects framed together.",
     "use": "Relationship, negotiation, shared space.",
     "camera": {"shot_size": "medium", "angle": "eye_level", "lens_mm": 40, "height_m": 1.5, "movement": "static"},
     "figure": 0.7, "figures": 2},
    {"key": "over_shoulder", "label": "Over-the-Shoulder", "abbr": "OTS",
     "what": "Behind one subject, looking at the other.",
     "use": "Conversation coverage, point of contact.",
     "camera": {"shot_size": "medium_close", "angle": "eye_level", "lens_mm": 65, "height_m": 1.55, "movement": "static"},
     "figure": 0.8, "figures": 2, "foreground": True},
    {"key": "pov", "label": "Point-of-View", "abbr": "POV",
     "what": "The camera is the character's eyes.",
     "use": "Subjectivity, discovery, threat.",
     "camera": {"shot_size": "medium", "angle": "eye_level", "lens_mm": 28, "height_m": 1.6, "movement": "handheld"},
     "figure": 0.0},
    {"key": "insert", "label": "Insert / Detail Shot", "abbr": "INS",
     "what": "An object or action detail, cut in for emphasis.",
     "use": "Clues, props, hands doing things.",
     "camera": {"shot_size": "extreme_close_up", "angle": "high", "lens_mm": 100, "height_m": 1.2, "movement": "static"},
     "figure": 0.0, "object": True},
    {"key": "establishing", "label": "Establishing Shot", "abbr": "EST",
     "what": "Where and when we are — usually the first shot of a scene.",
     "use": "Orientation, mood, transitions between locations.",
     "camera": {"shot_size": "wide", "angle": "high", "lens_mm": 24, "height_m": 4.0, "movement": "push_in"},
     "figure": 0.15},
    {"key": "low_angle", "label": "Low Angle", "abbr": "LA",
     "what": "Camera below the subject, looking up.",
     "use": "Power, menace, monumentality.",
     "camera": {"shot_size": "medium", "angle": "low", "lens_mm": 28, "height_m": 0.6, "movement": "static"},
     "figure": 0.75},
    {"key": "high_angle", "label": "High Angle", "abbr": "HA",
     "what": "Camera above the subject, looking down.",
     "use": "Vulnerability, overview, smallness.",
     "camera": {"shot_size": "medium", "angle": "high", "lens_mm": 35, "height_m": 2.6, "movement": "static"},
     "figure": 0.7},
    {"key": "dutch", "label": "Dutch Angle", "abbr": "DA",
     "what": "The horizon is tilted.",
     "use": "Unease, disorientation, chaos.",
     "camera": {"shot_size": "medium", "angle": "dutch", "lens_mm": 28, "height_m": 1.5, "movement": "handheld"},
     "figure": 0.72, "tilt_deg": 18},
    {"key": "top_down", "label": "Top-Down", "abbr": "TD",
     "what": "Straight down from above.",
     "use": "Patterns, maps, bodies on floors, food.",
     "camera": {"shot_size": "wide", "angle": "overhead", "lens_mm": 24, "height_m": 5.0, "movement": "static"},
     "figure": 0.35},
    {"key": "eye_level", "label": "Eye Level", "abbr": "EL",
     "what": "Camera at the subject's eye height — neutral and honest.",
     "use": "Realism, documentary feel, trust.",
     "camera": {"shot_size": "medium", "angle": "eye_level", "lens_mm": 50, "height_m": 1.6, "movement": "static"},
     "figure": 0.72},
]

LENSES: list[dict] = [
    {"key": "ultra_wide", "label": "Ultra wide", "mm": 14, "fov_deg": 104, "depth": "everything sharp, stretched edges"},
    {"key": "wide", "label": "Wide", "mm": 24, "fov_deg": 84, "depth": "deep focus, expansive"},
    {"key": "35", "label": "35mm", "mm": 35, "fov_deg": 63, "depth": "natural, slightly wide"},
    {"key": "50", "label": "50mm", "mm": 50, "fov_deg": 47, "depth": "human eye, gentle separation"},
    {"key": "85", "label": "85mm", "mm": 85, "fov_deg": 28, "depth": "portrait compression, creamy background"},
    {"key": "telephoto", "label": "Telephoto", "mm": 135, "fov_deg": 18, "depth": "flattened, isolated subject"},
    {"key": "macro", "label": "Macro", "mm": 100, "fov_deg": 24, "depth": "razor-thin focus on tiny detail", "macro": True},
]

CAMERA_MOVES: list[dict] = [
    {"key": "static", "label": "Static", "what": "Locked off. Nothing moves but the subject.", "speed": None},
    {"key": "push_in", "label": "Push in", "what": "Camera moves toward the subject.", "speed": "slow"},
    {"key": "pull_out", "label": "Pull out", "what": "Camera moves away, revealing more.", "speed": "slow"},
    {"key": "pan", "label": "Pan", "what": "Camera turns left/right from a fixed spot.", "speed": "medium"},
    {"key": "tilt", "label": "Tilt", "what": "Camera turns up/down from a fixed spot.", "speed": "medium"},
    {"key": "tracking", "label": "Tracking", "what": "Camera travels alongside the subject.", "speed": "medium"},
    {"key": "orbit", "label": "Orbit", "what": "Camera circles the subject.", "speed": "slow"},
    {"key": "crane", "label": "Crane", "what": "Camera rises or descends through space.", "speed": "slow"},
    {"key": "handheld", "label": "Handheld", "what": "Organic, breathing frame.", "speed": "medium"},
    {"key": "whip_pan", "label": "Whip pan", "what": "Violent fast pan, motion blur.", "speed": "fast"},
]
MOVE_SPEEDS = ["very slow", "slow", "medium", "fast", "very fast"]
ANGLES = ["eye_level", "low", "high", "overhead", "dutch"]
SHOT_SIZES = ["extreme_wide", "wide", "full", "medium_wide", "medium", "medium_close",
              "close_up", "extreme_close_up"]

LIGHTING_PRESETS: list[dict] = [
    {"key": "cinematic_soft", "label": "Cinematic soft", "key_intensity": 0.7, "fill_intensity": 0.4,
     "rim_intensity": 0.5, "direction": "front-left 45°", "color_temp_k": 4300, "contrast": "medium",
     "ambient": 0.3, "practicals": "warm practicals in background", "mood": "polished, flattering"},
    {"key": "hard_noon", "label": "Hard noon", "key_intensity": 1.0, "fill_intensity": 0.15,
     "rim_intensity": 0.2, "direction": "top", "color_temp_k": 5600, "contrast": "high",
     "ambient": 0.5, "practicals": "", "mood": "harsh, exposed"},
    {"key": "golden_hour", "label": "Golden hour", "key_intensity": 0.8, "fill_intensity": 0.35,
     "rim_intensity": 0.7, "direction": "back-right, low", "color_temp_k": 3200, "contrast": "medium",
     "ambient": 0.4, "practicals": "", "mood": "warm, nostalgic"},
    {"key": "blue_hour", "label": "Blue hour", "key_intensity": 0.4, "fill_intensity": 0.4,
     "rim_intensity": 0.3, "direction": "ambient sky", "color_temp_k": 8000, "contrast": "low",
     "ambient": 0.6, "practicals": "tungsten windows and street lamps", "mood": "cool, contemplative"},
    {"key": "neon_night", "label": "Neon night", "key_intensity": 0.6, "fill_intensity": 0.3,
     "rim_intensity": 0.9, "direction": "side, colored", "color_temp_k": 6000, "contrast": "high",
     "ambient": 0.2, "practicals": "magenta and cyan neon signs", "mood": "electric, noir"},
    {"key": "horror_low_key", "label": "Horror low-key", "key_intensity": 0.5, "fill_intensity": 0.05,
     "rim_intensity": 0.3, "direction": "below / side", "color_temp_k": 4000, "contrast": "very high",
     "ambient": 0.05, "practicals": "single flickering bulb", "mood": "dread"},
    {"key": "studio", "label": "Studio", "key_intensity": 0.8, "fill_intensity": 0.6,
     "rim_intensity": 0.6, "direction": "three-point", "color_temp_k": 5000, "contrast": "low",
     "ambient": 0.5, "practicals": "", "mood": "clean, commercial"},
    {"key": "overcast", "label": "Overcast", "key_intensity": 0.6, "fill_intensity": 0.55,
     "rim_intensity": 0.1, "direction": "diffuse sky", "color_temp_k": 6500, "contrast": "very low",
     "ambient": 0.7, "practicals": "", "mood": "soft, melancholic"},
]

PACING_PROFILES: dict[str, dict] = {
    "slow": {"label": "Slow", "base_s": 7.0, "min_s": 3.0, "max_s": 15.0},
    "relaxed": {"label": "Relaxed", "base_s": 5.5, "min_s": 2.5, "max_s": 12.0},
    "normal": {"label": "Normal", "base_s": 4.0, "min_s": 1.5, "max_s": 10.0},
    "fast": {"label": "Fast", "base_s": 2.5, "min_s": 1.0, "max_s": 6.0},
    "trailer": {"label": "Trailer", "base_s": 1.8, "min_s": 0.7, "max_s": 4.0},
    "hypercut": {"label": "Hypercut", "base_s": 1.0, "min_s": 0.4, "max_s": 2.0},
    "custom": {"label": "Custom", "base_s": 4.0, "min_s": 0.1, "max_s": 600.0},
}
# shot-type multipliers on the pacing base: wide shots breathe, inserts snap
SHOT_DURATION_FACTOR = {"extreme_wide": 1.3, "establishing": 1.4, "wide": 1.2, "full": 1.1,
                        "medium_wide": 1.0, "two_shot": 1.05, "medium": 1.0, "over_shoulder": 1.0,
                        "medium_close": 0.95, "close_up": 0.9, "extreme_close_up": 0.75,
                        "insert": 0.6, "pov": 1.0, "low_angle": 1.0, "high_angle": 1.0,
                        "dutch": 0.9, "top_down": 1.1, "eye_level": 1.0}

PIPELINE_TEMPLATES: dict[str, dict] = {
    "cinematic_narrative": {"label": "Cinematic narrative", "media_strategy": "ai_video",
                            "pacing_profile": "normal", "audio": ["dialogue", "music", "ambience"],
                            "qa": "strict_visual", "aspect_ratio": "16:9", "default_scene_gap_s": 0.5},
    "animation": {"label": "Animation", "media_strategy": "image_animation", "pacing_profile": "relaxed",
                  "audio": ["dialogue", "music", "sfx"], "qa": "standard", "aspect_ratio": "16:9",
                  "default_scene_gap_s": 0.3},
    "documentary_montage": {"label": "Documentary montage", "media_strategy": "archival",
                            "pacing_profile": "relaxed", "audio": ["narration", "music"], "qa": "standard",
                            "aspect_ratio": "16:9", "default_scene_gap_s": 0.75},
    "product_commercial": {"label": "Product commercial", "media_strategy": "ai_video",
                           "pacing_profile": "fast", "audio": ["music", "sfx"], "qa": "strict_technical",
                           "aspect_ratio": "16:9", "default_scene_gap_s": 0.2},
    "social_short": {"label": "Social short", "media_strategy": "ai_video", "pacing_profile": "trailer",
                     "audio": ["music", "narration"], "qa": "standard", "aspect_ratio": "9:16",
                     "default_scene_gap_s": 0.0},
    "explainer": {"label": "Explainer", "media_strategy": "motion_graphics", "pacing_profile": "normal",
                  "audio": ["narration", "music"], "qa": "standard", "aspect_ratio": "16:9",
                  "default_scene_gap_s": 0.4},
    "talking_head": {"label": "Talking head", "media_strategy": "talking_head", "pacing_profile": "slow",
                     "audio": ["dialogue"], "qa": "standard", "aspect_ratio": "16:9",
                     "default_scene_gap_s": 0.5},
    "hybrid": {"label": "Hybrid AI + real footage", "media_strategy": "user_footage",
               "pacing_profile": "normal", "audio": ["dialogue", "music", "ambience"], "qa": "standard",
               "aspect_ratio": "16:9", "default_scene_gap_s": 0.5},
}

TRANSITIONS: list[dict] = [
    {"key": "cut", "label": "Cut", "duration_s": 0.0},
    {"key": "dissolve", "label": "Dissolve / crossfade", "duration_s": 0.5},
    {"key": "fade_black", "label": "Fade to black", "duration_s": 0.75},
    {"key": "fade_white", "label": "Fade to white", "duration_s": 0.75},
    {"key": "wipe", "label": "Wipe", "duration_s": 0.4},
]


def shot_type(key: str | None) -> dict | None:
    return next((st for st in SHOT_TYPES if st["key"] == key), None)


def lighting_preset(key: str | None) -> dict | None:
    return next((lp for lp in LIGHTING_PRESETS if lp["key"] == key), None)


def pacing(profile: str | None) -> dict:
    return PACING_PROFILES.get(profile or "normal", PACING_PROFILES["normal"])


def propose_duration(shot_type_key: str | None, profile: str | None = "normal",
                     dialogue_words: int = 0, action_complexity: float = 1.0,
                     importance: float = 1.0, custom_base_s: float | None = None) -> float:
    """Deterministic duration suggestion (spec M): pacing base × shot-type
    factor × complexity × importance, plus reading time for dialogue,
    clamped to the profile's range. Always just a default — editable."""
    p = pacing(profile)
    base = custom_base_s if (profile == "custom" and custom_base_s) else p["base_s"]
    factor = SHOT_DURATION_FACTOR.get(shot_type_key or "", 1.0)
    complexity = max(0.5, min(2.0, float(action_complexity or 1.0)))
    weight = max(0.5, min(2.0, float(importance or 1.0)))
    d = base * factor * complexity * weight
    if dialogue_words:
        d = max(d, dialogue_words / 2.6 + 0.8)   # ~155 wpm + a beat
    d = max(p["min_s"], min(p["max_s"], d))
    return round(d * 2) / 2   # half-second grid


# ------------------------------------------------------- user overrides ----
def _user(s: Session) -> dict:
    data = settings_store.get(s, "film_presets", None) or {}
    return data if isinstance(data, dict) else {}


def merged(s: Session) -> dict:
    """Built-ins + user customisations: favourites, per-shot-type overrides,
    custom shot types (key prefixed custom_)."""
    user = _user(s)
    shot_types = deepcopy(SHOT_TYPES)
    overrides = user.get("shot_type_overrides") or {}
    for st in shot_types:
        ov = overrides.get(st["key"])
        if isinstance(ov, dict):
            st["camera"] = {**st["camera"], **{k: v for k, v in (ov.get("camera") or {}).items()}}
            for k in ("label", "what", "use"):
                if ov.get(k):
                    st[k] = str(ov[k])[:200]
            st["customized"] = True
    for custom in user.get("custom_shot_types") or []:
        if isinstance(custom, dict) and custom.get("key") and custom.get("label"):
            key = "custom_" + str(custom["key"]).removeprefix("custom_")[:40]
            shot_types.append({"key": key, "label": str(custom["label"])[:80],
                               "abbr": str(custom.get("abbr") or "CUS")[:5],
                               "what": str(custom.get("what") or "")[:200],
                               "use": str(custom.get("use") or "")[:200],
                               "camera": dict(custom.get("camera") or {}), "figure": 0.7,
                               "custom": True})
    favorites = [k for k in user.get("favorites") or [] if isinstance(k, str)]
    for st in shot_types:
        st["favorite"] = st["key"] in favorites
    return {"shot_types": shot_types, "lenses": LENSES, "camera_moves": CAMERA_MOVES,
            "move_speeds": MOVE_SPEEDS, "angles": ANGLES, "shot_sizes": SHOT_SIZES,
            "lighting_presets": LIGHTING_PRESETS, "pacing_profiles": PACING_PROFILES,
            "pipeline_templates": PIPELINE_TEMPLATES, "transitions": TRANSITIONS,
            "favorites": favorites}


def save_user(s: Session, data: dict) -> dict:
    """Persist favourites / overrides / custom shot types (partial update)."""
    cur = _user(s)
    for key in ("favorites", "shot_type_overrides", "custom_shot_types"):
        if key in data and data[key] is not None:
            cur[key] = data[key]
    settings_store.put(s, "film_presets", cur)
    return merged(s)


def resolve_shot_type(s: Session | None, key: str | None) -> dict | None:
    if s is None:
        return shot_type(key)
    return next((st for st in merged(s)["shot_types"] if st["key"] == key), None)
