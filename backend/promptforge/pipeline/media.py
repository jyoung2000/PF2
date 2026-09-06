"""Media download + lossy compression + thumbnails (D19, D36).

Images → WebP (quality/image_max_dim from settings); videos → H.264 MP4
(CRF/max height from settings, audio kept); thumbnails for both (ffmpeg
frame-grab for video). Metadata extraction happens in ingest BEFORE calling
compress_* — never after."""
from __future__ import annotations

import ipaddress
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".gif"}  # gif treated as video-ish? no — see guess
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".bmp"}

THUMB_DIM = 480
THUMB_QUALITY = 70


class MediaError(Exception):
    pass


# §197: a media URL comes from scraped page content, i.e. from a stranger.
# Before PF2 fetches one it must be an ordinary web URL — not a local file,
# not a script URL, and not a cloud metadata endpoint whose only purpose
# would be to hand an attacker this machine's credentials.
_ALLOWED_SCHEMES = ("http", "https")
_METADATA_HOSTS = {
    "metadata.google.internal", "metadata.goog", "metadata",
    "instance-data", "instance-data.ec2.internal",
}
_METADATA_NETS = (
    ipaddress.ip_network("169.254.0.0/16"),     # AWS/GCP/Azure IMDS + link-local
    ipaddress.ip_network("fe80::/10"),
)
_HOST_RE = re.compile(r"^\[?([^\]]+)\]?$")


def is_downloadable(url: str) -> bool:
    """True when PF2 may fetch this URL as media.

    Private and loopback addresses are deliberately ALLOWED: a self-hosted
    PromptForge legitimately talks to its own LAN (an Ollama box, a stand-in
    server, the user's NAS). What is refused is anything that is not a web
    fetch at all, and the link-local metadata range, where an SSRF turns into
    stolen cloud credentials."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host in _METADATA_HOSTS:
        return False
    m = _HOST_RE.match(host)
    try:
        ip = ipaddress.ip_address(m.group(1) if m else host)
    except ValueError:
        return True                     # a name; DNS is not resolved here
    return not any(ip in net for net in _METADATA_NETS)


def guess_media_type(url: str, content_type: str | None = None) -> str:
    if content_type:
        if content_type.startswith("video/"):
            return "video"
        if content_type.startswith("image/") and "gif" not in content_type:
            return "image"
    path = url.split("?")[0].lower()
    ext = Path(path).suffix
    if ext in {".mp4", ".webm", ".mov", ".m4v"}:
        return "video"
    return "image"


def download(url: str, dest: Path, client: httpx.Client, max_bytes: int = 500_000_000) -> int:
    """Stream url → dest with the SAME client/session that scraped it (signed
    URLs). Returns byte count."""
    if not is_downloadable(url):
        raise MediaError(f"refusing to fetch {str(url)[:80]!r}: not a permitted media URL")
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with client.stream("GET", url, follow_redirects=True) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1 << 16):
                total += len(chunk)
                if total > max_bytes:
                    raise MediaError(f"download exceeds {max_bytes} bytes")
                f.write(chunk)
    if total == 0:
        raise MediaError("empty download")
    return total


@dataclass
class CompressResult:
    path: Path
    width: int
    height: int
    original_bytes: int
    stored_bytes: int
    duration_s: float | None = None


def compress_image(src: Path, dest: Path, quality: int = 82, max_dim: int = 2048) -> CompressResult:
    orig_bytes = src.stat().st_size
    with Image.open(src) as img:
        img.load()
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.mode or img.mode == "P" else "RGB")
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                             Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "WEBP", quality=quality, method=4)
        w, h = img.size
    return CompressResult(dest, w, h, orig_bytes, dest.stat().st_size)


def make_image_thumb(src: Path, dest: Path, dim: int = THUMB_DIM) -> None:
    with Image.open(src) as img:
        img.load()
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img.thumbnail((dim, dim), Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "WEBP", quality=THUMB_QUALITY, method=4)


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise MediaError(f"{cmd[0]} failed: {proc.stderr[-500:]}")
    return proc


def probe_video(path: Path) -> dict:
    proc = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "json", str(path),
    ], timeout=60)
    data = json.loads(proc.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    duration = None
    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        pass
    return {"width": stream.get("width"), "height": stream.get("height"),
            "duration": duration}


def compress_video(src: Path, dest: Path, crf: int = 27, max_height: int = 1080) -> CompressResult:
    orig_bytes = src.stat().st_size
    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = f"scale=trunc(iw*min(1\\,{max_height}/ih)/2)*2:trunc(ih*min(1\\,{max_height}/ih)/2)*2"
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-vf", vf,
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(dest),
    ])
    meta = probe_video(dest)
    return CompressResult(dest, meta.get("width") or 0, meta.get("height") or 0,
                          orig_bytes, dest.stat().st_size, meta.get("duration"))


def make_video_thumb(src: Path, dest: Path, dim: int = THUMB_DIM) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_png = dest.with_suffix(".frame.png")
    try:
        _run([
            "ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", str(src),
            "-frames:v", "1", str(tmp_png),
        ], timeout=120)
    except MediaError:
        # very short clips: grab first frame instead
        _run([
            "ffmpeg", "-y", "-v", "error", "-i", str(src),
            "-frames:v", "1", str(tmp_png),
        ], timeout=120)
    try:
        make_image_thumb(tmp_png, dest, dim)
    finally:
        tmp_png.unlink(missing_ok=True)
