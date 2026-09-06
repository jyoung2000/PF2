"""Timeline export (spec §23, U): conform every selected take to the
project's frame size/fps and duration, join them exactly as the timeline
reports (scene gaps as black, dissolves/wipes as overlaps, fades as
per-clip fades), mix the audio tracks, write SRT/VTT (and burn in when
asked), then run the post-render review. Runs as a checkpointed job;
conformed clips are reused on resume."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..pipeline import media
from . import audio as audio_svc
from . import events, gates, graphics
from . import jobs as job_svc
from . import projects as proj_svc
from . import qa, storage, subtitles as sub_svc
from . import sequence as seq_svc
from . import takes as take_svc
from . import timeline
from .models import FilmJob, FilmProject, FilmShot, FilmTake

XFADE = {"dissolve": "fade", "wipe": "wipeleft"}
EXPORT_HEIGHTS = {"720p": 720, "1080p": 1080}


class ExportError(ValueError):
    pass


def frame_size(aspect: str | None, height: int = 1080) -> tuple[int, int]:
    val = qa._aspect_value(aspect) or 16 / 9
    w = int(round(height * val / 2) * 2)
    return w, height


def start_export(s: Session, project: FilmProject, label: str | None = None, burn_in: bool | None = None,
                 include_audio: bool = True, quality: str = "1080p", force: bool = False,
                 actor: str = "user") -> FilmJob:
    if not force and not gates.is_approved(s, project, "qa"):
        report = qa.check_project(s, project)
        if report["verdict"] == "FAIL":
            raise ExportError("QA fails — fix the repair queue (or export with force to render anyway): "
                              + "; ".join(c["message"] for c in report["checks"] if c["status"] == "FAIL")[:400])
    job = job_svc.create(s, project.id, "export",
                         payload={"label": label, "burn_in": burn_in, "include_audio": include_audio,
                                  "quality": quality if quality in EXPORT_HEIGHTS else "1080p", "force": force},
                         stage="export")
    events.log(s, project.id, "Export queued", kind="generation", stage="export", actor=actor,
               entity=("job", job.id), data={"quality": quality, "burn_in": burn_in})
    return job


# ------------------------------------------------------------- planning ---
def plan(s: Session, project: FilmProject) -> dict:
    """Everything the render needs. When the project has an edited sequence
    (built in the editor) THAT is the render plan — otherwise the storyboard-
    derived timeline is, exactly as before."""
    if seq_svc.exists(s, project.id):
        fl = seq_svc.flatten(s, project)
        segments = []
        for seg in fl["segments"]:
            row = dict(seg)
            row["join_after"] = seg.get("join_after")
            segments.append(row)
        return {"mode": "sequence", "segments": segments, "audio": fl["audio"],
                "fps": fl["fps"], "aspect_ratio": fl["aspect_ratio"], "runtime_s": fl["runtime_s"]}
    tl = timeline.compute(s, project)
    settings = proj_svc.merge_settings(project.settings, None)
    segments: list[dict] = []
    for si, sc in enumerate(tl["scenes"]):
        shots = sc["shots"]
        for j, sh in enumerate(shots):
            shot = s.get(FilmShot, sh["id"])
            take = s.get(FilmTake, shot.selected_take_id) if shot and shot.selected_take_id else None
            segments.append({"type": "clip", "shot_id": sh["id"], "label": sh["label"], "take_id": take.id if take else None,
                             "duration_s": sh["duration_s"], "join_after": (sh["transition"] or {"kind": "cut"})
                             if j < len(shots) - 1 else None})
        last = si == len(tl["scenes"]) - 1
        if not last:
            gap = float(sc["gap_after_s"] or 0)
            tr = sc["transition"] or {"kind": "cut", "duration_s": 0.0}
            if gap > 0:
                # gap ⇒ black; the scene transition becomes a fade in/out around it
                segments[-1]["join_after"] = {"kind": "fade_black", "duration_s": tr.get("duration_s") or 0.0} \
                    if tr.get("kind") != "cut" else {"kind": "cut", "duration_s": 0.0}
                segments.append({"type": "gap", "duration_s": gap, "join_after": {"kind": "cut", "duration_s": 0.0}})
            else:
                segments[-1]["join_after"] = tr
    return {"mode": "storyboard", "timeline": tl, "segments": segments,
            "fps": int(settings.get("fps") or 24),
            "aspect_ratio": settings.get("aspect_ratio"), "runtime_s": tl["runtime_s"]}


def _fade_parts(seg_join_before: dict | None, seg_join_after: dict | None, duration: float) -> tuple[float, float, str]:
    """Per-clip fade in/out seconds for fade_black/fade_white joins (each
    side takes half of the transition), plus the fade colour."""
    fin = fout = 0.0
    color = "black"
    if seg_join_before and seg_join_before.get("kind") in ("fade_black", "fade_white"):
        fin = min(duration / 2, float(seg_join_before.get("duration_s") or 0) / 2)
        color = "white" if seg_join_before["kind"] == "fade_white" else "black"
    if seg_join_after and seg_join_after.get("kind") in ("fade_black", "fade_white"):
        fout = min(duration / 2, float(seg_join_after.get("duration_s") or 0) / 2)
        color = "white" if seg_join_after["kind"] == "fade_white" else "black"
    return fin, fout, color


def _effects_chain(e: dict, w: int, h: int) -> tuple[str, bool]:
    """(filter fragment applied to the fitted clip, needs_composite). The
    values arrive pre-clamped by sequence.sanitize_effects. Transform
    effects (scale/x/y/rotation/opacity) composite the clip onto a black
    canvas so position and partial opacity render exactly like the editor's
    CSS preview."""
    parts: list[str] = []
    crop = e.get("crop") or {}
    if crop:
        cl, ct = float(crop.get("l") or 0), float(crop.get("t") or 0)
        cr, cb = float(crop.get("r") or 0), float(crop.get("b") or 0)
        parts.append(f"crop=iw*{max(0.05, 1 - cl - cr):.4f}:ih*{max(0.05, 1 - ct - cb):.4f}:iw*{cl:.4f}:ih*{ct:.4f}")
    eq = []
    if e.get("brightness") is not None:
        eq.append(f"brightness={float(e['brightness']):.3f}")
    if e.get("contrast") is not None:
        eq.append(f"contrast={float(e['contrast']):.3f}")
    if e.get("saturation") is not None:
        eq.append(f"saturation={float(e['saturation']):.3f}")
    if eq:
        parts.append("eq=" + ":".join(eq))
    if e.get("blur"):
        parts.append(f"gblur=sigma={float(e['blur']):.2f}")
    scale = float(e.get("scale") or 1.0)
    needs_composite = (abs(scale - 1.0) > 1e-6 or abs(float(e.get("x") or 0)) > 1e-6
                       or abs(float(e.get("y") or 0)) > 1e-6 or abs(float(e.get("rotation") or 0)) > 1e-6
                       or float(e.get("opacity") if e.get("opacity") is not None else 1.0) < 1.0 - 1e-6)
    if needs_composite:
        sw, sh = int(round(w * scale / 2) * 2), int(round(h * scale / 2) * 2)
        parts.append(f"scale={max(2, sw)}:{max(2, sh)}:force_original_aspect_ratio=decrease")
        rot = float(e.get("rotation") or 0)
        if abs(rot) > 1e-6:
            parts.append(f"rotate={rot:.3f}*PI/180:c=black@0:ow=rotw({rot:.3f}*PI/180):oh=roth({rot:.3f}*PI/180)")
        op = float(e.get("opacity") if e.get("opacity") is not None else 1.0)
        parts.append("format=yuva420p")
        if op < 1.0 - 1e-6:
            parts.append(f"colorchannelmixer=aa={op:.3f}")
    return ",".join(parts), needs_composite


def conform_clip(src: Path, dest: Path, w: int, h: int, fps: int, duration: float, fade_in: float = 0.0,
                 fade_out: float = 0.0, fade_color: str = "black", is_image: bool = False,
                 src_start: float = 0.0, speed: float = 1.0, hold_extra: float = 0.0,
                 effects: dict | None = None) -> Path:
    """Scale+pad to the frame, conform fps, force the exact duration
    (trim, or hold the last frame), apply per-clip effects and fades; video
    only (audio is mixed separately). `src_start`/`speed` implement clip
    trim + retime; `hold_extra` appends that many held-last-frame seconds
    AFTER the fades (used by in-place dissolves, which never shift timing)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if is_image:
        graphics.still_video(src, dest.with_suffix(".still.mp4"), duration, None, fps, size=(w, h))
        src = dest.with_suffix(".still.mp4")
        src_start, speed = 0.0, 1.0
    total = duration + max(0.0, hold_extra)
    fx, composite = _effects_chain(effects or {}, w, h)
    pre = ""
    if speed and abs(speed - 1.0) > 1e-6:
        pre += f"setpts=(PTS-STARTPTS)/{speed:.4f},"
    tail = (f"fps={fps},tpad=stop_mode=clone:stop_duration={total + 1:.3f},"
            f"trim=duration={total:.3f},setpts=PTS-STARTPTS")
    if fade_in > 0:
        tail += f",fade=t=in:st=0:d={fade_in:.3f}:color={fade_color}"
    if fade_out > 0:
        tail += f",fade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}:color={fade_color}"
    tail += ",format=yuv420p"
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if src_start > 1e-6:
        cmd += ["-ss", f"{src_start:.3f}"]
    if composite:
        # clip is transformed then centred (+x/y offsets) on a black canvas
        e = effects or {}
        ox = f"(W-w)/2+{float(e.get('x') or 0):.4f}*W"
        oy = f"(H-h)/2+{float(e.get('y') or 0):.4f}*H"
        graph = (f"color=c=black:s={w}x{h}:r={fps}:d={total + 1:.3f}[bg];"
                 f"[0:v]{pre}tpad=stop_mode=clone:stop_duration={total + 1:.3f},{fx}[fg];"
                 f"[bg][fg]overlay={ox}:{oy}:shortest=0,{tail}[out]")
        cmd += ["-i", str(src), "-filter_complex", graph, "-map", "[out]"]
    else:
        vf = pre + (fx + "," if fx else "")
        vf += (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
               f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,{tail}")
        cmd += ["-i", str(src), "-vf", vf]
    cmd += ["-an", "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-movflags", "+faststart", str(dest)]
    media._run(cmd, timeout=1800)
    if is_image:
        src.unlink(missing_ok=True)
    return dest


def black_clip(dest: Path, w: int, h: int, fps: int, duration: float) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    media._run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}:d={max(0.05, duration):.3f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(dest)], timeout=600)
    return dest


