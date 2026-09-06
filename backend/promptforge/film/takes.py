"""Takes (spec AD, §20–22, S): every generated or imported artifact for a
shot is a take. Generation rides the EXISTING generation queue (one
Generation row per take, D14) — the provider adapters, polling, download,
compression and gallery ingest are reused unchanged; the queue calls
`on_generation()` back when the job ends. Alternates are never deleted;
the shot selects one. Frames: start/end frames are takes too, and a video
take's last frame is extracted so the next shot can start from it."""
from __future__ import annotations

import io
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import settings_store
from ..config import get_config
from ..db import session_scope
from ..generation import pricing
from ..generation import queue as gen_queue
from ..logbus import bus
from ..models import Generation, Post
from ..pipeline import media
from . import capabilities, continuity, costs, events
from . import projects as proj_svc
from . import scoring, shotctx, storage
from .models import FilmProject, FilmScene, FilmShot, FilmTake

FRAME_KINDS = ("start_frame", "end_frame")
GENERATED_KINDS = ("video", "image") + FRAME_KINDS
MAX_CLIP_S_DEFAULT = 10.0
STRATEGY_TOOL = {"still": "Still image", "motion_graphics": "Motion graphics", "user_footage": "Footage",
                 "stock": "Footage search", "archival": "Footage search", "screen_recording": "Footage upload"}


class TakeError(ValueError):
    pass


class TakeBlocked(TakeError):
    """Continuity (strict) or gate blocks."""


# ----------------------------------------------------------------- paths ---
def abs_path(rel: str | None) -> Path | None:
    """DATA_DIR-relative media path (film/… or media/…) → absolute, or None."""
    if not rel:
        return None
    if rel.startswith("film/"):
        try:
            p = storage.resolve(rel)
        except storage.UnsafePath:
            return None
    elif rel.startswith("media/") and ".." not in rel:
        p = (get_config().data_dir / rel).resolve()
        if not p.is_relative_to(get_config().media_dir.resolve()):
            return None
    else:
        return None
    return p if p.is_file() else None


def frame_path(frame: dict | None) -> Path | None:
    return abs_path((frame or {}).get("path")) if frame else None


def _next_number(s: Session, shot_id: int) -> int:
    n = s.execute(select(func.max(FilmTake.number)).where(FilmTake.shot_id == shot_id)).scalar()
    return int(n or 0) + 1


# --------------------------------------------------------- generation ------
def _references(s: Session, ctx: dict, limit: int = 4) -> list[str]:
    """Primary reference images of the present characters (+ location) as
    absolute paths — the identity anchors a reference mode should see."""
    out: list[str] = []
    for c in ctx["assets"]:
        if c["type"] not in ("character", "location", "prop") or not c.get("present", True):
            continue
        ref = c.get("primary_reference")
        if not ref:
            continue
        rel = "film/" + ref["url"].removeprefix("/film-media/") if ref.get("url", "").startswith("/film-media/") else None
        p = abs_path(rel)
        if p:
            out.append(str(p))
        if len(out) >= limit:
            break
    return out


