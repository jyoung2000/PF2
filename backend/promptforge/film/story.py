"""Story / script workspace (spec §12): deterministic script → scene
splitting (screenplay sluglines, numbered/markdown headings, or paragraph
blocks), character/location/time extraction from headings and dialogue
cues, and the pacing helpers the Director uses for shot durations."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from . import presets
from . import projects as proj_svc
from .models import FilmProject, FilmScene

_SLUG_RE = re.compile(r"^\s*(?:\d+[.)]?\s+)?(INT\.?/EXT\.?|EXT\.?/INT\.?|INT\.?|EXT\.?|I/E\.?)\s*[-–—.]?\s*(.+?)\s*$", re.I)
_HEADING_RE = re.compile(r"^\s*(?:#{1,3}\s+|scene\s+\d+\s*[:.\-–—]?\s*|\d+\.\s+)(.+?)\s*$", re.I)
_TIME_WORDS = ["dawn", "morning", "midday", "noon", "afternoon", "golden hour", "dusk",
               "sunset", "blue hour", "evening", "night", "late night", "continuous", "later"]
_CUE_RE = re.compile(r"^\s*([A-Z][A-Z0-9 .'’\-]{1,30}?)(?:\s*\(.*?\))?\s*:?\s*$")
_WEATHER = ["rain", "storm", "snow", "fog", "wind", "overcast", "clear", "haze", "smoke"]


@dataclass
class ParsedScene:
    title: str
    heading: str | None = None
    location: str | None = None
    time_of_day: str | None = None
    interior: bool | None = None
    weather: str | None = None
    text: str = ""
    characters: list[str] = field(default_factory=list)
    dialogue_words: int = 0

    def to_dict(self) -> dict:
        return {"title": self.title, "heading": self.heading, "location": self.location,
                "time_of_day": self.time_of_day, "interior": self.interior,
                "weather": self.weather, "text": self.text, "characters": self.characters,
                "dialogue_words": self.dialogue_words}


def _split_heading(rest: str) -> tuple[str, str | None]:
    """'WAREHOUSE - NIGHT' → ('Warehouse', 'night')."""
    parts = re.split(r"\s+[-–—]\s+|\s*[-–—]\s*(?=[A-Za-z ]+$)", rest.strip(), maxsplit=1)
    loc = parts[0].strip(" .-–—")
    tod = None
    if len(parts) > 1:
        tail = parts[1].strip().lower()
        for w in _TIME_WORDS:
            if w in tail:
                tod = {"noon": "midday", "sunset": "golden hour", "evening": "dusk"}.get(w, w)
                break
    if tod is None:
        low = rest.lower()
        for w in _TIME_WORDS:
            if re.search(rf"\b{re.escape(w)}\b", low):
                tod = {"noon": "midday", "sunset": "golden hour", "evening": "dusk"}.get(w, w)
                loc = re.sub(rf"\s*[-–—]?\s*\b{re.escape(w)}\b\s*$", "", loc, flags=re.I).strip(" .-–—")
                break
    return (loc.title() if loc.isupper() else loc), tod


def parse_script(text: str) -> list[ParsedScene]:
    """Screenplay/markdown/plain text → scenes. Deterministic: sluglines and
    headings start scenes; otherwise blank-line paragraph blocks (grouped in
    threes) become scenes. Never empty for non-empty input."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    scenes: list[ParsedScene] = []
    cur: ParsedScene | None = None
    saw_heading = False
    for raw in lines:
        line = raw.rstrip()
        m = _SLUG_RE.match(line)
        if m and len(line) < 120:
            loc, tod = _split_heading(m.group(2))
            cur = ParsedScene(title=loc or f"Scene {len(scenes) + 1}", heading=line.strip(),
                              location=loc or None, time_of_day=tod,
                              interior=("INT" in m.group(1).upper()))
            scenes.append(cur)
            saw_heading = True
            continue
        m = _HEADING_RE.match(line)
        if m and len(line) < 100 and not line.strip().endswith((".", ",")) and (
                line.lstrip().startswith("#") or re.match(r"^\s*(scene\s+\d+|\d+\.)", line, re.I)):
            loc, tod = _split_heading(m.group(1))
            cur = ParsedScene(title=(m.group(1).strip() or f"Scene {len(scenes) + 1}")[:120],
                              heading=line.strip(), location=loc or None, time_of_day=tod)
            scenes.append(cur)
            saw_heading = True
            continue
        if cur is None:
            if not line.strip():
                continue
            cur = ParsedScene(title="Scene 1")
            scenes.append(cur)
        cur.text += line + "\n"
    if saw_heading and scenes:
        # a headed script's preamble (FADE IN:, title cards) is not a scene
        scenes = [sc for sc in scenes if sc.heading or not _only_cues(sc.text)] or scenes
    if not saw_heading and scenes:
        # plain prose: paragraphs → scenes (groups of up to 3 paragraphs)
        paras = [p.strip() for p in re.split(r"\n\s*\n", scenes[0].text) if p.strip()]
        if len(paras) > 1:
            scenes = []
            for i in range(0, len(paras), 3):
                chunk = paras[i:i + 3]
                first = re.sub(r"\s+", " ", chunk[0])[:60].rstrip(" ,.;:")
                scenes.append(ParsedScene(title=first or f"Scene {len(scenes) + 1}",
                                          text="\n\n".join(chunk) + "\n"))
    for sc in scenes:
        sc.text = sc.text.strip("\n") + ("\n" if sc.text.strip() else "")
        sc.characters, sc.dialogue_words = _characters_and_dialogue(sc.text)
        low = sc.text.lower()
        sc.weather = next((w for w in _WEATHER if re.search(rf"\b{w}\w*\b", low)), None)
        if sc.time_of_day is None:
            for w in ("night", "dawn", "dusk", "morning", "afternoon", "midday"):
                if re.search(rf"\b{w}\b", low):
                    sc.time_of_day = w
                    break
    return scenes


