"""Editor sequence engine (Editor spec, E2): the professional multi-track
timeline behind /film/editor. A project gains a sequence when it is built
from the storyboard (or by hand); from then on the sequence — not the
storyboard-derived timing — drives preview and export. Positions are
LITERAL: a clip renders exactly at [start_s, start_s + duration_s), so the
export always matches what the editor shows. Dissolve/wipe transitions
therefore never shift timing: the outgoing clip's last frame is held and
cross-faded into the incoming clip in place (no handle media required).

Every mutating operation pushes a full snapshot onto a bounded undo stack
(film_revisions) and clears the redo stack, so undo/redo survive reloads
and restarts and restore exact ids."""
from __future__ import annotations

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session

from . import events
from . import projects as proj_svc
from . import storage
from . import timeline
from .models import (CLIP_SOURCES, TRACK_KINDS, FilmAudioTrack, FilmClip,
                     FilmMarker, FilmProject, FilmRevision, FilmShot,
                     FilmTake, FilmTimelineClip, FilmTimelineTrack)

EPS = 1e-6
UNDO_CAP = 100
MIN_CLIP_S = 0.05
SPEED_MIN, SPEED_MAX = 0.1, 10.0
KIND_ORDER = {"video": 0, "audio": 1, "caption": 2}
# which clip sources may sit on which track kind
TRACK_SOURCES = {"video": ("take", "footage"), "audio": ("take", "footage", "audio"),
                 "caption": ("caption",)}


class SequenceError(ValueError):
    pass


class SequenceConflict(SequenceError):
    """State conflict (sequence already built, locked track…) → HTTP 409."""


def _round(v: float) -> float:
    return round(float(v), 3)


# ---------------------------------------------------------------- queries ---
def tracks_of(s: Session, project_id: int) -> list[FilmTimelineTrack]:
    rows = s.execute(select(FilmTimelineTrack).where(FilmTimelineTrack.project_id == project_id)).scalars()
    return sorted(rows, key=lambda t: (KIND_ORDER.get(t.kind, 9), t.position, t.id))


def clips_of(s: Session, project_id: int) -> list[FilmTimelineClip]:
    return list(s.execute(select(FilmTimelineClip).where(FilmTimelineClip.project_id == project_id)
                          .order_by(FilmTimelineClip.start_s, FilmTimelineClip.id)).scalars())


def markers_of(s: Session, project_id: int) -> list[FilmMarker]:
    return list(s.execute(select(FilmMarker).where(FilmMarker.project_id == project_id)
                          .order_by(FilmMarker.t_s, FilmMarker.id)).scalars())


def exists(s: Session, project_id: int) -> bool:
    return s.execute(select(FilmTimelineTrack.id).where(FilmTimelineTrack.project_id == project_id)
                     .limit(1)).first() is not None


# ------------------------------------------------------------- validation ---
def _check_overlaps(s: Session, project_id: int) -> None:
    by_track: dict[int, list[FilmTimelineClip]] = {}
    for c in clips_of(s, project_id):
        by_track.setdefault(c.track_id, []).append(c)
    for cs in by_track.values():
        cs.sort(key=lambda c: (c.start_s, c.id))
        for a, b in zip(cs, cs[1:]):
            if a.start_s + a.duration_s - EPS > b.start_s:
                raise SequenceError(
                    f"Clips overlap on the same track: '{a.label or a.id}' ends at "
                    f"{_round(a.start_s + a.duration_s)}s but '{b.label or b.id}' starts at "
                    f"{_round(b.start_s)}s. Move one, or put it on another track.")


def _check_clip(c: FilmTimelineClip) -> None:
    # before the first flush, unset columns are still None (defaults apply at INSERT)
    if (c.start_s or 0.0) < -EPS:
        raise SequenceError("A clip cannot start before 0.")
    if (c.duration_s if c.duration_s is not None else 1.0) < MIN_CLIP_S:
        raise SequenceError(f"Clip duration must be at least {MIN_CLIP_S}s.")
    if (c.trim_start_s or 0.0) < -EPS:
        raise SequenceError("Trim cannot be negative.")
    if not (SPEED_MIN <= (c.speed if c.speed is not None else 1.0) <= SPEED_MAX):
        raise SequenceError(f"Speed must be between {SPEED_MIN} and {SPEED_MAX}.")


def _track_guard(t: FilmTimelineTrack) -> None:
    if t.locked:
        raise SequenceConflict(f"Track '{t.label or t.kind}' is locked — unlock it to edit its clips.")


def _source_guard(track: FilmTimelineTrack, source_kind: str) -> None:
    if source_kind not in CLIP_SOURCES:
        raise SequenceError(f"Unknown clip source '{source_kind}'.")
    if source_kind not in TRACK_SOURCES.get(track.kind, ()):
        raise SequenceError(f"A {source_kind} clip cannot go on a {track.kind} track.")