def join_video(clips: list[dict], dest: Path, fps: int) -> Path:
    """clips: [{path, duration_s, join_after, extended_s?}] → one video.
    Cut/fade joins concat inside a group; dissolve/wipe joins xfade between
    groups. A clip carrying `extended_s` was rendered that much longer
    (held last frame) so the xfade consumes the extension instead of the
    timeline — total duration stays exact (sequence exports)."""
    groups: list[list[dict]] = [[]]
    joins: list[dict] = []
    for c in clips:
        groups[-1].append(c)
        j = c.get("join_after") or {"kind": "cut"}
        if j.get("kind") in XFADE and float(j.get("duration_s") or 0) > 0:
            joins.append({**j, "_ext": float(c.get("extended_s") or 0.0)})
            groups.append([])
    if not groups[-1]:
        groups.pop()
    inputs: list[str] = []
    filters: list[str] = []
    idx = 0
    labels = []
    for gi, group in enumerate(groups):
        names = []
        for c in group:
            inputs += ["-i", str(c["path"])]
            # identical timebase/fps on every input so concat and xfade agree
            filters.append(f"[{idx}:v]fps={fps},settb=AVTB,setpts=PTS-STARTPTS[n{idx}]")
            names.append(f"[n{idx}]")
            idx += 1
        if len(names) == 1:
            filters.append(f"{names[0]}null[g{gi}]")
        else:
            filters.append("".join(names) + f"concat=n={len(names)}:v=1:a=0,settb=AVTB[g{gi}]")
        labels.append((f"[g{gi}]", sum(float(c["duration_s"]) for c in group)))
    cur, cur_len = labels[0]
    for gi in range(1, len(labels)):
        j = joins[gi - 1]
        d = float(j.get("duration_s") or 0)
        ext = min(float(j.get("_ext") or 0.0), d)
        nxt, nxt_len = labels[gi]
        out = f"[x{gi}]"
        offset = max(0.0, cur_len - d + ext)
        filters.append(f"{cur}{nxt}xfade=transition={XFADE[j['kind']]}:duration={d:.3f}:offset={offset:.3f}{out}")
        cur, cur_len = out, offset + nxt_len
    dest.parent.mkdir(parents=True, exist_ok=True)
    media._run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters), "-map", cur,
                "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(dest)], timeout=3600)
    return dest