def choose_mode(s: Session, shot: FilmShot, kind: str, ctx: dict, requested: str | None,
                family: str | None, provider: str | None) -> tuple[str, dict]:
    """Pick the richest mode the inputs allow AND a connected provider
    declares: start+end → start_end_to_video, start → image_to_video,
    references → reference_to_image; else the text mode."""
    start = frame_path(shot.start_frame)
    end = frame_path(shot.end_frame)
    refs = _references(s, ctx)
    inputs: dict = {}
    order: list[str]
    if kind in ("video",):
        if requested:
            order = [requested]
        elif start and end:
            order = ["start_end_to_video", "image_to_video", "text_to_video"]
        elif start:
            order = ["image_to_video", "text_to_video"]
        elif refs:
            order = ["reference_to_video", "text_to_video"]
        else:
            order = ["text_to_video"]
    else:
        if requested:
            order = [requested]
        elif refs:
            order = ["reference_to_image", "text_to_image"]
        else:
            order = ["text_to_image"]
    available = scoring.score_candidates
    for mode in order:
        m = capabilities.resolve_mode(mode)
        cands = available(s, mode, capabilities.MODE_KINDS.get(mode, kind), None, family, provider)
        if not cands:
            continue
        needs = next((x["needs"] for x in capabilities.MODES if x["key"] == mode), [])
        real_needs = next((x["needs"] for x in capabilities.MODES if x["key"] == m), [])
        if "image" in needs and not (start or refs):
            continue
        if "end_image" in needs and not end:
            continue
        if "references" in needs and not refs:
            continue
        if "image" in needs or "image" in real_needs:
            # an aliased mode (reference/storyboard → …) feeds the provider's
            # image input with the start frame, else the first reference
            inputs["image"] = str(start) if start else refs[0]
        if "end_image" in needs:
            inputs["end_image"] = str(end)
        if "references" in needs:
            inputs["references"] = refs
        if m == "image_to_image":
            inputs.setdefault("strength", 0.6)
        return mode, inputs
    if requested:
        raise TakeError(f"No connected provider offers {requested.replace('_', ' ')}"
                        + (f" for {family}" if family else "") + " — see Film → capabilities.")
    raise TakeError("No connected provider offers "
                    + ("video" if kind == "video" else "image") + " generation — connect fal.ai, Replicate or "
                    "WaveSpeed in Settings → AI providers.")


def create_take(s: Session, shot: FilmShot, kind: str = "video", mode: str | None = None,
                family: str | None = None, provider: str | None = None, params: dict | None = None,
                change: list[str] | None = None, preserve: list[str] | None = None,
                instruction: str | None = None, approve_cost: bool = False, actor: str = "user",
                enqueue: bool = True) -> FilmTake:
    if kind not in GENERATED_KINDS:
        raise TakeError("kind must be video | image | start_frame | end_frame")
    project = s.get(FilmProject, shot.project_id)
    scene = s.get(FilmScene, shot.scene_id)
    settings = proj_svc.merge_settings(project.settings, None)
    if kind == "video" and shot.media_strategy in STRATEGY_TOOL:
        raise TakeError(f"This shot's media strategy is “{shot.media_strategy}” — use {STRATEGY_TOOL[shot.media_strategy]} "
                        "instead, or switch the strategy to AI video in the inspector.")
    ok, reasons = continuity.can_generate(s, shot)
    if not ok:
        raise TakeBlocked("Strict continuity mode blocks this shot: " + " ".join(reasons)
                          + " Override it on the shot or fix the continuity issue.")

    ctx = shotctx.effective_context(s, shot, scene, project)
    out_kind = "video" if kind == "video" else "image"
    if change or preserve or instruction:
        pr = shotctx.regeneration_prompt(ctx, change or [], preserve or [], instruction, out_kind)
    else:
        pr = shotctx.build_prompt(ctx, out_kind)
    if kind in FRAME_KINDS:
        pr["prompt"] = (f"{'Opening' if kind == 'start_frame' else 'Closing'} frame of the shot. " + pr["prompt"])
    gen_over = (ctx["shot"].get("generation") or {})
    family = (family or gen_over.get("family")
              or settings_store.get(s, "film_video_family" if out_kind == "video" else "film_image_family")
              or ("kling" if out_kind == "video" else "flux")).lower()
    provider = provider or gen_over.get("provider")
    user_override = bool(provider or gen_over.get("provider") or gen_over.get("family"))
    mode, inputs = choose_mode(s, shot, kind, ctx, mode or gen_over.get("mode"), family, provider)
    real_mode = capabilities.resolve_mode(mode)
    p: dict = dict(gen_over.get("params") or {})
    p.update(params or {})
    if out_kind == "video":
        max_clip = float(settings.get("max_clip_s") or MAX_CLIP_S_DEFAULT)
        p.setdefault("duration_s", round(min(float(shot.duration_s or 4), max_clip), 1))
        p.setdefault("resolution", "720p")
    else:
        p.setdefault("size", _size_for(settings.get("aspect_ratio")))
    best, ranked = scoring.pick(s, mode, out_kind, p, family, provider)
    if best is None:
        raise TakeError(f"No connected provider offers {mode.replace('_', ' ')} for {family}.")
    estimate = best["estimate"]
    check = costs.check(s, project, estimate, approve=approve_cost)
    if not check["allowed"]:
        raise costs.BudgetBlocked(check["reason"], check)

    take = FilmTake(shot_id=shot.id, project_id=shot.project_id, number=_next_number(s, shot.id),
                    kind=kind, status="queued", mode=mode, provider=best["provider"],
                    model_family=best["family"], provider_model_id=best["model_id"],
                    prompt=pr["prompt"], negative=pr.get("negative") or None,
                    params={**p, "inputs": {k: (v if k != "references" else list(v)) for k, v in inputs.items()},
                            "change": change or [], "preserve": preserve or [], "instruction": instruction},
                    context=_snapshot(ctx, pr), decision=scoring.decision(best, ranked, user_override),
                    cost_estimate=estimate)
    s.add(take)
    s.flush()
    gen_params = {k: v for k, v in p.items()}
    gen_params["_film_take_id"] = take.id
    gen_params["_mode"] = real_mode
    if inputs:
        gen_params["_inputs"] = inputs
        gen_params["_input_map"] = capabilities.inputs_map(best["family"], best["provider"], real_mode)
    if pr.get("negative"):
        gen_params["_negative"] = pr["negative"]
    g = Generation(provider=best["provider"], provider_model_id=best["model_id"], model_family=best["family"],
                   prompt=pr["prompt"], cost_estimate=estimate, status="queued", params=gen_params)
    s.add(g)
    s.flush()
    take.generation_id = g.id
    if shot.status == "planned":
        shot.status = "framed"
    s.flush()
    costs.reserve(s, take, check)
    events.log(s, shot.project_id,
               f"Take {take.number} ({kind}) queued on {best['provider']} · {best['family']} · {mode.replace('_', ' ')}",
               kind="generation", stage="shot_generation", actor=actor, reason=take.decision.get("reason"),
               entity=("take", take.id),
               data={"shot_id": shot.id, "generation_id": g.id, "estimate_usd": estimate,
                     "alternatives": take.decision.get("alternatives"), "basis": take.decision.get("basis"),
                     "warning": check.get("warning")})
    if enqueue:
        s.commit()
        gen_queue.start_worker()
        gen_queue.enqueue(g.id)
    return take