# ------------------------------------------------------------ undo / redo ---
def _snapshot(s: Session, project_id: int) -> dict:
    def track_row(t: FilmTimelineTrack) -> dict:
        return {"id": t.id, "kind": t.kind, "position": t.position, "label": t.label,
                "muted": t.muted, "solo": t.solo, "locked": t.locked}

    def clip_row(c: FilmTimelineClip) -> dict:
        return {"id": c.id, "track_id": c.track_id, "source_kind": c.source_kind,
                "take_id": c.take_id, "footage_id": c.footage_id, "audio_track_id": c.audio_track_id,
                "shot_id": c.shot_id, "label": c.label, "start_s": c.start_s,
                "duration_s": c.duration_s, "trim_start_s": c.trim_start_s, "speed": c.speed,
                "gain_db": c.gain_db, "muted": c.muted, "fade_in_s": c.fade_in_s,
                "fade_out_s": c.fade_out_s, "effects": c.effects or {},
                "transition_after": c.transition_after, "data": c.data or {}}

    def marker_row(m: FilmMarker) -> dict:
        return {"id": m.id, "t_s": m.t_s, "label": m.label, "color": m.color, "note": m.note}

    return {"tracks": [track_row(t) for t in tracks_of(s, project_id)],
            "clips": [clip_row(c) for c in clips_of(s, project_id)],
            "markers": [marker_row(m) for m in markers_of(s, project_id)]}


def _restore(s: Session, project_id: int, snap: dict) -> None:
    s.execute(sa_delete(FilmTimelineClip).where(FilmTimelineClip.project_id == project_id))
    s.execute(sa_delete(FilmTimelineTrack).where(FilmTimelineTrack.project_id == project_id))
    s.execute(sa_delete(FilmMarker).where(FilmMarker.project_id == project_id))
    s.flush()
    for t in snap.get("tracks", []):
        s.add(FilmTimelineTrack(project_id=project_id, **t))
    s.flush()
    for c in snap.get("clips", []):
        s.add(FilmTimelineClip(project_id=project_id, **c))
    for m in snap.get("markers", []):
        s.add(FilmMarker(project_id=project_id, **m))
    s.flush()


def _push_undo(s: Session, project_id: int, label: str) -> None:
    s.add(FilmRevision(project_id=project_id, stack="undo", label=label,
                       snapshot=_snapshot(s, project_id)))
    s.execute(sa_delete(FilmRevision).where(FilmRevision.project_id == project_id,
                                            FilmRevision.stack == "redo"))
    ids = [r for (r,) in s.execute(select(FilmRevision.id)
                                   .where(FilmRevision.project_id == project_id,
                                          FilmRevision.stack == "undo")
                                   .order_by(FilmRevision.id.desc()))]
    if len(ids) > UNDO_CAP:
        s.execute(sa_delete(FilmRevision).where(FilmRevision.id.in_(ids[UNDO_CAP:])))
    s.flush()


def _pop(s: Session, project_id: int, stack: str) -> FilmRevision | None:
    return s.execute(select(FilmRevision).where(FilmRevision.project_id == project_id,
                                                FilmRevision.stack == stack)
                     .order_by(FilmRevision.id.desc()).limit(1)).scalar_one_or_none()


def undo(s: Session, project: FilmProject) -> dict:
    rev = _pop(s, project.id, "undo")
    if rev is None:
        raise SequenceConflict("Nothing to undo.")
    s.add(FilmRevision(project_id=project.id, stack="redo", label=rev.label,
                       snapshot=_snapshot(s, project.id)))
    _restore(s, project.id, rev.snapshot)
    label = rev.label
    s.delete(rev)
    s.flush()
    events.log(s, project.id, f"Undo: {label}", kind="edit", stage="editor",
               entity=("project", project.id))
    return sequence_dict(s, project)


def redo(s: Session, project: FilmProject) -> dict:
    rev = _pop(s, project.id, "redo")
    if rev is None:
        raise SequenceConflict("Nothing to redo.")
    s.add(FilmRevision(project_id=project.id, stack="undo", label=rev.label,
                       snapshot=_snapshot(s, project.id)))
    _restore(s, project.id, rev.snapshot)
    label = rev.label
    s.delete(rev)
    s.flush()
    events.log(s, project.id, f"Redo: {label}", kind="edit", stage="editor",
               entity=("project", project.id))
    return sequence_dict(s, project)