def _audio_graph(tracks: list[dict], clip_audio: list[dict], runtime: float) -> tuple[list[str], str]:
    """Inputs + filter for the mix: every track/clip audio delayed to its
    start, trimmed, gained, faded; a silent bed keeps the length exact."""
    inputs = ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={runtime:.3f}"]
    chains = ["[0:a]atrim=duration=%.3f[bed]" % runtime]
    labels = ["[bed]"]
    n = 1
    for t in tracks + clip_audio:
        inputs += ["-i", str(t["path"])]
        start = max(0.0, float(t.get("start_s") or 0))
        trim_start = float(t.get("trim_start_s") or 0)
        trim_end = t.get("trim_end_s")
        f = f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=start={trim_start:.3f}"
        if trim_end is not None:
            f += f":end={float(trim_end):.3f}"
        f += ",asetpts=PTS-STARTPTS"
        sp = float(t.get("speed") or 1.0)
        if abs(sp - 1.0) > 1e-6:
            f += _atempo(sp)
        if t.get("loop"):
            f += f",aloop=loop=-1:size=2e9,atrim=duration={max(0.1, runtime - start):.3f}"
        gain = float(t.get("gain_db") or 0)
        if gain:
            f += f",volume={gain:.2f}dB"
        if float(t.get("fade_in_s") or 0) > 0:
            f += f",afade=t=in:st=0:d={float(t['fade_in_s']):.3f}"
        if float(t.get("fade_out_s") or 0) > 0 and t.get("end_s") is not None:
            length = float(t["end_s"]) - start
            f += f",afade=t=out:st={max(0.0, length - float(t['fade_out_s'])):.3f}:d={float(t['fade_out_s']):.3f}"
        f += f",adelay={int(start * 1000)}|{int(start * 1000)}[a{n}]"
        chains.append(f)
        labels.append(f"[a{n}]")
        n += 1
    chains.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0,atrim=duration={runtime:.3f}[aout]")
    return inputs, ";".join(chains)


