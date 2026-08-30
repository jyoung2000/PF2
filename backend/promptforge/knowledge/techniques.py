"""Technique taxonomy (6.6, D13) — eyecanndy-inspired fixed vocabulary of
visual techniques. Deterministic keyword pass runs free on every ingest; the
LLM pass refines video tags when budget allows."""
from __future__ import annotations

import re

# slug -> keyword variants found in prompts/commands
TAXONOMY: dict[str, list[str]] = {
    "zoom": ["zoom in", "zoom out", "zoom-in", "zoom-out", "crash zoom", "slow zoom"],
    "dolly": ["dolly in", "dolly out", "dolly-in", "dolly-out", "dolly shot", "push in", "pull out", "pull back"],
    "dolly-zoom": ["dolly zoom", "vertigo effect", "zolly"],
    "whip-pan": ["whip pan", "whip-pan", "swish pan"],
    "pan": ["camera pan", "panning shot", "slow pan", "pan across", "pan left", "pan right"],
    "tilt": ["tilt up", "tilt down", "camera tilt"],
    "orbit": ["orbit", "orbiting", "arc shot", "360 shot", "camera circles", "rotating around"],
    "tracking": ["tracking shot", "follow shot", "camera follows", "following the"],
    "crane": ["crane shot", "crane up", "crane down", "jib shot", "rising shot", "descending shot"],
    "handheld": ["handheld", "hand-held", "shaky cam", "documentary style camera"],
    "steadicam": ["steadicam", "gimbal", "smooth glide"],
    "fpv": ["fpv", "drone dive", "fpv drone", "drone fly-through", "flythrough", "fly through"],
    "aerial": ["aerial shot", "aerial view", "drone shot", "birds eye", "bird's-eye", "top-down shot"],
    "pov": ["pov shot", "first person view", "first-person view", "point of view shot"],
    "match-cut": ["match cut", "match-cut"],
    "jump-cut": ["jump cut", "jump-cut"],
    "morph": ["morph", "morphing", "seamless transformation", "transforms into"],
    "transition": ["seamless transition", "scene transition", "whip transition"],
    "timelapse": ["timelapse", "time-lapse", "time lapse"],
    "hyperlapse": ["hyperlapse", "hyper-lapse"],
    "slow-motion": ["slow motion", "slow-motion", "slo-mo", "slowmo", "120fps", "240fps", "bullet time"],
    "speed-ramp": ["speed ramp", "speed-ramp", "time remap"],
    "macro": ["macro shot", "macro photography", "macro lens", "extreme close-up of texture"],
    "tilt-shift": ["tilt shift", "tilt-shift", "miniature effect", "diorama effect"],
    "fisheye": ["fisheye", "fish-eye", "8mm lens"],
    "anamorphic": ["anamorphic", "2.39:1", "oval bokeh", "horizontal flare"],
    "rack-focus": ["rack focus", "focus pull", "shifting focus"],
    "long-exposure": ["long exposure", "light trails", "motion trails"],
    "double-exposure": ["double exposure", "double-exposure"],
    "loop": ["seamless loop", "perfect loop", "looping animation", "cinemagraph"],
    "stop-motion": ["stop motion", "stop-motion", "claymation", "cutout animation"],
    "glitch": ["glitch", "datamosh", "vhs distortion", "signal noise"],
    "split-screen": ["split screen", "split-screen"],
    "zoetrope": ["zoetrope"],
    "kaleidoscope": ["kaleidoscope", "kaleidoscopic"],
    "reverse": ["in reverse", "reversed footage", "playing backwards", "rewind effect"],
    "snorricam": ["snorricam", "body-mounted camera"],
    "crash-cam": ["crash cam", "impact shot"],
    "underwater": ["underwater shot", "submerged camera"],
    "one-take": ["one take", "oner", "long take", "single continuous shot"],
}

_compiled: list[tuple[str, re.Pattern]] | None = None


def _patterns() -> list[tuple[str, re.Pattern]]:
    global _compiled
    if _compiled is None:
        _compiled = []
        for slug, variants in TAXONOMY.items():
            pattern = "|".join(re.escape(v) for v in variants)
            _compiled.append((slug, re.compile(rf"(?<![\w-])(?:{pattern})(?![\w-])",
                                               re.IGNORECASE)))
    return _compiled


def detect_techniques(text: str | None) -> list[str]:
    """Deterministic keyword pass — free, runs on every ingest."""
    if not text:
        return []
    found = []
    for slug, pattern in _patterns():
        if pattern.search(text):
            found.append(slug)
    return found


def all_slugs() -> list[str]:
    return sorted(TAXONOMY)