def history(s: Session, project_id: int) -> dict:
    rows = s.execute(select(FilmRevision.id, FilmRevision.stack, FilmRevision.label,
                            FilmRevision.created_at)
                     .where(FilmRevision.project_id == project_id)
                     .order_by(FilmRevision.id.desc()).limit(UNDO_CAP * 2)).all()
    return {"undo": [{"id": r.id, "label": r.label, "at": r.created_at.isoformat() if r.created_at else None}
                     for r in rows if r.stack == "undo"],
            "redo": [{"id": r.id, "label": r.label, "at": r.created_at.isoformat() if r.created_at else None}
                     for r in rows if r.stack == "redo"]}


# ------------------------------------------------------------------ build ---
def build_from_storyboard(s: Session, project: FilmProject, replace: bool = False,
                          actor: str = "user") -> dict:
    """Materialise the storyboard into an editable sequence: one video clip
    per shot at the exact storyboard timing (scene gaps become empty track
    space), shot/scene transitions carried onto the clips, existing project
    audio tracks laid out as audio clips."""
    if exists(s, project.id):
        if not replace:
            raise SequenceConflict("This project already has a sequence. Rebuild replaces the "
                                   "current edit (undo restores it).")
        _push_undo(s, project.id, "rebuild from storyboard")
        s.execute(sa_delete(FilmTimelineClip).where(FilmTimelineClip.project_id == project.id))
        s.execute(sa_delete(FilmTimelineTrack).where(FilmTimelineTrack.project_id == project.id))
        s.flush()
    v1 = FilmTimelineTrack(project_id=project.id, kind="video", position=0, label="V1")
    a1 = FilmTimelineTrack(project_id=project.id, kind="audio", position=0, label="A1")
    c1 = FilmTimelineTrack(project_id=project.id, kind="caption", position=0, label="C1")
    s.add_all([v1, a1, c1])
    s.flush()
    tl = timeline.compute(s, project)
    settings = proj_svc.merge_settings(project.settings, None)
    default_tr = settings.get("default_transition") or {"kind": "cut", "duration_s": 0.0}
    t = 0.0
    n_shots = 0
    for si, sc in enumerate(tl["scenes"]):
        shots = sc["shots"]
        for j, sh in enumerate(shots):
            shot = s.get(FilmShot, sh["id"])
            take = s.get(FilmTake, shot.selected_take_id) if shot and shot.selected_take_id else None
            last_in_scene = j == len(shots) - 1
            tr = sh["transition"]
            if last_in_scene and si < len(tl["scenes"]) - 1:
                tr = sc["transition"] or default_tr
            s.add(FilmTimelineClip(
                project_id=project.id, track_id=v1.id, source_kind="take",
                take_id=take.id if take else None, shot_id=sh["id"],
                label=f"{sh['label']} {sh['title'] or ''}".strip(),
                start_s=_round(t), duration_s=_round(sh["duration_s"]),
                transition_after=(tr if tr and tr.get("kind") != "cut" else None),
                data={"built": True, "scene_id": sc["id"]}))
            t += float(sh["duration_s"])
            n_shots += 1
        if si < len(tl["scenes"]) - 1:
            t += float(sc["gap_after_s"] or 0.0)
    for at in s.execute(select(FilmAudioTrack).where(FilmAudioTrack.project_id == project.id)
                        .order_by(FilmAudioTrack.id)).scalars():
        from . import audio as audio_svc
        start = audio_svc.anchor_start(tl, at)
        if start is None:            # orphaned anchor — keep it, parked at 0
            start = 0.0
        dur = at.duration_s
        if dur is not None and at.trim_end_s is not None:
            dur = min(dur, at.trim_end_s) - at.trim_start_s
        elif dur is not None:
            dur = dur - at.trim_start_s
        s.add(FilmTimelineClip(
            project_id=project.id, track_id=a1.id, source_kind="audio",
            audio_track_id=at.id, label=at.label or at.kind,
            start_s=_round(max(0.0, start)), duration_s=_round(max(MIN_CLIP_S, dur or 3.0)),
            trim_start_s=at.trim_start_s or 0.0, gain_db=at.gain_db or 0.0, muted=at.muted,
            fade_in_s=at.fade_in_s or 0.0, fade_out_s=at.fade_out_s or 0.0,
            data={"built": True, "kind": at.kind, "loop": bool(at.loop)}))
    s.flush()
    _check_overlaps(s, project.id)
    events.log(s, project.id, f"Sequence built from storyboard ({n_shots} shots)", kind="edit",
               stage="editor", actor=actor, entity=("project", project.id),
               data={"shots": n_shots})
    return sequence_dict(s, project)