def _atempo(speed: float) -> str:
    """atempo chain for any retime factor (each stage stays in [0.5, 2])."""
    parts = []
    sp = max(0.05, min(20.0, speed))
    while sp > 2.0:
        parts.append("atempo=2.0")
        sp /= 2.0
    while sp < 0.5:
        parts.append("atempo=0.5")
        sp *= 2.0
    parts.append(f"atempo={sp:.4f}")
    return "," + ",".join(parts)


def _srt_ts(sec: float) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _cues_to_srt(cues: list[dict]) -> str:
    out = []
    for i, c in enumerate(sorted(cues, key=lambda x: x["start_s"]), start=1):
        out.append(f"{i}\n{_srt_ts(c['start_s'])} --> {_srt_ts(c['end_s'])}\n{(c.get('text') or '').strip()}\n")
    return "\n".join(out)


def _subtitle_style(style: dict) -> str:
    color = (style.get("color") or "#FFFFFF").lstrip("#")
    if len(color) == 6:
        bgr = color[4:6] + color[2:4] + color[0:2]
    else:
        bgr = "FFFFFF"
    align = 2 if (style.get("position") or "bottom") == "bottom" else 8
    return (f"FontName={style.get('font') or 'DejaVu Sans'},FontSize={int(style.get('font_size') or 28)},"
            f"PrimaryColour=&H00{bgr},Outline={int(style.get('outline') or 2)},Alignment={align}")