def _size_for(aspect: str | None) -> str:
    return {"16:9": "1344x768", "9:16": "768x1344", "4:3": "1152x864", "1:1": "1024x1024",
            "2.39:1": "1536x640", "21:9": "1536x640", "4:5": "896x1120"}.get(aspect or "", "1344x768")


def _snapshot(ctx: dict, pr: dict) -> dict:
    return {"assets": ctx["asset_versions"], "locks": ctx["locks"], "asset_locks": ctx["asset_locks"],
            "camera": ctx.get("camera"), "lighting": ctx.get("lighting"), "environment": ctx.get("environment"),
            "color": ctx.get("color"), "motion": ctx.get("motion"), "style": ctx.get("style"),
            "action": ctx.get("action"), "shot_type": ctx["shot"].get("shot_type"),
            "duration_s": ctx["shot"].get("duration_s"), "sources": ctx.get("sources"),
            "constraints": pr.get("constraints"), "start_frame": ctx["shot"].get("start_frame"),
            "end_frame": ctx["shot"].get("end_frame")}


# ------------------------------------------------------------ completion ---
def on_generation(gid: int, status: str) -> None:
    """Queue callback (worker thread). Updates the take, the shot, frames,
    chaining and QA — inside its own session."""
    with session_scope() as s:
        g = s.get(Generation, gid)
        if g is None:
            return
        take = s.execute(select(FilmTake).where(FilmTake.generation_id == gid)).scalar_one_or_none()
        if take is None:
            return
        _apply_generation(s, take, g, status)