def drop_sequence(s: Session, project: FilmProject, actor: str = "user") -> None:
    _push_undo(s, project.id, "delete sequence")
    s.execute(sa_delete(FilmTimelineClip).where(FilmTimelineClip.project_id == project.id))
    s.execute(sa_delete(FilmTimelineTrack).where(FilmTimelineTrack.project_id == project.id))
    s.flush()
    events.log(s, project.id, "Sequence deleted (storyboard timing drives export again)",
               kind="edit", stage="editor", actor=actor, entity=("project", project.id))


# ----------------------------------------------------------------- tracks ---
def add_track(s: Session, project: FilmProject, kind: str, label: str | None = None) -> FilmTimelineTrack:
    if kind not in TRACK_KINDS:
        raise SequenceError(f"Unknown track kind '{kind}'.")
    _push_undo(s, project.id, f"add {kind} track")
    existing = [t for t in tracks_of(s, project.id) if t.kind == kind]
    prefix = {"video": "V", "audio": "A", "caption": "C"}[kind]
    t = FilmTimelineTrack(project_id=project.id, kind=kind, position=len(existing),
                          label=label or f"{prefix}{len(existing) + 1}")
    s.add(t)
    s.flush()
    return t


def patch_track(s: Session, project: FilmProject, track: FilmTimelineTrack, **fields) -> FilmTimelineTrack:
    editable = {"label", "muted", "solo", "locked", "position"}
    changes = {k: v for k, v in fields.items() if k in editable and v is not None}
    if not changes:
        return track
    # mute/solo/lock toggles are cheap view state — no undo entry for those
    if "position" in changes or "label" in changes:
        _push_undo(s, project.id, "arrange tracks")
    for k, v in changes.items():
        setattr(track, k, v)
    s.flush()
    return track


def delete_track(s: Session, project: FilmProject, track: FilmTimelineTrack) -> None:
    _track_guard(track)
    _push_undo(s, project.id, f"delete track {track.label or track.kind}")
    s.execute(sa_delete(FilmTimelineClip).where(FilmTimelineClip.track_id == track.id))
    s.delete(track)
    s.flush()


# ------------------------------------------------------------------ clips ---
def _source_defaults(s: Session, source_kind: str, take_id: int | None, footage_id: int | None,
                     audio_track_id: int | None, data: dict) -> tuple[float | None, str | None]:
    """(natural source duration, default label)."""
    if source_kind == "take" and take_id:
        t = s.get(FilmTake, take_id)
        if t is None:
            raise SequenceError("Take not found.")
        return t.duration_s, f"take {t.number}"
    if source_kind == "footage" and footage_id:
        f = s.get(FilmClip, footage_id)
        if f is None:
            raise SequenceError("Footage clip not found.")
        return f.duration_s, f.title or f.source
    if source_kind == "audio" and audio_track_id:
        a = s.get(FilmAudioTrack, audio_track_id)
        if a is None:
            raise SequenceError("Audio track not found.")
        return a.duration_s, a.label or a.kind
    if source_kind == "caption":
        return None, (data.get("text") or "caption")[:60]
    raise SequenceError(f"A {source_kind} clip needs its source id.")


def add_clip(s: Session, project: FilmProject, track: FilmTimelineTrack, source_kind: str,
             start_s: float, duration_s: float | None = None, take_id: int | None = None,
             footage_id: int | None = None, audio_track_id: int | None = None,
             shot_id: int | None = None, label: str | None = None,
             data: dict | None = None) -> dict:
    _track_guard(track)
    _source_guard(track, source_kind)
    data = data or {}
    natural, default_label = _source_defaults(s, source_kind, take_id, footage_id, audio_track_id, data)
    if duration_s is None:
        duration_s = natural or 3.0
    _push_undo(s, project.id, "add clip")
    c = FilmTimelineClip(project_id=project.id, track_id=track.id, source_kind=source_kind,
                         take_id=take_id, footage_id=footage_id, audio_track_id=audio_track_id,
                         shot_id=shot_id, label=label or default_label,
                         start_s=_round(max(0.0, start_s)), duration_s=_round(duration_s), data=data)
    _check_clip(c)
    s.add(c)
    s.flush()
    _check_overlaps(s, project.id)
    return sequence_dict(s, project)


CLIP_FIELDS = {"track_id", "start_s", "duration_s", "trim_start_s", "speed", "gain_db",
               "muted", "fade_in_s", "fade_out_s", "effects", "transition_after", "label", "data"}