def run_export(job_id: int) -> dict:
    with session_scope() as s:
        j = s.get(FilmJob, job_id)
        payload = dict(j.payload or {})
        project = s.get(FilmProject, j.project_id)
        if project is None:
            raise ExportError("project no longer exists")
        pl = plan(s, project)
        w, h = frame_size(pl["aspect_ratio"], EXPORT_HEIGHTS.get(payload.get("quality") or "1080p", 1080))
        fps = pl["fps"]
        work_rel = f"film/projects/{project.id}/exports/work{job_id}"
        work = storage.resolve(work_rel + "/x").parent
        work.mkdir(parents=True, exist_ok=True)
        segments = pl["segments"]
        clip_audio: list[dict] = []
        clips: list[dict] = []
        total = len(segments)
        job_svc.set_progress(job_id, total=total + 2)
        is_seq = pl.get("mode") == "sequence"
        prev_join = None
        t_cursor = 0.0
        done = set(job_svc.done_items(job_id))

        def _seg_src(seg):
            if is_seq:
                return take_svc.abs_path(seg.get("path")), (seg.get("media_kind") == "image")
            take = s.get(FilmTake, seg["take_id"]) if seg.get("take_id") else None
            src = take_svc.abs_path(take.media_path) if take else None
            return src, bool(take and take.kind == "image")

        def _seg_audio(seg, src, dur, at_s):
            if src is None or not payload.get("include_audio", True):
                return
            if is_seq and seg.get("audio_muted"):
                return
            if not (qa.probe(src) or {}).get("audio"):
                return
            sp = float(seg.get("speed") or 1.0) if is_seq else 1.0
            trim0 = float(seg.get("trim_start_s") or 0.0) if is_seq else 0.0
            clip_audio.append({"path": src, "start_s": at_s, "trim_start_s": trim0,
                               "trim_end_s": trim0 + dur * sp, "speed": sp,
                               "gain_db": float(seg.get("gain_db") or 0.0) if is_seq else 0.0,
                               "fade_in_s": float(seg.get("fade_in_s") or 0.0) if is_seq else 0.0,
                               "fade_out_s": float(seg.get("fade_out_s") or 0.0) if is_seq else 0.0,
                               "end_s": at_s + dur})

        for i, seg in enumerate(segments):
            job_svc.check_stop(job_id)
            out = work / f"seg{i:03d}.mp4"
            dur = float(seg["duration_s"])
            fin, fout, color = _fade_parts(prev_join, seg.get("join_after"), dur)
            if is_seq and seg["type"] == "clip":
                fin = max(fin, float(seg.get("fade_in_s") or 0.0))
                fout = max(fout, float(seg.get("fade_out_s") or 0.0))
            j_after = seg.get("join_after") or {}
            hold = float(j_after.get("duration_s") or 0) \
                if is_seq and j_after.get("kind") in XFADE else 0.0
            key = f"seg{i}"
            if key not in done or not out.exists():
                job_svc.set_progress(job_id, current=f"conforming {seg.get('label') or 'gap'}")
                if seg["type"] == "gap":
                    black_clip(out, w, h, fps, dur + hold)
                else:
                    src, is_image = _seg_src(seg)
                    if src is None:
                        if not payload.get("force"):
                            raise ExportError(f"{'Clip' if is_seq else 'Shot'} {seg.get('label') or '?'} has "
                                              "no media — generate or import a take first.")
                        black_clip(out, w, h, fps, dur + hold)
                    else:
                        is_image = is_image or src.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                        conform_clip(src, out, w, h, fps, dur, fin, fout, color, is_image=is_image,
                                     src_start=float(seg.get("trim_start_s") or 0.0) if is_seq else 0.0,
                                     speed=float(seg.get("speed") or 1.0) if is_seq else 1.0,
                                     hold_extra=hold,
                                     effects=(seg.get("effects") or None) if is_seq else None)
                        _seg_audio(seg, src, dur, t_cursor)
                job_svc.checkpoint(job_id, key, current=seg.get("label"))
            elif seg["type"] == "clip":
                src, _img = _seg_src(seg)
                _seg_audio(seg, src, dur, t_cursor)
            clips.append({"path": out, "duration_s": dur, "join_after": seg.get("join_after"),
                          "extended_s": hold})
            overlap = 0.0 if is_seq else (float(j_after.get("duration_s") or 0)
                                          if j_after.get("kind") in XFADE else 0.0)
            t_cursor += dur - overlap
            prev_join = seg.get("join_after")
        job_svc.check_stop(job_id)
        job_svc.set_progress(job_id, current="joining")
        video = work / "video.mp4"
        join_video(clips, video, fps)
        runtime = float(pl["runtime_s"]) or (qa.probe(video) or {}).get("duration") or 1.0
        tracks = []
        if payload.get("include_audio", True):
            if is_seq:
                for a in pl["audio"]:
                    p = take_svc.abs_path(a.get("path"))
                    if p is not None:
                        tracks.append({**a, "path": p})
            else:
                for t in audio_svc.mix_plan(s, project)["tracks"]:
                    p = take_svc.abs_path(next((x.path for x in audio_svc.tracks_of(s, project.id) if x.id == t["id"]), None))
                    if p is not None:
                        tracks.append({**t, "path": p})
        label = (payload.get("label") or datetime.now(timezone.utc).strftime("export-%Y%m%d-%H%M%S"))
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label)[:60] or "export"
        final_rel = storage.project_rel(project.id, "exports", f"{safe}.mp4")
        final = storage.resolve(final_rel)
        st = sub_svc.get(s, project.id)
        burn = payload.get("burn_in") if payload.get("burn_in") is not None else bool(st and st.burn_in)
        srt_rel = vtt_rel = None
        vf = None
        if st and st.cues:
            sub_svc.resync(s, project)
            srt_rel = storage.project_rel(project.id, "exports", f"{safe}.srt")
            vtt_rel = storage.project_rel(project.id, "exports", f"{safe}.vtt")
            storage.write(srt_rel, sub_svc.to_srt(st).encode("utf-8"))
            storage.write(vtt_rel, sub_svc.to_vtt(st).encode("utf-8"))
            if burn:
                srt_path = str(storage.resolve(srt_rel)).replace("\\", "/").replace(":", "\\:")
                vf = f"subtitles='{srt_path}':force_style='{_subtitle_style(st.style or {})}'"
        if is_seq:
            # caption-track clips are on-video text: always burned, exactly as
            # the editor previews them (one style per export; the first
            # caption clip's style wins over the project subtitle style)
            caps = [c for c in seq_svc.preview_manifest(s, project)["captions"] if (c.get("text") or "").strip()]
            if caps:
                cap_rel = storage.project_rel(project.id, "exports", f"{safe}.captions.srt")
                storage.write(cap_rel, _cues_to_srt(caps).encode("utf-8"))
                style = dict((st.style if st else None) or {})
                style.update(caps[0].get("style") or {})
                cap_path = str(storage.resolve(cap_rel)).replace("\\", "/").replace(":", "\\:")
                cap_vf = f"subtitles='{cap_path}':force_style='{_subtitle_style(style)}'"
                vf = f"{vf},{cap_vf}" if vf else cap_vf
        job_svc.set_progress(job_id, current="mixing + encoding")
        inputs, agraph = _audio_graph(tracks, clip_audio, runtime)
        # the audio graph numbers its inputs from 0; the video is input 0 here, so shift by one
        shifted = _shift_audio_inputs(agraph)
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video), *inputs, "-filter_complex", shifted,
               "-map", "0:v", "-map", "[aout]", "-c:v", "libx264" if vf else "copy"]
        if vf:
            cmd += ["-vf", vf, "-preset", "veryfast", "-crf", "20"]
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final)]
        final.parent.mkdir(parents=True, exist_ok=True)
        media._run(cmd, timeout=3600)
        sources = _sources(s, project, pl, tracks, st)
        src_rel = storage.project_rel(project.id, "exports", f"{safe}.sources.json")
        storage.write(src_rel, json.dumps(sources, indent=2, default=str).encode("utf-8"))
        review = qa.review_export(final, {"aspect_ratio": pl["aspect_ratio"], "fps": fps, "runtime_s": runtime})
        job_svc.checkpoint(job_id, "final", current=None)
        shutil.rmtree(work, ignore_errors=True)
        result = {"path": final_rel, "url": storage.url_for(final_rel), "srt_url": storage.url_for(srt_rel),
                  "vtt_url": storage.url_for(vtt_rel), "sources_url": storage.url_for(src_rel),
                  "runtime_s": runtime, "width": w, "height": h, "fps": fps, "review": review,
                  "samples": [storage.url_for(storage.project_rel(project.id, "exports", n)) for n in review.get("samples", [])],
                  "burn_in": bool(vf), "tracks": len(tracks), "clip_audio": len(clip_audio)}
        events.log(s, project.id, f"Export rendered: {safe}.mp4 ({runtime:.1f}s, QA {review['verdict']})",
                   kind="generation", stage="export", actor="system", entity=("job", job_id),
                   data={"path": final_rel, "verdict": review["verdict"]})
        return result


