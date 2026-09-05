"""Subtitles / captions (spec O): one track per project; cues carry
optional shot anchors (shot_id + relative times) so they re-sync when
durations change; SRT/VTT export/import; burn-in at export via ffmpeg.
Word-level timing is only available when a provider declares it (none
does), so cues are sentence-level and editable."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events
from . import projects as proj_svc
from . import story, timeline
from .models import FilmProject, FilmSubtitle

DEFAULT_STYLE = {"font_size": 28, "color": "#FFFFFF", "outline": 2, "position": "bottom", "font": "DejaVu Sans"}


def get(s: Session, project_id: int) -> FilmSubtitle | None:
    return s.execute(select(FilmSubtitle).where(FilmSubtitle.project_id == project_id)).scalar_one_or_none()


def ensure(s: Session, project: FilmProject) -> FilmSubtitle:
    st = get(s, project.id)
    if st is None:
        st = FilmSubtitle(project_id=project.id, cues=[], style=dict(DEFAULT_STYLE))
        s.add(st)
        s.flush()
    return st


def _clean_cues(cues) -> list[dict]:
    out = []
    for i, c in enumerate(cues or []):
        if not isinstance(c, dict):
            continue
        try:
            start = float(c.get("start_s", 0))
            end = float(c.get("end_s", start + 2))
        except (TypeError, ValueError):
            continue
        text = str(c.get("text") or "").strip()
        if not text:
            continue
        cue = {"id": int(c.get("id") or i + 1), "start_s": round(max(0.0, start), 3),
               "end_s": round(max(start + 0.2, end), 3), "text": text[:400]}
        if c.get("shot_id"):
            cue["shot_id"] = int(c["shot_id"])
            cue["rel_start_s"] = float(c.get("rel_start_s") or 0)
            cue["rel_end_s"] = float(c.get("rel_end_s") or (cue["rel_start_s"] + (end - start)))
        out.append(cue)
    out.sort(key=lambda c: c["start_s"])
    for n, c in enumerate(out, 1):
        c["id"] = n
    return out


def set_cues(s: Session, project: FilmProject, cues, source: str = "manual", style: dict | None = None,
             burn_in: bool | None = None, language: str | None = None, actor: str = "user") -> FilmSubtitle:
    st = ensure(s, project)
    st.cues = _clean_cues(cues)
    st.source = source
    if style is not None:
        st.style = {**DEFAULT_STYLE, **{k: v for k, v in style.items() if k in DEFAULT_STYLE}}
    if burn_in is not None:
        st.burn_in = bool(burn_in)
    if language:
        st.language = str(language)[:10]
    s.flush()
    events.log(s, project.id, f"Subtitles updated: {len(st.cues)} cue(s) ({source})", kind="edit", stage="audio",
               actor=actor, entity=("subtitles", st.id), data={"cues": len(st.cues), "burn_in": st.burn_in})
    return st


def from_script(s: Session, project: FilmProject) -> FilmSubtitle:
    """Deterministic captions from the script's dialogue: each scene's
    lines are spread across its shots in order, anchored to those shots."""
    tl = timeline.compute(s, project)
    cues = []
    for sc_tl in tl["scenes"]:
        scene = next((sc for sc in proj_svc.scenes_of(s, project.id) if sc.id == sc_tl["id"]), None)
        if scene is None or not scene.script_text:
            continue
        lines = _dialogue_lines(scene.script_text)
        shots = sc_tl["shots"]
        if not lines or not shots:
            continue
        total = sum(sh["duration_s"] for sh in shots) or 1.0
        words_total = sum(len(l[1].split()) for l in lines) or 1
        t = 0.0
        for speaker, text in lines:
            dur = max(1.0, total * len(text.split()) / words_total)
            rel = t
            shot = shots[0]
            for sh in shots:
                if sh["start_s"] - sc_tl["start_s"] <= rel:
                    shot = sh
            cues.append({"start_s": sc_tl["start_s"] + rel, "end_s": sc_tl["start_s"] + rel + dur,
                         "text": text, "shot_id": shot["id"],
                         "rel_start_s": sc_tl["start_s"] + rel - shot["start_s"],
                         "rel_end_s": sc_tl["start_s"] + rel + dur - shot["start_s"], "speaker": speaker})
            t += dur
    return set_cues(s, project, cues, source="script")


def _dialogue_lines(text: str) -> list[tuple[str, str]]:
    out = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = story._CUE_RE.match(line)
        if not m:
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if nxt and not story._CUE_RE.match(nxt):
            out.append((m.group(1).strip().title(), nxt))
    return out


def resync(s: Session, project: FilmProject) -> FilmSubtitle:
    """Recompute absolute times for anchored cues after timing changes;
    unanchored cues keep their absolute times."""
    st = ensure(s, project)
    tl = timeline.compute(s, project)
    starts = {sh["id"]: sh["start_s"] for sc in tl["scenes"] for sh in sc["shots"]}
    cues = []
    for c in st.cues or []:
        c = dict(c)
        if c.get("shot_id") in starts:
            base = starts[c["shot_id"]]
            c["start_s"] = round(base + float(c.get("rel_start_s") or 0), 3)
            c["end_s"] = round(base + float(c.get("rel_end_s") or (c.get("rel_start_s") or 0) + 2), 3)
        cues.append(c)
    st.cues = _clean_cues(cues)
    s.flush()
    return st


def _tc(seconds: float, sep: str = ",") -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d}{sep}{ms:03d}"


def to_srt(st: FilmSubtitle) -> str:
    out = []
    for i, c in enumerate(st.cues or [], 1):
        out.append(f"{i}\n{_tc(c['start_s'])} --> {_tc(c['end_s'])}\n{c['text']}\n")
    return "\n".join(out)


def to_vtt(st: FilmSubtitle) -> str:
    out = ["WEBVTT", ""]
    for c in st.cues or []:
        out.append(f"{_tc(c['start_s'], '.')} --> {_tc(c['end_s'], '.')}\n{c['text']}\n")
    return "\n".join(out)


_SRT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


def parse(text: str) -> list[dict]:
    """SRT or VTT → cues."""
    cues = []
    blocks = re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [l for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        if lines[0].strip().upper().startswith("WEBVTT"):
            lines = lines[1:]
            if not lines:
                continue
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        times = _SRT_TIME.findall(lines[idx])
        if len(times) < 2:
            continue
        def secs(t):
            h, m, sec, ms = t
            return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms.ljust(3, "0")) / 1000
        text_lines = lines[idx + 1:]
        cues.append({"start_s": secs(times[0]), "end_s": secs(times[1]), "text": " ".join(l.strip() for l in text_lines)})
    return cues


def validate(s: Session, project: FilmProject) -> dict:
    st = get(s, project.id)
    if st is None or not st.cues:
        return {"status": "PASS", "message": "No subtitle track (nothing to validate).", "cues": 0}
    tl = timeline.compute(s, project)
    problems = []
    prev_end = -1.0
    for c in st.cues:
        if c["end_s"] <= c["start_s"]:
            problems.append(f"cue {c['id']} ends before it starts")
        if c["start_s"] < prev_end - 0.001:
            problems.append(f"cue {c['id']} overlaps the previous cue")
        if c["end_s"] > tl["runtime_s"] + 0.5:
            problems.append(f"cue {c['id']} runs past the end of the film")
        prev_end = c["end_s"]
    if problems:
        return {"status": "FAIL" if any("before it starts" in p for p in problems) else "WARN",
                "message": "; ".join(problems[:5]), "cues": len(st.cues), "problems": problems}
    return {"status": "PASS", "message": f"{len(st.cues)} cue(s) valid.", "cues": len(st.cues)}


def subtitle_dict(st: FilmSubtitle | None) -> dict:
    if st is None:
        return {"cues": [], "style": dict(DEFAULT_STYLE), "source": None, "burn_in": False, "language": "en"}
    return {"id": st.id, "project_id": st.project_id, "language": st.language, "cues": st.cues or [],
            "style": {**DEFAULT_STYLE, **(st.style or {})}, "source": st.source, "burn_in": bool(st.burn_in),
            "updated_at": st.updated_at.isoformat() if st.updated_at else None}