def _apply_clip_patch(s: Session, project: FilmProject, clip: FilmTimelineClip, fields: dict) -> None:
    track = s.get(FilmTimelineTrack, clip.track_id)
    _track_guard(track)
    if "track_id" in fields and fields["track_id"] is not None and fields["track_id"] != clip.track_id:
        dest = s.get(FilmTimelineTrack, fields["track_id"])
        if dest is None or dest.project_id != project.id:
            raise SequenceError("Destination track not found.")
        _track_guard(dest)
        _source_guard(dest, clip.source_kind)
        clip.track_id = dest.id
    for k in ("start_s", "duration_s", "trim_start_s", "speed", "gain_db", "fade_in_s", "fade_out_s"):
        if k in fields and fields[k] is not None:
            setattr(clip, k, _round(fields[k]) if k != "speed" else float(fields[k]))
    for k in ("muted", "label"):
        if k in fields and fields[k] is not None:
            setattr(clip, k, fields[k])
    for k in ("effects", "transition_after", "data"):
        if k in fields:                          # None clears transition_after
            if fields[k] is not None or k == "transition_after":
                setattr(clip, k, fields[k])
    _check_clip(clip)


def patch_clip(s: Session, project: FilmProject, clip: FilmTimelineClip, label_op: str | None = None,
               **fields) -> dict:
    _push_undo(s, project.id, label_op or "edit clip")
    _apply_clip_patch(s, project, clip, fields)
    s.flush()
    _check_overlaps(s, project.id)
    return sequence_dict(s, project)


def batch_patch(s: Session, project: FilmProject, ops: list[dict], label: str = "move clips") -> dict:
    """Apply several clip patches as ONE undoable step (multi-select drags)."""
    if not ops:
        return sequence_dict(s, project)
    _push_undo(s, project.id, label)
    for op in ops:
        clip = s.get(FilmTimelineClip, op.get("id"))
        if clip is None or clip.project_id != project.id:
            raise SequenceError(f"Clip {op.get('id')} not found.")
        _apply_clip_patch(s, project, clip, {k: v for k, v in op.items() if k in CLIP_FIELDS})
    s.flush()
    _check_overlaps(s, project.id)
    return sequence_dict(s, project)


def split_clip(s: Session, project: FilmProject, clip: FilmTimelineClip, at_s: float) -> dict:
    track = s.get(FilmTimelineTrack, clip.track_id)
    _track_guard(track)
    at = float(at_s)
    if not (clip.start_s + MIN_CLIP_S <= at <= clip.start_s + clip.duration_s - MIN_CLIP_S):
        raise SequenceError("Split point must fall inside the clip.")
    _push_undo(s, project.id, "split clip")
    left_dur = at - clip.start_s
    right = FilmTimelineClip(
        project_id=project.id, track_id=clip.track_id, source_kind=clip.source_kind,
        take_id=clip.take_id, footage_id=clip.footage_id, audio_track_id=clip.audio_track_id,
        shot_id=clip.shot_id, label=clip.label, start_s=_round(at),
        duration_s=_round(clip.start_s + clip.duration_s - at),
        trim_start_s=_round(clip.trim_start_s + left_dur * clip.speed), speed=clip.speed,
        gain_db=clip.gain_db, muted=clip.muted, fade_in_s=0.0, fade_out_s=clip.fade_out_s,
        effects=dict(clip.effects or {}), transition_after=clip.transition_after,
        data=dict(clip.data or {}))
    clip.duration_s = _round(left_dur)
    clip.fade_out_s = 0.0
    clip.transition_after = None
    s.add(right)
    s.flush()
    _check_overlaps(s, project.id)
    return sequence_dict(s, project)


def delete_clips(s: Session, project: FilmProject, ids: list[int], ripple: bool = False) -> dict:
    clips = [c for c in clips_of(s, project.id) if c.id in set(ids)]
    if not clips:
        raise SequenceError("No matching clips.")
    for c in clips:
        _track_guard(s.get(FilmTimelineTrack, c.track_id))
    _push_undo(s, project.id, "ripple delete" if ripple else "delete clips")
    # process right-to-left so earlier shifts don't move later removal spans
    for c in sorted(clips, key=lambda c: -c.start_s):
        end = c.start_s + c.duration_s
        dur = c.duration_s
        s.delete(c)
        s.flush()
        if ripple:
            for other in clips_of(s, project.id):
                tr = s.get(FilmTimelineTrack, other.track_id)
                if tr.locked:
                    continue
                if other.start_s >= end - EPS:
                    other.start_s = _round(max(0.0, other.start_s - dur))
    s.flush()
    _check_overlaps(s, project.id)
    return sequence_dict(s, project)


def ripple_insert(s: Session, project: FilmProject, at_s: float, gap_s: float) -> dict:
    if gap_s <= 0:
        raise SequenceError("Gap must be positive.")
    _push_undo(s, project.id, "insert gap")
    for c in clips_of(s, project.id):
        tr = s.get(FilmTimelineTrack, c.track_id)
        if tr.locked:
            continue
        if c.start_s >= float(at_s) - EPS:
            c.start_s = _round(c.start_s + float(gap_s))
    s.flush()
    _check_overlaps(s, project.id)
    return sequence_dict(s, project)


