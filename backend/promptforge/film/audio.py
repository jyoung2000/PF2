"""Audio department (spec N): tracks of every kind on the project timeline
with gain/mute/fades/anchors, a deterministic mix plan for export, and
capability flags that stay false until a provider declares TTS/music/SFX.
No provider is ever forced."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline import media
from . import capabilities, events, storage, timeline
from .models import FilmAudioTrack, FilmProject

KINDS = ("dialogue", "narration", "voice", "music", "ambience", "sfx")


class AudioError(ValueError):
    pass


def probe_duration(path) -> float | None:
    try:
        import json
        import subprocess
        proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                              capture_output=True, text=True, timeout=60)
        return float(json.loads(proc.stdout or "{}").get("format", {}).get("duration"))
    except Exception:
        return None


def add_track(s: Session, project: FilmProject, data: bytes, content_type: str | None, filename: str | None,
              kind: str = "music", label: str | None = None, anchor_kind: str = "timeline",
              anchor_id: int | None = None, offset_s: float = 0.0, gain_db: float = 0.0,
              source: str = "upload", provider: str | None = None, actor: str = "user") -> FilmAudioTrack:
    ext = storage.ext_for(content_type, filename, {**storage.AUDIO_TYPES, **storage.VIDEO_TYPES})
    if ext is None:
        raise AudioError("audio must be MP3, WAV, OGG, M4A, AAC or FLAC (video files are accepted for their audio)")
    if kind not in KINDS:
        raise AudioError(f"kind must be one of {', '.join(KINDS)}")
    if anchor_kind not in ("timeline", "shot", "scene"):
        raise AudioError("anchor_kind must be timeline | shot | scene")
    rel = storage.project_rel(project.id, "audio", storage.new_name(ext))
    full = storage.write(rel, data)
    duration = probe_duration(full)
    if duration is None:
        storage.remove(rel)
        raise AudioError("ffprobe could not read the audio file")
    t = FilmAudioTrack(project_id=project.id, kind=kind, label=(label or filename or kind)[:200], path=rel,
                       source=source, provider=provider, anchor_kind=anchor_kind, anchor_id=anchor_id,
                       offset_s=float(offset_s or 0), duration_s=duration, gain_db=float(gain_db or 0))
    s.add(t)
    s.flush()
    events.log(s, project.id, f"Audio track added: {t.label} ({kind}, {duration:.1f}s)", kind="edit", stage="audio",
               actor=actor, entity=("audio", t.id), data={"source": source, "anchor": [anchor_kind, anchor_id]})
    return t


def update_track(s: Session, t: FilmAudioTrack, **fields) -> FilmAudioTrack:
    for key in ("label",):
        if fields.get(key) is not None:
            t.label = str(fields[key])[:200]
    if fields.get("kind") in KINDS:
        t.kind = fields["kind"]
    if fields.get("anchor_kind") in ("timeline", "shot", "scene"):
        t.anchor_kind = fields["anchor_kind"]
    if "anchor_id" in fields:
        t.anchor_id = fields["anchor_id"]
    for key in ("offset_s", "gain_db", "trim_start_s", "fade_in_s", "fade_out_s"):
        if fields.get(key) is not None:
            setattr(t, key, float(fields[key]))
    if "trim_end_s" in fields:
        t.trim_end_s = None if fields["trim_end_s"] in (None, "") else float(fields["trim_end_s"])
    for key in ("muted", "loop"):
        if fields.get(key) is not None:
            setattr(t, key, bool(fields[key]))
    t.gain_db = max(-60.0, min(12.0, float(t.gain_db or 0)))
    s.flush()
    return t


def remove_track(s: Session, t: FilmAudioTrack) -> None:
    storage.remove(t.path)
    s.delete(t)
    s.flush()


def tracks_of(s: Session, project_id: int) -> list[FilmAudioTrack]:
    return list(s.execute(select(FilmAudioTrack).where(FilmAudioTrack.project_id == project_id)
                          .order_by(FilmAudioTrack.id.asc())).scalars())


def anchor_start(tl: dict, t: FilmAudioTrack) -> float | None:
    """Absolute start on the timeline for an anchored track (None when the
    anchor no longer exists)."""
    if t.anchor_kind == "timeline":
        return float(t.offset_s or 0)
    for sc in tl["scenes"]:
        if t.anchor_kind == "scene" and sc["id"] == t.anchor_id:
            return sc["start_s"] + float(t.offset_s or 0)
        for sh in sc["shots"]:
            if t.anchor_kind == "shot" and sh["id"] == t.anchor_id:
                return sh["start_s"] + float(t.offset_s or 0)
    return None


def track_dict(t: FilmAudioTrack, tl: dict | None = None) -> dict:
    d = {"id": t.id, "project_id": t.project_id, "kind": t.kind, "label": t.label, "url": storage.url_for(t.path),
         "source": t.source, "provider": t.provider, "anchor_kind": t.anchor_kind, "anchor_id": t.anchor_id,
         "offset_s": t.offset_s, "duration_s": t.duration_s, "trim_start_s": t.trim_start_s,
         "trim_end_s": t.trim_end_s, "gain_db": t.gain_db, "muted": bool(t.muted), "fade_in_s": t.fade_in_s,
         "fade_out_s": t.fade_out_s, "loop": bool(t.loop),
         "created_at": t.created_at.isoformat() if t.created_at else None}
    if tl is not None:
        d["start_s"] = anchor_start(tl, t)
        eff = (t.trim_end_s if t.trim_end_s is not None else (t.duration_s or 0)) - float(t.trim_start_s or 0)
        d["end_s"] = (d["start_s"] + max(0.0, eff)) if d["start_s"] is not None else None
        d["orphaned"] = d["start_s"] is None
    return d


def mix_plan(s: Session, project: FilmProject) -> dict:
    """What export will mix: every audible track with absolute times."""
    tl = timeline.compute(s, project)
    items = []
    for t in tracks_of(s, project.id):
        d = track_dict(t, tl)
        if d["muted"] or d["start_s"] is None:
            continue
        items.append(d)
    by_kind: dict[str, int] = {}
    for it in items:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    return {"runtime_s": tl["runtime_s"], "tracks": items, "by_kind": by_kind,
            "capabilities": {k: capabilities.EXTRA_CAPABILITIES.get(k) for k in ("tts", "music", "sfx", "audio_enhance")}}


def capability_flags(s: Session) -> dict:
    m = capabilities.matrix(s)["extra"]
    return {k: m[k] for k in ("tts", "music", "sfx", "audio_enhance", "talking_head", "lip_sync", "transcription")}
