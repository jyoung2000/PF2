"""Footage corpus (spec D, E): user footage (analysed with ffprobe + scene
cuts + keyframes, indexed for search) and stock/archival search adapters
(Pexels, Pixabay, Unsplash when keys are configured; Archive.org, NASA and
Wikimedia Commons without keys). License metadata is stored exactly as the
source reports it — unknown stays unknown. Attaching a clip to a shot makes
an imported take, never a copy of someone else's rights claim."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..pipeline import media
from . import events, qa, storage
from . import takes as take_svc
from .models import FilmClip, FilmShot

SOURCES: dict[str, dict] = {
    "pexels": {"label": "Pexels", "key_setting": "pexels_api_key", "key_url": "https://www.pexels.com/api/",
               "media": ["video", "image"], "license": {"name": "Pexels License", "url": "https://www.pexels.com/license/"}},
    "pixabay": {"label": "Pixabay", "key_setting": "pixabay_api_key", "key_url": "https://pixabay.com/api/docs/",
                "media": ["video", "image"], "license": {"name": "Pixabay Content License", "url": "https://pixabay.com/service/license-summary/"}},
    "unsplash": {"label": "Unsplash", "key_setting": "unsplash_access_key", "key_url": "https://unsplash.com/developers",
                 "media": ["image"], "license": {"name": "Unsplash License", "url": "https://unsplash.com/license"}},
    "archive": {"label": "Archive.org", "key_setting": None, "key_url": None, "media": ["video"], "license": None},
    "nasa": {"label": "NASA", "key_setting": None, "key_url": None, "media": ["video", "image"],
             "license": {"name": "NASA media (generally public domain; check item notes)", "url": "https://www.nasa.gov/nasa-brand-center/images-and-media/"}},
    "wikimedia": {"label": "Wikimedia Commons", "key_setting": None, "key_url": None, "media": ["video", "image"], "license": None},
}
STOP = {"the", "a", "an", "of", "in", "on", "at", "and", "or", "to", "with", "from", "my", "our", "shot", "footage",
        "clip", "video", "find", "me", "some", "for", "is", "are"}


class FootageError(ValueError):
    pass


def configured_sources(s: Session) -> list[dict]:
    out = []
    for key, src in SOURCES.items():
        configured = True if not src["key_setting"] else bool(settings_store.get(s, src["key_setting"]))
        out.append({"key": key, "label": src["label"], "configured": configured, "media": src["media"],
                    "needs_key": bool(src["key_setting"]), "key_setting": src["key_setting"],
                    "key_url": src["key_url"], "license": src["license"]})
    return out


def _client(transport=None) -> httpx.Client:
    kw: dict = {"timeout": 30, "follow_redirects": True, "headers": {"User-Agent": "PromptForge/1.0 (film studio footage search)"}}
    if transport is not None:
        kw["transport"] = transport
    return httpx.Client(**kw)


def _item(source: str, sid, url, title, description, media_type, download_url, thumb_url=None,
          duration=None, width=None, height=None, license=None, attribution=None, page_url=None) -> dict:
    return {"source": source, "source_id": str(sid), "url": url or page_url, "page_url": page_url or url,
            "title": (title or "")[:300] or None, "description": (description or "")[:1000] or None,
            "media_type": media_type, "download_url": download_url, "thumb_url": thumb_url,
            "duration_s": duration, "width": width, "height": height,
            "license": license, "attribution": attribution}


# ------------------------------------------------------------- adapters ---
def _pexels(c: httpx.Client, q: str, media_type: str, key: str, n: int) -> list[dict]:
    lic = SOURCES["pexels"]["license"]
    if media_type == "video":
        r = c.get("https://api.pexels.com/videos/search", params={"query": q, "per_page": n}, headers={"Authorization": key})
        r.raise_for_status()
        out = []
        for v in r.json().get("videos", []):
            files = sorted([f for f in v.get("video_files", []) if f.get("link")],
                           key=lambda f: -(f.get("height") or 0))
            best = next((f for f in files if (f.get("height") or 0) <= 1080), files[0] if files else None)
            if not best:
                continue
            user = (v.get("user") or {}).get("name")
            out.append(_item("pexels", v["id"], v.get("url"), f"Pexels video {v['id']}", None, "video", best["link"],
                             v.get("image"), v.get("duration"), best.get("width"), best.get("height"), lic,
                             f"Video by {user} on Pexels" if user else "Pexels", v.get("url")))
        return out
    r = c.get("https://api.pexels.com/v1/search", params={"query": q, "per_page": n}, headers={"Authorization": key})
    r.raise_for_status()
    return [_item("pexels", p["id"], p.get("url"), p.get("alt"), None, "image", (p.get("src") or {}).get("large2x") or (p.get("src") or {}).get("original"),
                  (p.get("src") or {}).get("medium"), None, p.get("width"), p.get("height"), lic,
                  f"Photo by {p.get('photographer')} on Pexels", p.get("url")) for p in r.json().get("photos", [])]


def _pixabay(c: httpx.Client, q: str, media_type: str, key: str, n: int) -> list[dict]:
    lic = SOURCES["pixabay"]["license"]
    if media_type == "video":
        r = c.get("https://pixabay.com/api/videos/", params={"key": key, "q": q, "per_page": max(3, n)})
        r.raise_for_status()
        out = []
        for h in r.json().get("hits", []):
            vids = h.get("videos") or {}
            best = vids.get("medium") or vids.get("small") or vids.get("large") or {}
            if not best.get("url"):
                continue
            out.append(_item("pixabay", h["id"], h.get("pageURL"), h.get("tags"), None, "video", best["url"],
                             best.get("thumbnail"), h.get("duration"), best.get("width"), best.get("height"), lic,
                             f"{h.get('user')} on Pixabay", h.get("pageURL")))
        return out
    r = c.get("https://pixabay.com/api/", params={"key": key, "q": q, "per_page": max(3, n), "image_type": "photo"})
    r.raise_for_status()
    return [_item("pixabay", h["id"], h.get("pageURL"), h.get("tags"), None, "image", h.get("largeImageURL"),
                  h.get("previewURL"), None, h.get("imageWidth"), h.get("imageHeight"), lic,
                  f"{h.get('user')} on Pixabay", h.get("pageURL")) for h in r.json().get("hits", [])]


def _unsplash(c: httpx.Client, q: str, media_type: str, key: str, n: int) -> list[dict]:
    if media_type != "image":
        return []
    r = c.get("https://api.unsplash.com/search/photos", params={"query": q, "per_page": n},
              headers={"Authorization": f"Client-ID {key}"})
    r.raise_for_status()
    lic = SOURCES["unsplash"]["license"]
    return [_item("unsplash", p["id"], (p.get("links") or {}).get("html"), p.get("alt_description") or p.get("description"),
                  p.get("description"), "image", (p.get("urls") or {}).get("full") or (p.get("urls") or {}).get("regular"),
                  (p.get("urls") or {}).get("small"), None, p.get("width"), p.get("height"), lic,
                  f"Photo by {(p.get('user') or {}).get('name')} on Unsplash", (p.get("links") or {}).get("html"))
            for p in r.json().get("results", [])]


def _archive(c: httpx.Client, q: str, media_type: str, key: str | None, n: int) -> list[dict]:
    if media_type != "video":
        return []
    r = c.get("https://archive.org/advancedsearch.php",
              params={"q": f"({q}) AND mediatype:(movies)", "fl[]": ["identifier", "title", "description", "licenseurl", "creator"],
                      "rows": n, "output": "json"})
    r.raise_for_status()
    out = []
    for d in (r.json().get("response") or {}).get("docs", []):
        ident = d.get("identifier")
        if not ident:
            continue
        lic_url = d.get("licenseurl")
        lic = {"name": "as stated by the item", "url": lic_url} if lic_url else None
        desc = d.get("description")
        if isinstance(desc, list):
            desc = " ".join(str(x) for x in desc)
        out.append(_item("archive", ident, f"https://archive.org/details/{ident}", d.get("title"), desc, "video",
                         f"https://archive.org/download/{ident}", f"https://archive.org/services/img/{ident}",
                         None, None, None, lic, f"{d.get('creator') or 'Internet Archive'} (archive.org/{ident})",
                         f"https://archive.org/details/{ident}"))
    return out


def _nasa(c: httpx.Client, q: str, media_type: str, key: str | None, n: int) -> list[dict]:
    r = c.get("https://images-api.nasa.gov/search", params={"q": q, "media_type": media_type})
    r.raise_for_status()
    lic = SOURCES["nasa"]["license"]
    out = []
    for it in (r.json().get("collection") or {}).get("items", [])[:n]:
        data = (it.get("data") or [{}])[0]
        links = it.get("links") or []
        thumb = next((l.get("href") for l in links if l.get("rel") == "preview"), None)
        out.append(_item("nasa", data.get("nasa_id"), it.get("href"), data.get("title"), data.get("description"),
                         media_type, it.get("href"), thumb, None, None, None, lic,
                         f"NASA / {data.get('center') or 'NASA'}", it.get("href")))
    return out


def _wikimedia(c: httpx.Client, q: str, media_type: str, key: str | None, n: int) -> list[dict]:
    ftype = "video" if media_type == "video" else "bitmap"
    r = c.get("https://commons.wikimedia.org/w/api.php",
              params={"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                      "gsrsearch": f"{q} filetype:{ftype}", "gsrlimit": n, "prop": "imageinfo",
                      "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 480})
    r.raise_for_status()
    out = []
    for page in ((r.json().get("query") or {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic_name = (meta.get("LicenseShortName") or {}).get("value")
        lic_url = (meta.get("LicenseUrl") or {}).get("value")
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value") or "")
        out.append(_item("wikimedia", page.get("pageid"), info.get("descriptionurl"), page.get("title"),
                         re.sub(r"<[^>]+>", "", (meta.get("ImageDescription") or {}).get("value") or ""),
                         media_type, info.get("url"), info.get("thumburl"), None, info.get("width"), info.get("height"),
                         {"name": lic_name, "url": lic_url} if lic_name else None,
                         f"{artist} via Wikimedia Commons" if artist else "Wikimedia Commons", info.get("descriptionurl")))
    return out


_ADAPTERS = {"pexels": _pexels, "pixabay": _pixabay, "unsplash": _unsplash, "archive": _archive,
             "nasa": _nasa, "wikimedia": _wikimedia}


def search(s: Session, q: str, sources: list[str] | None = None, media_type: str = "video",
           per_source: int = 8, transport=None) -> dict:
    """Search every configured source; failures are isolated per source."""
    q = (q or "").strip()
    if not q:
        raise FootageError("search query is empty")
    wanted = sources or list(SOURCES)
    results: list[dict] = []
    errors: dict[str, str] = {}
    skipped: list[str] = []
    with _client(transport) as c:
        for key in wanted:
            src = SOURCES.get(key)
            if src is None or media_type not in src["media"]:
                continue
            api_key = settings_store.get(s, src["key_setting"]) if src["key_setting"] else None
            if src["key_setting"] and not api_key:
                skipped.append(key)
                continue
            try:
                results += _ADAPTERS[key](c, q, media_type, api_key, per_source)
            except Exception as e:  # noqa: BLE001 — one source down never hides the others
                errors[key] = f"{type(e).__name__}: {str(e)[:200]}"
    return {"query": q, "media_type": media_type, "results": results, "errors": errors,
            "needs_setup": skipped}


# ------------------------------------------------------- user footage -----
def _keywords(*texts: str | None) -> list[str]:
    seen: list[str] = []
    for t in texts:
        for w in re.findall(r"[a-z0-9]{3,}", (t or "").lower()):
            if w not in STOP and w not in seen:
                seen.append(w)
    return seen[:60]


def detect_cuts(path: Path, threshold: float = 0.35, max_cuts: int = 200) -> list[float]:
    try:
        proc = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf", f"select='gt(scene,{threshold})',showinfo",
                               "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return []
    cuts = [float(m.group(1)) for m in re.finditer(r"pts_time:\s*(\d+(?:\.\d+)?)", proc.stderr or "")]
    return sorted(set(round(c, 3) for c in cuts))[:max_cuts]


def analyze_clip(path: Path, thumb_dir: Path | None = None, stem: str = "clip", max_keyframes: int = 12) -> dict:
    info = qa.probe(path) or {}
    duration = info.get("duration") or 0.0
    cuts = detect_cuts(path) if info.get("video") and duration > 0.5 else []
    bounds = [0.0] + [c for c in cuts if 0 < c < duration] + [duration]
    segments = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b - a < 0.2:
            continue
        segments.append({"index": len(segments), "start_s": round(a, 3), "end_s": round(b, 3),
                         "duration_s": round(b - a, 3)})
    keyframes = []
    if thumb_dir is not None and info.get("video"):
        thumb_dir.mkdir(parents=True, exist_ok=True)
        step = max(1, len(segments) // max_keyframes) if segments else 1
        for seg in segments[::step][:max_keyframes]:
            t = seg["start_s"] + min(0.5, seg["duration_s"] / 2)
            out = thumb_dir / f"{stem}.kf{seg['index']}.webp"
            try:
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                                "-vf", "scale=480:-2", str(out)], capture_output=True, timeout=120)
                if out.exists():
                    seg["thumb"] = out.name
                    keyframes.append(out.name)
            except (OSError, subprocess.TimeoutExpired):
                pass
    dur_list = [sg["duration_s"] for sg in segments]
    pacing = None
    if dur_list:
        srt = sorted(dur_list)
        pacing = {"shots": len(dur_list), "median_s": round(srt[len(srt) // 2], 2),
                  "mean_s": round(sum(dur_list) / len(dur_list), 2), "min_s": round(srt[0], 2), "max_s": round(srt[-1], 2)}
    return {"technical": info, "cuts": cuts, "segments": segments, "keyframes": keyframes, "pacing": pacing,
            "transcript": None, "transcript_note": "No configured provider declares speech-to-text.",
            "on_screen_text": None, "on_screen_text_note": "OCR is not available in this build."}


def import_user_clip(s: Session, data: bytes, content_type: str | None, filename: str | None,
                     project_id: int | None = None, title: str | None = None, description: str | None = None,
                     tags: list[str] | None = None, actor: str = "user") -> FilmClip:
    is_video = storage.ext_for(content_type, filename, storage.VIDEO_TYPES) is not None
    ext = storage.ext_for(content_type, filename, storage.VIDEO_TYPES if is_video else storage.IMAGE_TYPES)
    if ext is None:
        raise FootageError("footage must be MP4/WebM/MOV (or PNG/JPEG/WebP for stills)")
    name = storage.new_name(ext)
    rel = storage.clip_rel(name)
    full = storage.write(rel, data)
    thumb_rel = None
    analysis: dict = {}
    if is_video:
        analysis = analyze_clip(full, storage.resolve("film/clips/thumbs/x").parent, Path(name).stem)
        info = analysis.get("technical") or {}
        if not info.get("video"):
            storage.remove(rel)
            raise FootageError("ffprobe could not read the video")
        try:
            thumb_rel = f"film/clips/thumbs/{Path(name).stem}.webp"
            media.make_video_thumb(full, storage.resolve(thumb_rel))
        except Exception:
            thumb_rel = None
        width, height, duration, fps = info.get("width"), info.get("height"), info.get("duration"), info.get("fps")
    else:
        from PIL import Image
        with Image.open(full) as im:
            width, height = im.size
        duration = fps = None
        try:
            thumb_rel = f"film/clips/thumbs/{Path(name).stem}.webp"
            media.make_image_thumb(full, storage.resolve(thumb_rel))
        except Exception:
            thumb_rel = None
    clip = FilmClip(project_id=project_id, source="user", source_id=Path(name).stem, url=None,
                    title=(title or filename or "clip")[:300], description=description,
                    license={"name": "Your own footage", "url": None}, media_type="video" if is_video else "image",
                    duration_s=duration, width=width, height=height, fps=fps, tags=[str(t)[:40] for t in (tags or [])][:30],
                    keywords=_keywords(title, filename, description, " ".join(tags or [])), path=rel,
                    thumb_path=thumb_rel, analysis=analysis)
    s.add(clip)
    s.flush()
    events.log(s, project_id, f"Footage imported: {clip.title}", kind="edit", stage="assets", actor=actor,
               entity=("clip", clip.id), data={"segments": len(analysis.get("segments", [])), "duration_s": duration})
    return clip


def describe_with_llm(s: Session, clip: FilmClip) -> list[str] | None:
    """Optional semantic descriptors from the central LLM (only what we know:
    title/description/technical stats — no frames are sent)."""
    from ..llm import client as llm_client
    try:
        raw = llm_client.run_llm("film-footage-describe",
                                 "Return a JSON list of up to 12 short lowercase search keywords describing this footage.",
                                 json.dumps({"title": clip.title, "description": clip.description,
                                             "duration_s": clip.duration_s, "segments": len((clip.analysis or {}).get("segments", []))}),
                                 max_tokens=200)
    except llm_client.LLMNotConfigured:
        return None
    m = re.search(r"\[.*\]", raw or "", re.S)
    try:
        words = json.loads(m.group(0)) if m else []
    except ValueError:
        return None
    words = [str(w).strip().lower()[:40] for w in words if str(w).strip()]
    if words:
        clip.keywords = list(dict.fromkeys(list(clip.keywords or []) + words))[:80]
        s.flush()
    return words


def search_clips(s: Session, q: str, project_id: int | None = None, media_type: str | None = None,
                 limit: int = 20) -> list[dict]:
    """Ranked segments from the local corpus with a confidence score."""
    terms = _keywords(q)
    stmt = select(FilmClip)
    if project_id is not None:
        stmt = stmt.where((FilmClip.project_id == project_id) | (FilmClip.project_id.is_(None)))
    if media_type:
        stmt = stmt.where(FilmClip.media_type == media_type)
    out = []
    for clip in s.execute(stmt).scalars():
        hay = {"title": _keywords(clip.title), "description": _keywords(clip.description),
               "keywords": list(clip.keywords or []), "tags": list(clip.tags or []),
               "transcript": _keywords(clip.transcript)}
        weights = {"title": 3.0, "keywords": 2.0, "tags": 2.0, "description": 1.5, "transcript": 1.0}
        score = 0.0
        matched: set[str] = set()
        for field, words in hay.items():
            for t in terms:
                if t in words or any(w.startswith(t) for w in words):
                    score += weights[field]
                    matched.add(t)
        if not terms or not matched:
            continue
        confidence = round(min(1.0, len(matched) / len(terms)) * min(1.0, score / (3.0 * len(terms))) ** 0.5, 3)
        segments = (clip.analysis or {}).get("segments") or [{"index": 0, "start_s": 0.0, "end_s": clip.duration_s or 0,
                                                                "duration_s": clip.duration_s or 0}]
        for seg in segments[:6]:
            out.append({"clip_id": clip.id, "title": clip.title, "source": clip.source, "media_type": clip.media_type,
                        "license": clip.license, "url": storage.url_for(clip.path),
                        "thumb_url": storage.url_for(f"film/clips/thumbs/{seg['thumb']}") if seg.get("thumb")
                        else storage.url_for(clip.thumb_path),
                        "segment": {k: seg[k] for k in ("index", "start_s", "end_s", "duration_s") if k in seg},
                        "timecode": f"{seg.get('start_s', 0):.2f}–{seg.get('end_s', 0):.2f}",
                        "confidence": confidence, "matched": sorted(matched), "score": round(score, 2)})
    out.sort(key=lambda r: (-r["confidence"], -r["score"], r["clip_id"], r["segment"].get("index", 0)))
    return out[:limit]


def clip_dict(c: FilmClip) -> dict:
    return {"id": c.id, "project_id": c.project_id, "source": c.source, "source_id": c.source_id, "url": c.url,
            "title": c.title, "description": c.description, "license": c.license, "media_type": c.media_type,
            "duration_s": c.duration_s, "width": c.width, "height": c.height, "fps": c.fps,
            "transcript": c.transcript, "tags": c.tags or [], "keywords": c.keywords or [],
            "file_url": storage.url_for(c.path), "thumb_url": storage.url_for(c.thumb_path),
            "segments": (c.analysis or {}).get("segments", []), "pacing": (c.analysis or {}).get("pacing"),
            "notes": {k: v for k, v in (c.analysis or {}).items() if k.endswith("_note")},
            "created_at": c.created_at.isoformat() if c.created_at else None}


# --------------------------------------------------------- attaching -----
def download_result(s: Session, result: dict, transport=None) -> FilmClip:
    """Fetch a search result into the corpus (idempotent per source id)."""
    source, sid = result.get("source"), str(result.get("source_id"))
    existing = s.execute(select(FilmClip).where(FilmClip.source == source, FilmClip.source_id == sid)).scalar_one_or_none()
    if existing is not None and existing.path and take_svc.abs_path(existing.path):
        return existing
    url = result.get("download_url")
    if not url:
        raise FootageError("result has no downloadable file")
    media_type = result.get("media_type") or "video"
    ext = ".mp4" if media_type == "video" else ".jpg"
    name = storage.new_name(ext)
    rel = storage.clip_rel(name)
    dest = storage.resolve(rel)
    with _client(transport) as c:
        media.download(url, dest, c, max_bytes=800_000_000)
    thumb_rel = f"film/clips/thumbs/{Path(name).stem}.webp"
    analysis = {}
    if media_type == "video":
        analysis = analyze_clip(dest, storage.resolve("film/clips/thumbs/x").parent, Path(name).stem)
        try:
            media.make_video_thumb(dest, storage.resolve(thumb_rel))
        except Exception:
            thumb_rel = None
    else:
        try:
            media.make_image_thumb(dest, storage.resolve(thumb_rel))
        except Exception:
            thumb_rel = None
    info = analysis.get("technical") or {}
    clip = existing or FilmClip(source=source, source_id=sid)
    clip.url = result.get("page_url") or result.get("url")
    clip.title = result.get("title")
    clip.description = result.get("description")
    clip.license = result.get("license")
    clip.media_type = media_type
    clip.duration_s = info.get("duration") or result.get("duration_s")
    clip.width = info.get("width") or result.get("width")
    clip.height = info.get("height") or result.get("height")
    clip.fps = info.get("fps")
    clip.keywords = _keywords(result.get("title"), result.get("description"))
    clip.path, clip.thumb_path, clip.analysis = rel, thumb_rel, {**analysis, "attribution": result.get("attribution")}
    if existing is None:
        s.add(clip)
    s.flush()
    return clip


def attach_clip(s: Session, shot: FilmShot, clip: FilmClip, start_s: float | None = None,
                end_s: float | None = None, actor: str = "user"):
    """Make the clip (or a segment of it) an imported take on the shot."""
    src = take_svc.abs_path(clip.path)
    if src is None:
        raise FootageError("clip file is missing on disk")
    data_path = src
    trimmed = None
    if clip.media_type == "video" and (start_s is not None or end_s is not None):
        a = float(start_s or 0)
        b = float(end_s) if end_s is not None else None
        rel = storage.project_rel(shot.project_id, "takes", storage.new_name(".mp4"))
        out = storage.resolve(rel)
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-i", str(src)]
        if b is not None:
            cmd += ["-t", f"{max(0.2, b - a):.3f}"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", str(out)]
        media._run(cmd, timeout=600)
        data_path = out
        trimmed = {"start_s": a, "end_s": b}
    ct = "video/mp4" if clip.media_type == "video" else "image/jpeg"
    take = take_svc.import_take(s, shot, data_path.read_bytes(), ct, data_path.name,
                                kind="footage" if clip.media_type == "video" else "image",
                                source=f"clip:{clip.source}",
                                provenance={"origin": "footage", "clip_id": clip.id, "source": clip.source,
                                            "source_id": clip.source_id, "url": clip.url, "title": clip.title,
                                            "license": clip.license, "attribution": (clip.analysis or {}).get("attribution"),
                                            "segment": trimmed}, actor=actor)
    if shot.media_strategy == "ai_video":
        shot.media_strategy = "user_footage" if clip.source == "user" else ("archival" if clip.source in ("archive", "nasa", "wikimedia") else "stock")
    s.flush()
    return take