def replace_take(s: Session, project: FilmProject, clip: FilmTimelineClip, take: FilmTake) -> dict:
    """Point a clip at a different take (review queue / storyboard swap).
    Trim resets; the clip keeps its position and duration."""
    if clip.source_kind != "take":
        raise SequenceError("Only take clips can swap takes.")
    _track_guard(s.get(FilmTimelineTrack, clip.track_id))
    _push_undo(s, project.id, "replace take")
    clip.take_id = take.id
    clip.shot_id = clip.shot_id or take.shot_id
    clip.trim_start_s = 0.0
    if take.duration_s:
        clip.duration_s = _round(min(clip.duration_s, take.duration_s)) if clip.data.get("built") is not True \
            else clip.duration_s
    s.flush()
    return sequence_dict(s, project)


# ---------------------------------------------------------------- markers ---
def add_marker(s: Session, project: FilmProject, t_s: float, label: str = "",
               color: str = "amber", note: str | None = None) -> dict:
    _push_undo(s, project.id, "add marker")
    s.add(FilmMarker(project_id=project.id, t_s=_round(max(0.0, t_s)), label=label,
                     color=color, note=note))
    s.flush()
    return sequence_dict(s, project)


def patch_marker(s: Session, project: FilmProject, marker: FilmMarker, **fields) -> dict:
    _push_undo(s, project.id, "edit marker")
    for k in ("t_s", "label", "color", "note"):
        if k in fields and fields[k] is not None:
            setattr(marker, k, _round(fields[k]) if k == "t_s" else fields[k])
    s.flush()
    return sequence_dict(s, project)


def delete_marker(s: Session, project: FilmProject, marker: FilmMarker) -> dict:
    _push_undo(s, project.id, "delete marker")
    s.delete(marker)
    s.flush()
    return sequence_dict(s, project)


# ---------------------------------------------------------------- flatten ---
def _source_path(s: Session, c: FilmTimelineClip) -> tuple[str | None, str | None]:
    """(DATA_DIR-relative media path, media kind) for a clip's source."""
    if c.source_kind == "take" and c.take_id:
        t = s.get(FilmTake, c.take_id)
        if t is not None and t.media_path:
            return t.media_path, t.kind
    elif c.source_kind == "footage" and c.footage_id:
        f = s.get(FilmClip, c.footage_id)
        if f is not None and f.path:
            return f.path, f.media_type
    elif c.source_kind == "audio" and c.audio_track_id:
        a = s.get(FilmAudioTrack, c.audio_track_id)
        if a is not None and a.path:
            return a.path, "audio"
    return None, None


