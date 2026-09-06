"""Multimodal evaluation backends (Phase 2, spec: "genuine vision/audio
evaluation, never faked").

Three ways to actually look at a result, in preference order:

1. the configured LLM provider, when it can see images (Anthropic image
   blocks, OpenAI-compatible image_url parts — including Grok and any
   OpenAI-shaped gateway);
2. MuAPI's `openrouter-vision` endpoint (found in the upstream
   Generative-Media-Skills schema database) when a MuAPI key is present;
3. nothing — in which case the caller is told evaluation is unavailable and
   falls back to the clearly-labelled metadata-only mode.

Video is sampled into keyframes with ffmpeg; audio is transcribed or analysed
through the audio endpoints. No backend is ever simulated: if none is
available the evaluator says so.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from .. import settings_store
from ..config import get_config
from ..llm.client import LLMError, VisionUnsupported, build_client

MAX_FRAMES = 4
MAX_IMAGE_BYTES = 4 * 1024 * 1024


class NoEvaluator(Exception):
    """No vision/audio backend is configured — report, never guess."""


# ------------------------------------------------------------- backends ---
def _llm_backend(s: Session):
    try:
        client = build_client(s)
    except Exception:
        return None
    return client if getattr(client, "supports_vision", False) else None


def _muapi_vision_available(s: Session) -> bool:
    return bool(settings_store.get(s, "muapi_api_key"))


def available_backends(s: Session) -> list[dict]:
    """What can actually judge a result right now (shown in the UI)."""
    out = []
    client = _llm_backend(s)
    if client is not None:
        out.append({"kind": "vision", "name": client.name,
                    "detail": f"{client.name} vision"})
    if _muapi_vision_available(s):
        out.append({"kind": "vision", "name": "muapi:openrouter-vision",
                    "detail": "MuAPI openrouter-vision"})
        out.append({"kind": "audio", "name": "muapi:gemini-audio-vision",
                    "detail": "MuAPI gemini-audio-vision"})
        out.append({"kind": "transcription", "name": "muapi:openai-whisper",
                    "detail": "MuAPI Whisper"})
    return out


def _muapi_vision(s: Session, system: str, user: str, images: list[bytes]) -> str:
    """openrouter-vision takes image URLs, so upload the bytes first."""
    import base64

    import httpx

    from ..generation.muapi import API, extract_text
    key = settings_store.get(s, "muapi_api_key")
    if not key:
        raise NoEvaluator("no MuAPI key")
    urls = []
    with httpx.Client(timeout=120, headers={"x-api-key": key}) as c:
        for raw in images[:MAX_FRAMES]:
            r = c.post(f"{API}/upload_file", files={"file": ("frame.png", raw, "image/png")})
            if r.status_code >= 400:
                raise LLMError(f"MuAPI upload failed (HTTP {r.status_code})")
            body = r.json() if r.content else {}
            url = body if isinstance(body, str) else (
                body.get("url") or body.get("file_url") or body.get("image_url"))
            if not url:
                raise LLMError("MuAPI upload returned no URL")
            urls.append(url)
        sub = c.post(f"{API}/openrouter-vision",
                     json={"prompt": user, "system_prompt": system, "images_list": urls},
                     headers={"x-api-key": key, "Content-Type": "application/json"})
        if sub.status_code >= 400:
            raise LLMError(f"MuAPI vision failed (HTTP {sub.status_code})")
        rid = (sub.json() or {}).get("id") or (sub.json() or {}).get("request_id")
        import time
        for _ in range(60):
            res = c.get(f"{API}/predictions/{rid}/result")
            body = res.json() if res.content else {}
            status = str(body.get("status") or "").lower()
            if status in ("succeeded", "completed", "success"):
                return extract_text(body) or ""
            if status in ("failed", "error"):
                raise LLMError(f"MuAPI vision job failed: {body.get('error')}")
            time.sleep(2)
    raise LLMError("MuAPI vision timed out")


def look(s: Session, system: str, user: str, images: list[bytes]) -> tuple[str, str]:
    """→ (raw answer, backend name). Raises NoEvaluator when nothing can see."""
    images = [i for i in images if i][:MAX_FRAMES]
    if not images:
        raise NoEvaluator("no frames to look at")
    client = _llm_backend(s)
    if client is not None:
        try:
            return client.complete_vision(system, user, images), client.name
        except VisionUnsupported:
            pass
    if _muapi_vision_available(s):
        return _muapi_vision(s, system, user, images), "muapi:openrouter-vision"
    raise NoEvaluator(
        "No vision-capable evaluator is configured — set an Anthropic/OpenAI-"
        "compatible provider in Settings → Knowledge engine, or connect MuAPI "
        "in Settings → AI providers.")


# -------------------------------------------------------------- sampling ---
def read_image(path: Path) -> bytes | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) <= MAX_IMAGE_BYTES:
        return raw
    try:                                   # downscale rather than refuse
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(raw))
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def video_frames(path: Path, count: int = 3) -> list[bytes]:
    """Evenly spaced keyframes via ffmpeg — how a video gets 'seen'."""
    ffmpeg = get_config().ffmpeg
    if not ffmpeg or not path.exists():
        return []
    duration = 0.0
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60)
        duration = float((probe.stdout or "0").strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        duration = 0.0
    frames: list[bytes] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(count):
            at = (duration * (i + 0.5) / count) if duration else i
            out = Path(tmp) / f"f{i}.png"
            try:
                subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", f"{at:.2f}",
                                "-i", str(path), "-frames:v", "1",
                                "-vf", "scale=768:-2", str(out)],
                               check=True, timeout=120, capture_output=True)
            except (OSError, subprocess.SubprocessError):
                continue
            if out.exists():
                frames.append(out.read_bytes())
    return frames


def parse_verdict(raw: str) -> dict | None:
    """Evaluators are asked for JSON; be tolerant of prose around it."""
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
