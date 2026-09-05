"""Reference-video director mode (spec A): deterministic media analysis
first (ffprobe, scene cuts, shot-length pacing, keyframes, aspect, audio
presence, coarse brightness/saturation), then an optional LLM pass that
turns those numbers + the project's story into a grounded production
proposal. Transcript/OCR are reported as unavailable — no provider
declares them. The reference is structural inspiration, never copied."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageStat
from sqlalchemy.orm import Session

from ..llm import client as llm_client
from ..models import Post
from . import director, events, footage, presets
from . import projects as proj_svc
from . import storage
from . import takes as take_svc
from .models import FilmClip, FilmJob, FilmProject

SYSTEM_REF = """You are the AI Director. Using ONLY the measured facts about a reference video and the project's
own story, propose a production plan that keeps the reference's pacing/structure principles without copying it.
Respond with ONE JSON object only:
{"retained":[str],"changed":[str],"hook":str,"structure":str,"scenes":[{"title":str,"intent":str,"shots":int,
 "duration_s":number}],"media_strategy":str,"audio_strategy":str,"notes":str}"""


class ReferenceError(ValueError):
    pass


def _style_stats(thumbs: list[Path]) -> dict | None:
    if not thumbs:
        return None
    br, sat = [], []
    for p in thumbs[:12]:
        try:
            with Image.open(p) as im:
                hsv = im.convert("HSV")
                st = ImageStat.Stat(hsv)
                sat.append(st.mean[1] / 255)
                br.append(st.mean[2] / 255)
        except Exception:
            continue
    if not br:
        return None
    b, s_ = sum(br) / len(br), sum(sat) / len(sat)
    return {"brightness": round(b, 3), "saturation": round(s_, 3),
            "look": ("dark" if b < 0.35 else "bright" if b > 0.65 else "balanced") + ", "
                    + ("muted" if s_ < 0.25 else "saturated" if s_ > 0.5 else "natural"), "heuristic": True}


def analyze_file(path: Path, thumb_dir: Path, stem: str) -> dict:
    a = footage.analyze_clip(path, thumb_dir, stem)
    info = a.get("technical") or {}
    if not info.get("video"):
        raise ReferenceError("ffprobe could not read the reference video")
    pacing = a.get("pacing") or {}
    median = pacing.get("median_s")
    profile = None
    if median:
        profile = min(presets.PACING_PROFILES.items(), key=lambda kv: abs(kv[1]["base_s"] - median))[0]
        if profile == "custom":
            profile = "normal"
    duration = info.get("duration") or 0
    aspect = None
    if info.get("width") and info.get("height"):
        r = info["width"] / info["height"]
        aspect = min(["16:9", "9:16", "4:3", "1:1", "2.39:1", "4:5"],
                     key=lambda lab: abs(r - __import__("promptforge.film.qa", fromlist=["x"])._aspect_value(lab)))
    thumbs = [thumb_dir / k for k in a.get("keyframes", [])]
    return {"duration_s": duration, "fps": info.get("fps"), "width": info.get("width"), "height": info.get("height"),
            "aspect_ratio": aspect, "audio": bool(info.get("audio")), "cuts": a.get("cuts", []),
            "shots": a.get("segments", []), "shot_count": len(a.get("segments", [])), "pacing": pacing,
            "pacing_profile": profile, "keyframes": [storage.url_for(f"film/clips/thumbs/{k}") for k in a.get("keyframes", [])],
            "style": _style_stats(thumbs), "transcript": None,
            "transcript_note": a.get("transcript_note"), "on_screen_text": None,
            "on_screen_text_note": a.get("on_screen_text_note"),
            "camera_patterns": "not inferable without a vision model", "analyzed_at": datetime.now(timezone.utc).isoformat()}


def analyze_for_project(s: Session, project: FilmProject, path: Path, source: dict, actor: str = "user") -> dict:
    thumb_dir = storage.resolve("film/clips/thumbs/x").parent
    stem = f"ref{project.id}"
    analysis = analyze_file(path, thumb_dir, stem)
    analysis["source"] = source
    project.reference = analysis
    s.flush()
    events.log(s, project.id, f"Reference analysed: {analysis['shot_count']} shots over {analysis['duration_s']:.1f}s "
               f"(median {analysis['pacing'].get('median_s') if analysis['pacing'] else '?'}s → {analysis['pacing_profile']})",
               kind="director", stage="concept", actor=actor, entity=("project", project.id),
               data={"source": source, "aspect_ratio": analysis["aspect_ratio"]})
    return analysis


def analyze_upload(s: Session, project: FilmProject, data: bytes, content_type: str | None, filename: str | None) -> dict:
    ext = storage.ext_for(content_type, filename, storage.VIDEO_TYPES)
    if ext is None:
        raise ReferenceError("reference must be an MP4/WebM/MOV file")
    rel = storage.project_rel(project.id, "reference", storage.new_name(ext))
    full = storage.write(rel, data)
    return analyze_for_project(s, project, full, {"kind": "file", "name": filename, "path": rel})


def analyze_post(s: Session, project: FilmProject, post_id: int) -> dict:
    post = s.get(Post, post_id)
    if post is None or post.media_type != "video" or not post.media_path:
        raise ReferenceError("post is not a stored video")
    path = take_svc.abs_path(post.media_path)
    if path is None:
        raise ReferenceError("post media missing on disk")
    return analyze_for_project(s, project, path, {"kind": "post", "post_id": post.id, "platform": post.platform,
                                                  "url": post.source_url, "author": post.author})


def analyze_clip(s: Session, project: FilmProject, clip_id: int) -> dict:
    clip = s.get(FilmClip, clip_id)
    path = take_svc.abs_path(clip.path) if clip else None
    if path is None:
        raise ReferenceError("clip not found on disk")
    return analyze_for_project(s, project, path, {"kind": "clip", "clip_id": clip.id, "title": clip.title,
                                                  "url": clip.url, "license": clip.license})


def analyze_url(s: Session, project: FilmProject, url: str) -> dict:
    """YouTube/TikTok/Reel URLs need yt-dlp, which PF2 does not bundle."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        raise ReferenceError("Downloading from a URL needs yt-dlp, which is not installed in this build. "
                             "Save the video locally and upload it as the reference instead.")
    rel = storage.project_rel(project.id, "reference", storage.new_name(".mp4"))
    dest = storage.resolve(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL({"outtmpl": str(dest), "format": "mp4/best", "quiet": True}) as ydl:  # pragma: no cover
        ydl.download([url])
    return analyze_for_project(s, project, dest, {"kind": "url", "url": url, "path": rel})


def propose(s: Session, project: FilmProject, use_llm: bool = True) -> FilmJob:
    ref = project.reference or {}
    if not ref.get("shot_count"):
        raise ReferenceError("Analyse a reference video first.")
    st = proj_svc.merge_settings(project.settings, None)
    shots = ref.get("shots") or []
    target = float(st.get("target_runtime_s") or ref.get("duration_s") or 60)
    scale = target / float(ref.get("duration_s") or target)
    # structure: group reference shots into ~4–8 beats by cumulative time
    beats = max(2, min(8, round(len(shots) / 4) or 2))
    per = max(1, -(-len(shots) // beats))          # ceil ⇒ at most `beats` groups
    scenes = []
    for i in range(0, len(shots), per):
        chunk = shots[i:i + per]
        if not chunk:
            continue
        # keep the reference's relative rhythm, scaled to the target runtime,
        # but never propose absurd single-shot lengths
        durations = [min(15.0, max(0.5, round(c["duration_s"] * scale * 2) / 2)) for c in chunk]
        scenes.append({"title": f"Beat {len(scenes) + 1}", "intent": None, "shots": len(chunk),
                       "duration_s": round(sum(durations), 1), "shot_durations_s": durations})
    data = None
    if use_llm:
        facts = {k: ref.get(k) for k in ("duration_s", "shot_count", "pacing", "pacing_profile", "aspect_ratio", "audio", "style")}
        user = (director._project_brief(s, project) + "\n\nREFERENCE FACTS (measured):\n" + json.dumps(facts, default=str)
                + f"\n\nDerived beats: {json.dumps(scenes)}\n\nSTORY:\n" + (project.script or project.synopsis or project.logline or "")[:6000])
        data = director._llm_json("film-director-reference", SYSTEM_REF, user, 1500)
    proposal = {
        "retained": [str(x)[:200] for x in ((data or {}).get("retained") or [])][:8] or [
            f"pacing: median shot {ref['pacing'].get('median_s')}s ({ref.get('pacing_profile')})" if ref.get("pacing") else "pacing",
            f"structure: {len(scenes)} beats over {target:.0f}s", f"aspect ratio {ref.get('aspect_ratio')}"],
        "changed": [str(x)[:200] for x in ((data or {}).get("changed") or [])][:8] or [
            "subject, characters, locations and script come from this project", "no footage or text is reused"],
        "hook": (data or {}).get("hook"), "structure": (data or {}).get("structure") or f"{len(scenes)} beats",
        "scenes": scenes if not (data or {}).get("scenes") else [
            {**sc, **{k: v for k, v in llm.items() if k in ("title", "intent")}}
            for sc, llm in zip(scenes, (data or {}).get("scenes") or [])] + scenes[len((data or {}).get("scenes") or []):],
        "pacing_profile": ref.get("pacing_profile") or st.get("pacing_profile"),
        "aspect_ratio": ref.get("aspect_ratio") or st.get("aspect_ratio"),
        "target_runtime_s": target,
        "media_strategy": (data or {}).get("media_strategy") or "ai_video for character beats; stock/archival for establishing beats where the brief allows",
        "audio_strategy": (data or {}).get("audio_strategy") or ("music + dialogue" if ref.get("audio") else "music bed"),
        "notes": (data or {}).get("notes"),
        "source": ref.get("source"),
    }
    est = director.estimate_costs(s, [{"label": f"b{i}.{j}", "duration_s": d, "media_strategy": "ai_video"}
                                      for i, sc in enumerate(scenes) for j, d in enumerate(sc["shot_durations_s"])])
    proposal["estimates"] = est
    proposal["estimated_cost_usd"] = est["total_usd"]
    proposal["estimated_duration_s"] = round(sum(sc["duration_s"] for sc in scenes), 1)
    proposal["recommended"] = {"video_family": est["video_family"], "video_provider": est["video_provider"],
                               "image_family": est["image_family"]}
    return director._store(s, project.id, "reference_proposal", proposal, "llm" if data is not None else "fallback",
                           {"project_id": project.id}, "plan")