def flatten(s: Session, project: FilmProject) -> dict:
    """Resolve the multi-track sequence into exactly what renders: a single
    ordered list of video segments (topmost unmuted track wins; empty space
    is black) plus the audio items to mix. Preview and export BOTH consume
    this, so they can never disagree. Positions are literal — a segment at
    [start, start+duration) renders there, full stop."""
    tracks = tracks_of(s, project.id)
    vid_tracks = [t for t in tracks if t.kind == "video"]
    solo_v = [t for t in vid_tracks if t.solo]
    audible_v = solo_v or [t for t in vid_tracks if not t.muted]
    # highest position renders on top (V2 covers V1)
    layer = {t.id: t.position for t in audible_v}
    all_clips = clips_of(s, project.id)
    vclips = [c for c in all_clips if c.track_id in layer]
    runtime = max((c.start_s + c.duration_s for c in all_clips), default=0.0)
    bounds = sorted({0.0} | {c.start_s for c in vclips} | {_round(c.start_s + c.duration_s) for c in vclips}
                    | ({runtime} if runtime else set()))
    segments: list[dict] = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a < EPS:
            continue
        cover = [c for c in vclips if c.start_s <= a + EPS and c.start_s + c.duration_s >= b - EPS]
        if not cover:
            segments.append({"type": "gap", "start_s": _round(a), "duration_s": _round(b - a)})
            continue
        top = max(cover, key=lambda c: (layer[c.track_id], c.id))
        offset = a - top.start_s
        clip_end = top.start_s + top.duration_s
        path, kind = _source_path(s, top)
        segments.append({
            "type": "clip", "clip_id": top.id, "shot_id": top.shot_id, "take_id": top.take_id,
            "label": top.label, "start_s": _round(a), "duration_s": _round(b - a),
            "path": path, "media_kind": kind, "missing": path is None,
            "trim_start_s": _round(top.trim_start_s + offset * top.speed), "speed": top.speed,
            "gain_db": top.gain_db, "audio_muted": top.muted,
            # fades belong to the clip's own edges — only the visible edge keeps one
            "fade_in_s": top.fade_in_s if abs(a - top.start_s) < EPS else 0.0,
            "fade_out_s": top.fade_out_s if abs(b - clip_end) < EPS else 0.0,
            "effects": top.effects or {},
            "join_after": (top.transition_after if abs(b - clip_end) < EPS else None)})
    # merge segments that are the same clip playing continuously (a lower-track
    # clip ending underneath creates a boundary that changes nothing visible)
    merged: list[dict] = []
    for seg in segments:
        prev = merged[-1] if merged else None
        if (prev and seg["type"] == "clip" and prev.get("type") == "clip"
                and prev.get("clip_id") == seg["clip_id"]
                and abs(prev["start_s"] + prev["duration_s"] - seg["start_s"]) < EPS):
            prev["duration_s"] = _round(prev["duration_s"] + seg["duration_s"])
            prev["fade_out_s"] = seg["fade_out_s"]
            prev["join_after"] = seg["join_after"]
        elif (prev and seg["type"] == "gap" and prev.get("type") == "gap"
                and abs(prev["start_s"] + prev["duration_s"] - seg["start_s"]) < EPS):
            prev["duration_s"] = _round(prev["duration_s"] + seg["duration_s"])
        else:
            merged.append(dict(seg))
    # a dissolve/wipe only makes sense straight into the next clip
    for i, seg in enumerate(merged):
        nxt = merged[i + 1] if i + 1 < len(merged) else None
        if seg.get("join_after") and (nxt is None or nxt["type"] != "clip"):
            j = seg["join_after"]
            seg["join_after"] = j if (j or {}).get("kind") in ("fade_black", "fade_white") else None
    # audio items: clips on audible audio tracks
    aud_tracks = [t for t in tracks if t.kind == "audio"]
    solo_a = [t for t in aud_tracks if t.solo]
    audible_a = {t.id for t in (solo_a or [t for t in aud_tracks if not t.muted])}
    audio: list[dict] = []
    for c in all_clips:
        if c.track_id not in audible_a or c.muted:
            continue
        path, _kind = _source_path(s, c)
        if path is None:
            continue
        loop = bool((c.data or {}).get("loop"))
        audio.append({"clip_id": c.id, "path": path, "start_s": c.start_s,
                      "trim_start_s": c.trim_start_s,
                      "trim_end_s": None if loop else _round(c.trim_start_s + c.duration_s * c.speed),
                      "speed": c.speed, "gain_db": c.gain_db, "loop": loop,
                      "fade_in_s": c.fade_in_s, "fade_out_s": c.fade_out_s,
                      "end_s": _round(c.start_s + c.duration_s), "label": c.label})
    settings = proj_svc.merge_settings(project.settings, None)
    return {"mode": "sequence", "segments": merged, "audio": audio,
            "runtime_s": _round(runtime), "fps": int(settings.get("fps") or 24),
            "aspect_ratio": settings.get("aspect_ratio")}


def preview_manifest(s: Session, project: FilmProject) -> dict:
    """The flattened render plan with URLs — what the editor's player runs."""
    fl = flatten(s, project)
    for seg in fl["segments"]:
        if seg.get("path"):
            seg["media_url"] = _media_url(seg["path"])
    for a in fl["audio"]:
        a["media_url"] = _media_url(a["path"])
    caption_clips = []
    cap_tracks = {t.id for t in tracks_of(s, project.id) if t.kind == "caption" and not t.muted}
    for c in clips_of(s, project.id):
        if c.track_id in cap_tracks:
            caption_clips.append({"clip_id": c.id, "start_s": c.start_s,
                                  "end_s": _round(c.start_s + c.duration_s),
                                  "text": (c.data or {}).get("text") or "",
                                  "style": (c.data or {}).get("style") or {}})
    fl["captions"] = caption_clips
    return fl