def _apply_generation(s: Session, take: FilmTake, g: Generation, status: str) -> None:
    shot = s.get(FilmShot, take.shot_id)
    take.finished_at = datetime.now(timezone.utc)
    if status != "succeeded" or not g.output_post_id:
        take.status = "failed"
        take.error = g.error or "provider reported failure"
        s.flush()
        events.log(s, take.project_id, f"Take {take.number} failed on {take.provider}", kind="generation",
                   stage="shot_generation", actor="system", reason=take.error, entity=("take", take.id),
                   data={"shot_id": take.shot_id})
        return
    post = s.get(Post, g.output_post_id)
    take.status = "succeeded"
    take.post_id = post.id if post else None
    if post is not None:
        take.media_path, take.thumb_path = post.media_path, post.thumb_path
        take.width, take.height, take.duration_s = post.media_width, post.media_height, post.duration_s
    costs.reconcile(s, take, g.cost_actual)
    if shot is not None:
        if take.kind in FRAME_KINDS and post is not None:
            frame = {"kind": "generated", "path": post.media_path, "take_id": take.id, "post_id": post.id,
                     "locked": bool((getattr(shot, take.kind) or {}).get("locked"))}
            setattr(shot, take.kind, frame)
        elif take.kind in ("video", "image"):
            if shot.selected_take_id is None or not _selected_ok(s, shot):
                shot.selected_take_id = take.id
            if shot.status in ("planned", "framed"):
                shot.status = "generated"
            if take.kind == "video":
                _extract_last_frame(s, take)
                _chain_next(s, shot, take)
        from . import qa
        try:
            take.qa = qa.check_take(s, take, shot)
        except Exception as e:  # noqa: BLE001 — QA must never break completion
            take.qa = {"verdict": "WARN", "checks": [{"key": "qa_error", "status": "WARN", "message": str(e)}]}
        if take.qa and take.qa.get("verdict") == "FAIL" and shot.selected_take_id == take.id:
            shot.status = "needs_repair"
        shot.qa = take.qa if shot.selected_take_id == take.id else shot.qa
    s.flush()
    events.log(s, take.project_id, f"Take {take.number} succeeded ({take.kind}) → post {take.post_id}",
               kind="generation", stage="shot_generation", actor="system", entity=("take", take.id),
               data={"shot_id": take.shot_id, "qa": (take.qa or {}).get("verdict"), "cost_actual": take.cost_actual})


def _selected_ok(s: Session, shot: FilmShot) -> bool:
    t = s.get(FilmTake, shot.selected_take_id) if shot.selected_take_id else None
    return bool(t and t.status in ("succeeded", "imported"))