_CUE_ONLY_RE = re.compile(r"^\s*(FADE (IN|OUT|TO BLACK)|CUT TO|DISSOLVE TO|SMASH CUT|TITLE|THE END)\s*[:.]?\s*$", re.I)


def _only_cues(text: str) -> bool:
    lines = [l for l in text.split("\n") if l.strip()]
    return bool(lines) and all(_CUE_ONLY_RE.match(l) for l in lines) or not lines


def _characters_and_dialogue(text: str) -> tuple[list[str], int]:
    names: list[str] = []
    words = 0
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = _CUE_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip().title()
        if name.upper() in ("INT", "EXT", "CUT TO", "FADE IN", "FADE OUT", "THE END", "CONTINUED"):
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if not nxt or _CUE_RE.match(nxt):
            continue
        if name not in names:
            names.append(name)
        words += len(nxt.split())
    return names, words


def import_script(s: Session, project: FilmProject, text: str, mode: str = "replace") -> list[FilmScene]:
    """Store the script and materialise scenes (mode replace | append).
    Existing shots survive only in append mode."""
    parsed = parse_script(text)
    project.script = text
    if mode == "replace":
        for sc in proj_svc.scenes_of(s, project.id):
            proj_svc.delete_scene(s, sc)
    created = []
    for ps in parsed:
        defaults = {k: v for k, v in (("time_of_day", ps.time_of_day), ("weather", ps.weather),
                                      ("location_name", ps.location),
                                      ("characters", ps.characters or None)) if v}
        sc = proj_svc.create_scene(s, project, title=ps.title, script_text=ps.text,
                                   summary=_summary(ps.text), defaults=defaults)
        created.append(sc)
    from . import events
    events.log(s, project.id, f"Script imported: {len(created)} scene(s)", kind="edit",
               stage="story", entity=("project", project.id),
               data={"mode": mode, "scenes": [sc.id for sc in created]})
    return created


def _summary(text: str, limit: int = 240) -> str | None:
    prose = " ".join(l.strip() for l in text.split("\n")
                     if l.strip() and not _CUE_RE.match(l))
    prose = re.sub(r"\s+", " ", prose).strip()
    return (prose[:limit].rsplit(" ", 1)[0] + "…") if len(prose) > limit else (prose or None)


def duration_for(shot_type_key: str | None, project: FilmProject | None,
                 dialogue_words: int = 0, complexity: float = 1.0, importance: float = 1.0) -> float:
    settings = (project.settings or {}) if project else {}
    return presets.propose_duration(shot_type_key, settings.get("pacing_profile", "normal"),
                                    dialogue_words, complexity, importance,
                                    settings.get("custom_shot_s"))