def qc(s: Session, project: FilmProject) -> list[dict]:
    """Sequence-specific QC rows in the qa.check_project shape."""
    checks: list[dict] = []
    if not exists(s, project.id):
        return checks
    fl = flatten(s, project)
    missing = [seg for seg in fl["segments"] if seg["type"] == "clip" and seg["missing"]]
    if missing:
        labels = ", ".join(str(seg.get("label") or seg["clip_id"]) for seg in missing[:6])
        checks.append({"key": "sequence_media", "status": "FAIL", "heuristic": False,
                       "message": f"{len(missing)} timeline clip(s) have no media yet ({labels}) — "
                                  "generate/import takes or remove the clips.",
                       "clips": [seg["clip_id"] for seg in missing]})
    else:
        checks.append({"key": "sequence_media", "status": "PASS", "heuristic": False,
                       "message": "Every timeline clip has media."})
    if not [seg for seg in fl["segments"] if seg["type"] == "clip"]:
        checks.append({"key": "sequence_empty", "status": "FAIL", "heuristic": False,
                       "message": "The sequence has no visible video clips."})
    gap_total = sum(seg["duration_s"] for seg in fl["segments"] if seg["type"] == "gap")
    if gap_total > max(2.0, 0.2 * (fl["runtime_s"] or 1)):
        checks.append({"key": "sequence_gaps", "status": "WARN", "heuristic": True,
                       "message": f"{gap_total:.1f}s of the sequence is empty (renders black)."})
    orphaned = [c.id for c in clips_of(s, project.id)
                if c.source_kind == "audio" and c.audio_track_id
                and s.get(FilmAudioTrack, c.audio_track_id) is None]
    if orphaned:
        checks.append({"key": "sequence_audio", "status": "WARN", "heuristic": False,
                       "message": f"{len(orphaned)} audio clip(s) lost their source track.",
                       "clips": orphaned})
    return checks


# -------------------------------------------------------------- serialise ---
def _media_url(rel: str | None) -> str | None:
    if not rel:
        return None
    if rel.startswith("film/"):
        return storage.url_for(rel)
    return "/" + rel


def clip_dict(s: Session, c: FilmTimelineClip) -> dict:
    media_url = thumb_url = None
    media_kind = None
    source_duration = None
    if c.source_kind == "take" and c.take_id:
        t = s.get(FilmTake, c.take_id)
        if t is not None:
            media_url, thumb_url = _media_url(t.media_path), _media_url(t.thumb_path)
            media_kind, source_duration = t.kind, t.duration_s
    elif c.source_kind == "footage" and c.footage_id:
        f = s.get(FilmClip, c.footage_id)
        if f is not None:
            media_url, thumb_url = _media_url(f.path), _media_url(f.thumb_path)
            media_kind, source_duration = f.media_type, f.duration_s
    elif c.source_kind == "audio" and c.audio_track_id:
        a = s.get(FilmAudioTrack, c.audio_track_id)
        if a is not None:
            media_url, media_kind, source_duration = _media_url(a.path), "audio", a.duration_s
    return {"id": c.id, "track_id": c.track_id, "source_kind": c.source_kind,
            "take_id": c.take_id, "footage_id": c.footage_id, "audio_track_id": c.audio_track_id,
            "shot_id": c.shot_id, "label": c.label, "start_s": c.start_s, "end_s": _round(c.start_s + c.duration_s),
            "duration_s": c.duration_s, "trim_start_s": c.trim_start_s, "speed": c.speed,
            "gain_db": c.gain_db, "muted": c.muted, "fade_in_s": c.fade_in_s, "fade_out_s": c.fade_out_s,
            "effects": c.effects or {}, "transition_after": c.transition_after, "data": c.data or {},
            "media_url": media_url, "thumb_url": thumb_url, "media_kind": media_kind,
            "source_duration_s": source_duration,
            "missing_media": c.source_kind in ("take", "footage") and media_url is None}


def sequence_dict(s: Session, project: FilmProject) -> dict:
    tracks = tracks_of(s, project.id)
    if not tracks:
        return {"project_id": project.id, "exists": False}
    clips = clips_of(s, project.id)
    by_track: dict[int, list[dict]] = {t.id: [] for t in tracks}
    runtime = 0.0
    for c in clips:
        d = clip_dict(s, c)
        by_track.setdefault(c.track_id, []).append(d)
        runtime = max(runtime, c.start_s + c.duration_s)
    settings = proj_svc.merge_settings(project.settings, None)
    undo_n = s.execute(select(FilmRevision.id).where(FilmRevision.project_id == project.id,
                                                     FilmRevision.stack == "undo")).all()
    redo_n = s.execute(select(FilmRevision.id).where(FilmRevision.project_id == project.id,
                                                     FilmRevision.stack == "redo")).all()
    return {"project_id": project.id, "exists": True,
            "runtime_s": _round(runtime), "runtime_tc": timeline.format_tc(runtime),
            "fps": int(settings.get("fps") or 24), "aspect_ratio": settings.get("aspect_ratio"),
            "tracks": [{"id": t.id, "kind": t.kind, "position": t.position, "label": t.label,
                        "muted": t.muted, "solo": t.solo, "locked": t.locked,
                        "clips": by_track.get(t.id, [])} for t in tracks],
            "markers": [{"id": m.id, "t_s": m.t_s, "label": m.label, "color": m.color, "note": m.note}
                        for m in markers_of(s, project.id)],
            "can_undo": len(undo_n) > 0, "can_redo": len(redo_n) > 0}
