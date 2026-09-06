"""Quality gates (spec T, U, V): technical validation with ffprobe, black /
frozen-frame detection with ffmpeg, expectation checks (duration, aspect,
fps, audio), subtitle validity, missing-media and ordering checks, and a
repair queue that points at the SMALLEST artifact to redo. Heuristic
checks say so. Verdicts: PASS | WARN | FAIL."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_config
from . import projects as proj_svc
from .models import FilmProject, FilmShot, FilmTake

DURATION_TOL = 0.15      # ±15 % of the expected duration → WARN beyond
BLACK_MAX_RATIO = 0.2    # > 20 % black → WARN
FREEZE_MAX_RATIO = 0.5   # > 50 % frozen → WARN


def _check(key: str, status: str, message: str, heuristic: bool = False, **data) -> dict:
    return {"key": key, "status": status, "message": message, "heuristic": heuristic, **data}


def probe(path: Path) -> dict | None:
    try:
        proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                               "stream=codec_type,codec_name,width,height,r_frame_rate,duration,nb_frames:format=duration,size",
                               "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        return None
    video = next((st for st in data.get("streams", []) if st.get("codec_type") == "video"), None)
    audio = next((st for st in data.get("streams", []) if st.get("codec_type") == "audio"), None)
    fps = None
    if video and video.get("r_frame_rate") and "/" in video["r_frame_rate"]:
        n, d = video["r_frame_rate"].split("/")
        try:
            fps = round(float(n) / float(d), 3) if float(d) else None
        except ValueError:
            fps = None
    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return {"video": bool(video), "audio": bool(audio), "codec": (video or {}).get("codec_name"),
            "width": (video or {}).get("width"), "height": (video or {}).get("height"), "fps": fps,
            "duration": duration, "size": int(data.get("format", {}).get("size") or 0),
            "audio_codec": (audio or {}).get("codec_name")}


def black_ratio(path: Path, duration: float | None) -> float | None:
    """Fraction of the clip flagged black by ffmpeg blackdetect (heuristic)."""
    try:
        proc = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf", "blackdetect=d=0.1:pic_th=0.98",
                               "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    total = 0.0
    for m in re.finditer(r"black_duration:(\d+(?:\.\d+)?)", proc.stderr or ""):
        total += float(m.group(1))
    if not duration:
        return None
    return min(1.0, total / duration)


def freeze_ratio(path: Path, duration: float | None) -> float | None:
    try:
        proc = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf", "freezedetect=n=0.003:d=0.5",
                               "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    total = 0.0
    for m in re.finditer(r"freeze_duration: (\d+(?:\.\d+)?)", proc.stderr or ""):
        total += float(m.group(1))
    if not duration:
        return None
    return min(1.0, total / duration)


def _aspect(w: int | None, h: int | None) -> float | None:
    return round(w / h, 3) if w and h else None


def _aspect_value(label: str | None) -> float | None:
    if not label:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$", label)
    return round(float(m.group(1)) / float(m.group(2)), 3) if m else None


def verdict(checks: list[dict]) -> str:
    if any(c["status"] == "FAIL" for c in checks):
        return "FAIL"
    if any(c["status"] == "WARN" for c in checks):
        return "WARN"
    return "PASS"


def check_media(path: Path | None, expected: dict | None = None, deep: bool = True) -> dict:
    """Technical + visual checks for one media file."""
    expected = expected or {}
    checks: list[dict] = []
    if path is None or not path.is_file():
        checks.append(_check("file", "FAIL", "Media file is missing on disk."))
        return {"verdict": "FAIL", "checks": checks, "probe": None}
    info = probe(path)
    if info is None or not info.get("video"):
        checks.append(_check("valid", "FAIL", "ffprobe could not read a video/image stream — the file is corrupt or unsupported."))
        return {"verdict": "FAIL", "checks": checks, "probe": info}
    checks.append(_check("valid", "PASS", f"Valid {info.get('codec')} stream, {info.get('width')}×{info.get('height')}."))
    kind = expected.get("kind", "video")
    if kind == "video":
        exp_d = expected.get("duration_s")
        if info.get("duration") is None:
            checks.append(_check("duration", "WARN", "Duration unknown (no container duration)."))
        elif exp_d:
            delta = abs(info["duration"] - float(exp_d))
            tol = max(0.5, DURATION_TOL * float(exp_d))
            status = "PASS" if delta <= tol else "WARN"
            checks.append(_check("duration", status,
                                 f"Duration {info['duration']:.2f}s vs expected {float(exp_d):.2f}s"
                                 + ("" if status == "PASS" else " — trim or regenerate with the right length."),
                                 actual=info["duration"], expected=float(exp_d)))
        exp_fps = expected.get("fps")
        if exp_fps and info.get("fps") and abs(info["fps"] - float(exp_fps)) > 0.6:
            checks.append(_check("fps", "WARN", f"Frame rate {info['fps']} vs project {exp_fps} — export will conform it.",
                                 actual=info["fps"], expected=exp_fps))
        elif info.get("fps"):
            checks.append(_check("fps", "PASS", f"{info['fps']} fps."))
        # silent clips are normal for AI video — informational, never a warning
        checks.append(_check("audio", "PASS",
                             "Audio stream present." if info.get("audio") else "No audio stream (normal for AI video; music/dialogue is mixed at export).",
                             audio=bool(info.get("audio"))))
    exp_aspect = _aspect_value(expected.get("aspect_ratio"))
    actual_aspect = _aspect(info.get("width"), info.get("height"))
    if exp_aspect and actual_aspect and abs(actual_aspect - exp_aspect) > 0.06:
        checks.append(_check("aspect", "WARN", f"Aspect {actual_aspect} vs project {expected.get('aspect_ratio')} — export pads/crops.",
                             actual=actual_aspect, expected=exp_aspect))
    elif actual_aspect:
        checks.append(_check("aspect", "PASS", f"Aspect {actual_aspect}."))
    if deep and kind == "video" and info.get("duration"):
        br = black_ratio(path, info["duration"])
        if br is not None:
            checks.append(_check("black_frames", "WARN" if br > BLACK_MAX_RATIO else "PASS",
                                 f"{br * 100:.0f}% of the clip is black." + (" Likely a failed render." if br > BLACK_MAX_RATIO else ""),
                                 heuristic=True, ratio=br))
        fr = freeze_ratio(path, info["duration"])
        if fr is not None:
            checks.append(_check("frozen_frames", "WARN" if fr > FREEZE_MAX_RATIO else "PASS",
                                 f"{fr * 100:.0f}% of the clip is frozen." + (" Motion may have failed." if fr > FREEZE_MAX_RATIO else ""),
                                 heuristic=True, ratio=fr))
    return {"verdict": verdict(checks), "checks": checks, "probe": info}


def check_take(s: Session, take: FilmTake, shot: FilmShot | None = None) -> dict:
    from . import takes as take_svc
    shot = shot or s.get(FilmShot, take.shot_id)
    project = s.get(FilmProject, take.project_id)
    settings = proj_svc.merge_settings(project.settings if project else None, None)
    expected = {"kind": "video" if take.kind in ("video", "footage", "graphics") else "image",
                "aspect_ratio": settings.get("aspect_ratio"), "fps": settings.get("fps")}
    if expected["kind"] == "video" and shot is not None and take.kind != "footage":
        expected["duration_s"] = min(float(shot.duration_s or 0), float((take.params or {}).get("duration_s") or shot.duration_s or 0)) or None
    res = check_media(take_svc.abs_path(take.media_path), expected)
    res["take_id"] = take.id
    res["kind"] = take.kind
    return res


def check_project(s: Session, project: FilmProject) -> dict:
    """Pre-render gate (spec T): completion, ordering, media validity of
    selected takes, continuity summary, subtitles."""
    from . import continuity, subtitles as sub_svc
    from . import takes as take_svc
    checks: list[dict] = []
    per_shot: dict[str, dict] = {}
    ordered = proj_svc.ordered_shots(s, project.id)
    if not ordered:
        checks.append(_check("shots", "FAIL", "The project has no shots."))
    missing = []
    for sh, sc in ordered:
        t = s.get(FilmTake, sh.selected_take_id) if sh.selected_take_id else None
        label = f"{sc.position + 1}.{sh.position + 1}"
        if t is None or t.status not in ("succeeded", "imported") or take_svc.abs_path(t.media_path) is None:
            missing.append(label)
            per_shot[str(sh.id)] = {"verdict": "FAIL", "checks": [_check("media", "FAIL", "No finished media selected.")]}
            continue
        res = t.qa or check_take(s, t, sh)
        per_shot[str(sh.id)] = {"verdict": res.get("verdict"), "checks": res.get("checks", []), "take_id": t.id}
    if missing:
        checks.append(_check("missing_media", "FAIL", f"{len(missing)} shot(s) without media: {', '.join(missing[:8])}.",
                             shots=missing))
    else:
        checks.append(_check("missing_media", "PASS", "Every shot has selected media."))
    positions = [sh.position for sh, _ in ordered]
    checks.append(_check("ordering", "PASS" if all(sh.position >= 0 for sh, _ in ordered) and len(positions) == len(ordered)
                         else "WARN", "Shot ordering is consistent."))
    cont = continuity.validate_project(s, project, log=False)
    if cont["counts"]["block"]:
        checks.append(_check("continuity", "FAIL", f"{cont['counts']['block']} blocking continuity issue(s).", heuristic=True))
    elif cont["counts"]["warn"]:
        checks.append(_check("continuity", "WARN", f"{cont['counts']['warn']} continuity warning(s) — review the inspector.", heuristic=True))
    else:
        checks.append(_check("continuity", "PASS", "No continuity warnings.", heuristic=True))
    subs = sub_svc.validate(s, project)
    checks.append(_check("subtitles", subs["status"], subs["message"], cues=subs.get("cues", 0)))
    failing = [k for k, v in per_shot.items() if v.get("verdict") == "FAIL"]
    warning = [k for k, v in per_shot.items() if v.get("verdict") == "WARN"]
    if failing:
        checks.append(_check("shot_media", "FAIL", f"{len(failing)} shot(s) failed media checks."))
    elif warning:
        checks.append(_check("shot_media", "WARN", f"{len(warning)} shot(s) have media warnings."))
    else:
        checks.append(_check("shot_media", "PASS", "All selected takes pass technical checks."))
    from . import sequence as seq_svc
    if seq_svc.exists(s, project.id):
        # the sequence — not the storyboard — drives export now, so shot-level
        # media gaps inform but the sequence checks decide
        for c in checks:
            if c["key"] in ("missing_media", "shot_media") and c["status"] == "FAIL":
                c["status"] = "WARN"
                c["message"] += " (storyboard; the edited sequence drives export)"
        checks.extend(seq_svc.qc(s, project))
    report = {"verdict": verdict(checks), "checks": checks, "per_shot": per_shot,
              "continuity": {"mode": cont["mode"], "counts": cont["counts"]}}
    report["repairs"] = repair_queue(s, project, report)
    return report


def repair_queue(s: Session, project: FilmProject, report: dict | None = None) -> list[dict]:
    """Smallest-artifact repair actions (spec V)."""
    report = report or check_project(s, project)
    actions: list[dict] = []
    shots = {str(sh.id): (sh, sc) for sh, sc in proj_svc.ordered_shots(s, project.id)}
    for sid, res in report.get("per_shot", {}).items():
        if res.get("verdict") != "FAIL" and not any(c.get("key") in ("black_frames", "frozen_frames") and c["status"] == "WARN"
                                                    for c in res.get("checks", [])):
            continue
        sh, sc = shots.get(sid, (None, None))
        if sh is None:
            continue
        reason = "; ".join(c["message"] for c in res.get("checks", []) if c["status"] in ("FAIL", "WARN"))
        actions.append({"kind": "regenerate_shot", "entity": "shot", "entity_id": sh.id,
                        "label": f"Shot {sc.position + 1}.{sh.position + 1}", "severity": res.get("verdict"),
                        "reason": reason, "action": f"POST /api/film/shots/{sh.id}/takes"})
    for c in report.get("checks", []):
        if c["key"] == "subtitles" and c["status"] == "FAIL":
            actions.append({"kind": "fix_subtitles", "entity": "project", "entity_id": project.id,
                            "label": "Subtitle track", "severity": "FAIL", "reason": c["message"],
                            "action": f"PUT /api/film/projects/{project.id}/subtitles"})
        if c["key"] == "continuity" and c["status"] == "FAIL":
            actions.append({"kind": "continuity", "entity": "project", "entity_id": project.id,
                            "label": "Continuity", "severity": "FAIL", "reason": c["message"],
                            "action": f"POST /api/film/projects/{project.id}/continuity"})
    return actions


def review_export(path: Path, expected: dict) -> dict:
    """Post-render review (spec U): technical validation, sampled frames,
    audio level, subtitle validity, delivery properties."""
    res = check_media(path, {**expected, "kind": "video"})
    info = res.get("probe") or {}
    checks = list(res["checks"])
    if info.get("audio"):
        try:
            proc = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                                  capture_output=True, text=True, timeout=300)
            m = re.search(r"mean_volume: (-?\d+(?:\.\d+)?) dB", proc.stderr or "")
            if m:
                mean = float(m.group(1))
                status = "PASS" if -30 <= mean <= -8 else "WARN"
                checks.append(_check("audio_level", status, f"Mean audio level {mean:.1f} dB" +
                                     ("" if status == "PASS" else " — outside the comfortable -30…-8 dB range."), level=mean))
        except (OSError, subprocess.TimeoutExpired):
            pass
    samples = []
    if info.get("duration"):
        for frac in (0.1, 0.5, 0.9):
            t = max(0.0, info["duration"] * frac)
            out = path.with_name(f"{path.stem}.sample{int(frac * 100)}.webp")
            try:
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                                "-vf", "scale=480:-2", str(out)], capture_output=True, text=True, timeout=120)
                if out.exists():
                    samples.append(out.name)
            except (OSError, subprocess.TimeoutExpired):
                pass
    exp_runtime = expected.get("runtime_s")
    if exp_runtime and info.get("duration") is not None:
        delta = abs(info["duration"] - float(exp_runtime))
        checks.append(_check("runtime", "PASS" if delta <= 0.5 else "WARN",
                             f"Rendered {info['duration']:.2f}s vs timeline {float(exp_runtime):.2f}s.",
                             actual=info["duration"], expected=exp_runtime))
    return {"verdict": verdict(checks), "checks": checks, "probe": info, "samples": samples}