def extract_last_frame(video: Path, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for args in (["-sseof", "-0.2"], []):
        try:
            media._run(["ffmpeg", "-y", "-v", "error", *args, "-i", str(video), "-frames:v", "1",
                        "-update", "1", str(dest)], timeout=120)
            if dest.exists() and dest.stat().st_size > 0:
                return True
        except media.MediaError:
            continue
    return False


def _extract_last_frame(s: Session, take: FilmTake) -> str | None:
    src = abs_path(take.media_path)
    if src is None:
        return None
    rel = storage.project_rel(take.project_id, "frames", f"take{take.id}_last.png")
    ok = extract_last_frame(src, storage.resolve(rel))
    if ok:
        p = dict(take.params or {})
        p["last_frame_path"] = rel
        take.params = p
        s.flush()
        return rel
    return None


def last_frame_of(s: Session, shot: FilmShot) -> tuple[str | None, FilmTake | None]:
    t = s.get(FilmTake, shot.selected_take_id) if shot.selected_take_id else None
    if t is None or t.status not in ("succeeded", "imported") or t.kind not in ("video", "footage", "graphics"):
        return None, t
    rel = (t.params or {}).get("last_frame_path")
    if rel and abs_path(rel):
        return rel, t
    return _extract_last_frame(s, t), t


def previous_shot(s: Session, shot: FilmShot) -> FilmShot | None:
    ordered = [sh for sh, _ in proj_svc.ordered_shots(s, shot.project_id)]
    idx = next((i for i, sh in enumerate(ordered) if sh.id == shot.id), None)
    return ordered[idx - 1] if idx else None


def next_shot(s: Session, shot: FilmShot) -> FilmShot | None:
    ordered = [sh for sh, _ in proj_svc.ordered_shots(s, shot.project_id)]
    idx = next((i for i, sh in enumerate(ordered) if sh.id == shot.id), None)
    return ordered[idx + 1] if idx is not None and idx + 1 < len(ordered) else None


def use_previous_last_frame(s: Session, shot: FilmShot, actor: str = "user") -> dict | None:
    """“Use previous shot's last frame as this shot's start frame.”"""
    prev = previous_shot(s, shot)
    if prev is None:
        raise TakeError("This is the first shot — there is no previous shot to chain from.")
    rel, t = last_frame_of(s, prev)
    if not rel:
        raise TakeError(f"Shot {prev.position + 1} has no finished video take yet — generate it first.")
    if (shot.start_frame or {}).get("locked"):
        raise TakeError("The start frame is locked on this shot — unlock it to replace it.")
    shot.start_frame = {"kind": "previous_shot", "path": rel, "take_id": t.id, "source_shot_id": prev.id,
                        "locked": False}
    shot.chain_from_previous = True
    s.flush()
    events.log(s, shot.project_id, f"Shot {shot.position + 1} starts from shot {prev.position + 1}'s last frame",
               kind="edit", stage="storyboard", actor=actor, entity=("shot", shot.id),
               data={"source_shot_id": prev.id, "take_id": t.id})
    return shot.start_frame


def _chain_next(s: Session, shot: FilmShot, take: FilmTake) -> None:
    """After a video take lands, feed the next chained shot automatically
    (unless its start frame is locked)."""
    nxt = next_shot(s, shot)
    if nxt is None or not nxt.chain_from_previous or shot.selected_take_id != take.id:
        return
    if (nxt.start_frame or {}).get("locked"):
        return
    rel = (take.params or {}).get("last_frame_path")
    if not rel:
        return
    nxt.start_frame = {"kind": "previous_shot", "path": rel, "take_id": take.id, "source_shot_id": shot.id,
                       "locked": False}
    s.flush()


# ------------------------------------------------------------ selection ----
def select_take(s: Session, shot: FilmShot, take: FilmTake, actor: str = "user") -> FilmShot:
    if take.shot_id != shot.id:
        raise TakeError("take belongs to another shot")
    if take.status not in ("succeeded", "imported"):
        raise TakeError("only finished takes can be selected")
    shot.selected_take_id = take.id
    shot.qa = take.qa
    if take.kind in ("video", "footage", "graphics", "image") and shot.status in ("planned", "framed"):
        shot.status = "generated"
    if take.kind == "video":
        rel, _ = last_frame_of(s, shot)
        nxt = next_shot(s, shot)
        if rel and nxt and nxt.chain_from_previous and not (nxt.start_frame or {}).get("locked"):
            nxt.start_frame = {"kind": "previous_shot", "path": rel, "take_id": take.id,
                               "source_shot_id": shot.id, "locked": False}
    s.flush()
    events.log(s, shot.project_id, f"Shot {shot.position + 1}: take {take.number} selected", kind="edit",
               stage="shot_generation", actor=actor, entity=("shot", shot.id), data={"take_id": take.id})
    return shot


def set_frame(s: Session, shot: FilmShot, which: str, frame: dict | None, actor: str = "user") -> dict | None:
    if which not in FRAME_KINDS:
        raise TakeError("which must be start_frame | end_frame")
    if frame is not None:
        if frame.get("path") and abs_path(frame["path"]) is None:
            raise TakeError("frame path does not exist")
        frame = {"kind": frame.get("kind", "upload"), "path": frame.get("path"), "take_id": frame.get("take_id"),
                 "post_id": frame.get("post_id"), "ref_id": frame.get("ref_id"),
                 "source_shot_id": frame.get("source_shot_id"), "locked": bool(frame.get("locked"))}
    setattr(shot, which, frame)
    if which == "start_frame" and frame is None:
        shot.chain_from_previous = False
    s.flush()
    return frame


def store_frame_upload(s: Session, shot: FilmShot, which: str, data: bytes, content_type: str | None,
                       filename: str | None) -> dict:
    ext = storage.ext_for(content_type, filename, storage.IMAGE_TYPES)
    if ext is None:
        raise TakeError("frame must be PNG, JPEG or WebP")
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception:
        raise TakeError("file is not a valid image")
    rel = storage.project_rel(shot.project_id, "frames", storage.new_name(ext))
    storage.write(rel, data)
    return set_frame(s, shot, which, {"kind": "upload", "path": rel})


def frame_from_post(s: Session, shot: FilmShot, which: str, post_id: int) -> dict:
    post = s.get(Post, post_id)
    if post is None or not post.media_path:
        raise TakeError("post not found")
    rel = post.media_path if post.media_type == "image" else post.thumb_path
    return set_frame(s, shot, which, {"kind": "storyboard" if post.origin == "generated" else "gallery",
                                      "path": rel, "post_id": post.id})


def frame_from_ref(s: Session, shot: FilmShot, which: str, ref_id: int) -> dict:
    from .models import FilmAssetRef
    ref = s.get(FilmAssetRef, ref_id)
    if ref is None:
        raise TakeError("reference not found")
    return set_frame(s, shot, which, {"kind": "asset", "path": ref.path, "ref_id": ref.id})


# ------------------------------------------------------------- imports -----
def import_take(s: Session, shot: FilmShot, data: bytes, content_type: str | None, filename: str | None,
                kind: str = "footage", source: str = "upload", provenance: dict | None = None,
                select: bool = True, actor: str = "user") -> FilmTake:
    is_video = storage.ext_for(content_type, filename, storage.VIDEO_TYPES) is not None
    is_image = storage.ext_for(content_type, filename, storage.IMAGE_TYPES) is not None
    if not (is_video or is_image):
        raise TakeError("upload must be MP4/WebM/MOV video or PNG/JPEG/WebP image")
    ext = storage.ext_for(content_type, filename, storage.VIDEO_TYPES if is_video else storage.IMAGE_TYPES)
    name = storage.new_name(ext)
    rel = storage.project_rel(shot.project_id, "takes", name)
    full = storage.write(rel, data)
    thumb_rel = storage.project_rel(shot.project_id, "takes", Path(name).stem + ".thumb.webp")
    width = height = duration = None
    try:
        if is_video:
            meta = media.probe_video(full)
            width, height, duration = meta.get("width"), meta.get("height"), meta.get("duration")
            media.make_video_thumb(full, storage.resolve(thumb_rel))
        else:
            with Image.open(full) as im:
                width, height = im.size
            media.make_image_thumb(full, storage.resolve(thumb_rel))
    except Exception:
        thumb_rel = None
    take = FilmTake(shot_id=shot.id, project_id=shot.project_id, number=_next_number(s, shot.id),
                    kind=kind if is_video else "image", status="imported", mode="import",
                    provider="import", media_path=rel, thumb_path=thumb_rel, width=width, height=height,
                    duration_s=duration, params={"source": source, "filename": filename},
                    context={"provenance": provenance or {"origin": source}}, cost_estimate=0.0,
                    cost_actual=0.0, finished_at=datetime.now(timezone.utc))
    s.add(take)
    s.flush()
    if is_video:
        _extract_last_frame(s, take)
    if select and (shot.selected_take_id is None or not _selected_ok(s, shot)):
        shot.selected_take_id = take.id
        if shot.status in ("planned", "framed"):
            shot.status = "generated"
    from . import qa
    try:
        take.qa = qa.check_take(s, take, shot)
    except Exception as e:  # noqa: BLE001
        take.qa = {"verdict": "WARN", "checks": [{"key": "qa_error", "status": "WARN", "message": str(e)}]}
    if shot.selected_take_id == take.id:
        shot.qa = take.qa
        if take.qa.get("verdict") == "FAIL":
            shot.status = "needs_repair"
        elif take.kind == "footage":
            _chain_next(s, shot, take)
    s.flush()
    events.log(s, shot.project_id, f"Take {take.number} imported ({take.kind})", kind="generation",
               stage="shot_generation", actor=actor, entity=("take", take.id),
               data={"shot_id": shot.id, "source": source})
    return take


# ------------------------------------------------------------- compare -----
def compare(s: Session, a: FilmTake, b: FilmTake) -> dict:
    def flat(t: FilmTake) -> dict:
        return {"id": t.id, "number": t.number, "kind": t.kind, "status": t.status, "provider": t.provider,
                "model_family": t.model_family, "mode": t.mode, "prompt": t.prompt,
                "assets": (t.context or {}).get("assets"), "camera": (t.context or {}).get("camera"),
                "lighting": (t.context or {}).get("lighting"), "cost": t.cost_actual if t.cost_actual is not None else t.cost_estimate,
                "duration_s": t.duration_s, "qa": (t.qa or {}).get("verdict"),
                "media_url": proj_svc.take_dict(t)["media_url"], "thumb_url": proj_svc.take_dict(t)["thumb_url"],
                "created_at": t.created_at.isoformat() if t.created_at else None}
    fa, fb = flat(a), flat(b)
    diff = {k: {"a": fa[k], "b": fb[k]} for k in fa if k not in ("id", "number", "media_url", "thumb_url", "created_at")
            and fa[k] != fb[k]}
    return {"a": fa, "b": fb, "differences": diff}


# ------------------------------------------------------------- recovery ----
def sync_pending(s: Session, project_id: int | None = None) -> int:
    """Takes whose generation finished while the hook was unavailable (e.g.
    restart mid-poll) get reconciled from the Generation row."""
    stmt = select(FilmTake).where(FilmTake.status.in_(["queued", "running"]), FilmTake.generation_id.is_not(None))
    if project_id:
        stmt = stmt.where(FilmTake.project_id == project_id)
    n = 0
    for take in s.execute(stmt).scalars():
        g = s.get(Generation, take.generation_id)
        if g is None:
            continue
        if g.status == "running" and take.status != "running":
            take.status = "running"
        elif g.status in ("succeeded", "failed"):
            _apply_generation(s, take, g, g.status)
            n += 1
    s.flush()
    return n


def takes_of(s: Session, shot_id: int) -> list[FilmTake]:
    return list(s.execute(select(FilmTake).where(FilmTake.shot_id == shot_id)
                          .order_by(FilmTake.number.asc())).scalars())


# ------------------------------------------------------------ review (E6) ---
REVIEW_STATUSES = ("approved", "rejected")


def set_review(s: Session, take: FilmTake, status: str | None, note: str | None = None,
               actor: str = "user") -> FilmTake:
    """Approve/reject a finished take (None clears back to pending)."""
    if status is not None and status not in REVIEW_STATUSES:
        raise TakeError(f"Review status must be one of {', '.join(REVIEW_STATUSES)} (or null to clear).")
    if take.status not in ("succeeded", "imported"):
        raise TakeError("Only finished takes can be reviewed.")
    take.review = None if status is None else {
        "status": status, "note": note,
        "at": datetime.now(timezone.utc).isoformat(), "actor": actor}
    s.flush()
    events.log(s, take.project_id,
               f"Take {take.number} of shot #{take.shot_id} {status or 'review cleared'}",
               kind="qa", stage="editor", actor=actor, entity=("take", take.id),
               data={"status": status, "note": note})
    return take


def review_queue(s: Session, project_id: int) -> dict:
    """Everything awaiting a decision: finished-but-unreviewed takes (with
    shot context + whether they're live in the storyboard/sequence) and
    failed takes (regenerate candidates)."""
    from .models import FilmScene, FilmShot, FilmTimelineClip
    rows = s.execute(select(FilmTake).where(FilmTake.project_id == project_id)
                     .order_by(FilmTake.id.desc())).scalars()
    used_by_clip: dict[int, int] = {}
    for cid, tid in s.execute(select(FilmTimelineClip.id, FilmTimelineClip.take_id)
                              .where(FilmTimelineClip.project_id == project_id,
                                     FilmTimelineClip.take_id.is_not(None))):
        used_by_clip.setdefault(tid, cid)
    pending, decided, failed = [], [], []
    for t in rows:
        sh = s.get(FilmShot, t.shot_id)
        if sh is None:
            continue
        sc = s.get(FilmScene, sh.scene_id)
        from . import projects as proj_svc
        item = {"take": proj_svc.take_dict(t),
                "shot_id": sh.id, "shot_label": f"{(sc.position if sc else 0) + 1}.{sh.position + 1}",
                "shot_title": sh.title, "selected_on_shot": sh.selected_take_id == t.id,
                "sequence_clip_id": used_by_clip.get(t.id), "review": t.review}
        if t.status == "failed":
            failed.append(item)
        elif t.status in ("succeeded", "imported"):
            (decided if t.review else pending).append(item)
    return {"pending": pending, "decided": decided[:30], "failed": failed[:30],
            "counts": {"pending": len(pending), "failed": len(failed)}}