def _shift_audio_inputs(graph: str) -> str:
    """The audio graph numbers its inputs from 0; in the final command the
    conformed video is input 0, so every [N:a] becomes [N+1:a]."""
    import re
    return re.sub(r"\[(\d+):a\]", lambda m: f"[{int(m.group(1)) + 1}:a]", graph)


def _sources(s: Session, project: FilmProject, pl: dict, tracks: list[dict], st) -> dict:
    shots = []
    for seg in pl["segments"]:
        if seg["type"] != "clip":
            continue
        take = s.get(FilmTake, seg["take_id"]) if seg.get("take_id") else None
        shots.append({"shot_id": seg["shot_id"], "label": seg["label"], "duration_s": seg["duration_s"],
                      "take": ({"id": take.id, "kind": take.kind, "provider": take.provider,
                                "model_family": take.model_family, "mode": take.mode, "prompt": take.prompt,
                                "negative": take.negative, "assets": (take.context or {}).get("assets"),
                                "decision": take.decision, "cost_estimate": take.cost_estimate,
                                "cost_actual": take.cost_actual, "provenance": (take.context or {}).get("provenance"),
                                "media_path": take.media_path} if take else None)})
    return {"project": {"id": project.id, "title": project.title, "settings": project.settings, "plan": project.plan},
            "exported_at": datetime.now(timezone.utc).isoformat(), "runtime_s": pl["runtime_s"], "shots": shots,
            "audio_tracks": [{k: v for k, v in t.items() if k != "path"} for t in tracks],
            "subtitles": sub_svc.subtitle_dict(st) if st else None}


job_svc.register("export", run_export)


def exports_of(s: Session, project: FilmProject) -> list[dict]:
    rows = s.execute(select(FilmJob).where(FilmJob.project_id == project.id, FilmJob.kind == "export")
                     .order_by(FilmJob.id.desc()).limit(20)).scalars()
    from . import board
    return [board.job_dict(j) for j in rows]
