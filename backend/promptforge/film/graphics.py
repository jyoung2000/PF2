"""Local media makers (spec Q, C): still → video with a gentle Ken Burns
move, title cards, lower thirds and caption cards rendered with Pillow and
encoded with ffmpeg. No provider, no cost — the honest cheap medium for
titles, slides and intentionally still shots."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..pipeline import media

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]
SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "4:3": (960, 720), "1:1": (720, 720),
         "2.39:1": (1280, 536), "21:9": (1280, 548), "4:5": (720, 900)}
STYLES = {
    "title": {"bg": (10, 10, 12), "fg": (245, 245, 245), "accent": (255, 122, 24), "align": "center", "size": 0.09},
    "lower_third": {"bg": None, "fg": (255, 255, 255), "accent": (255, 122, 24), "align": "left", "size": 0.055},
    "caption": {"bg": None, "fg": (255, 255, 255), "accent": (0, 0, 0), "align": "center", "size": 0.05},
    "end_card": {"bg": (0, 0, 0), "fg": (230, 230, 230), "accent": (120, 120, 120), "align": "center", "size": 0.07},
}


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def canvas_size(aspect: str | None) -> tuple[int, int]:
    return SIZES.get(aspect or "16:9", SIZES["16:9"])


def _wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        cur = ""
        for w in words:
            trial = (cur + " " + w).strip()
            if draw.textlength(trial, font=fnt) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines or [""]


def render_card(text: str, subtitle: str | None = None, style: str = "title", aspect: str | None = "16:9",
                background: Path | None = None, accent: tuple | None = None) -> Image.Image:
    """One frame of a title card / lower third / caption / end card."""
    st = STYLES.get(style, STYLES["title"])
    w, h = canvas_size(aspect)
    if background and background.exists():
        with Image.open(background) as bg:
            img = bg.convert("RGB")
            img = img.resize((w, h))
            if style in ("title", "end_card"):
                img = img.filter(ImageFilter.GaussianBlur(4))
                overlay = Image.new("RGB", (w, h), (0, 0, 0))
                img = Image.blend(img, overlay, 0.45)
    else:
        img = Image.new("RGB", (w, h), st["bg"] or (0, 0, 0, 0))
        if st["bg"] is None:
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    size = int(h * st["size"])
    fnt = font(size)
    small = font(int(size * 0.55))
    accent = accent or st["accent"]
    lines = _wrap(draw, text, fnt, int(w * 0.8))
    line_h = int(size * 1.25)
    if style == "lower_third":
        bar_h = line_h + (int(size * 0.7) if subtitle else 0) + int(size * 0.6)
        y0 = h - bar_h - int(h * 0.08)
        draw.rectangle([0, y0, int(w * 0.62), y0 + bar_h], fill=(0, 0, 0, 200) if img.mode == "RGBA" else (0, 0, 0))
        draw.rectangle([0, y0, int(w * 0.012), y0 + bar_h], fill=accent)
        y = y0 + int(size * 0.3)
        for ln in lines[:2]:
            draw.text((int(w * 0.04), y), ln, font=fnt, fill=st["fg"])
            y += line_h
        if subtitle:
            draw.text((int(w * 0.04), y), subtitle, font=small, fill=accent)
    elif style == "caption":
        total = len(lines) * line_h + int(size * 0.6)
        y0 = h - total - int(h * 0.06)
        for ln in lines:
            tw = draw.textlength(ln, font=fnt)
            x = (w - tw) / 2
            draw.rectangle([x - size * 0.4, y0 - size * 0.15, x + tw + size * 0.4, y0 + line_h],
                           fill=(0, 0, 0, 170) if img.mode == "RGBA" else (0, 0, 0))
            draw.text((x, y0), ln, font=fnt, fill=st["fg"])
            y0 += line_h
    else:
        total = len(lines) * line_h + (int(size * 0.8) if subtitle else 0)
        y = (h - total) / 2
        for ln in lines:
            tw = draw.textlength(ln, font=fnt)
            draw.text(((w - tw) / 2, y), ln, font=fnt, fill=st["fg"])
            y += line_h
        if subtitle:
            tw = draw.textlength(subtitle, font=small)
            draw.text(((w - tw) / 2, y + size * 0.2), subtitle, font=small, fill=accent)
        draw.rectangle([w * 0.45, y + size * (0.9 if subtitle else 0.3), w * 0.55, y + size * (0.95 if subtitle else 0.35)],
                       fill=accent)
    return img.convert("RGB") if img.mode == "RGBA" and background is None and st["bg"] is not None else img


def card_video(text: str, dest: Path, duration_s: float = 3.0, subtitle: str | None = None, style: str = "title",
               aspect: str | None = "16:9", fps: int = 24, background: Path | None = None,
               fade_s: float = 0.5) -> Path:
    """Render a card as an H.264 clip with fade in/out."""
    frame = render_card(text, subtitle, style, aspect, background)
    if frame.mode == "RGBA":
        base = Image.new("RGB", frame.size, (0, 0, 0))
        base.paste(frame, mask=frame.split()[-1])
        frame = base
    png = dest.with_suffix(".card.png")
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.save(png)
    d = max(0.5, float(duration_s))
    fade = min(fade_s, d / 3)
    media._run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(fps), "-i", str(png),
                "-t", f"{d:.2f}", "-vf", f"fade=t=in:st=0:d={fade:.2f},fade=t=out:st={max(0.0, d - fade):.2f}:d={fade:.2f},format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart", str(dest)],
               timeout=300)
    png.unlink(missing_ok=True)
    return dest


def still_video(image: Path, dest: Path, duration_s: float, aspect: str | None = "16:9", fps: int = 24,
                zoom: float = 1.08, size: tuple[int, int] | None = None) -> Path:
    """Ken Burns: a still slowly zooming over the shot's duration."""
    w, h = size or canvas_size(aspect)
    d = max(0.5, float(duration_s))
    frames = int(round(d * fps))
    dest.parent.mkdir(parents=True, exist_ok=True)
    # scale to the canvas (cover), then zoompan over `frames` frames
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='min(1+({zoom - 1})*on/{max(frames, 1)},{zoom})':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},"
          f"format=yuv420p")
    media._run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(image), "-t", f"{d:.2f}", "-vf", vf,
                "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart",
                str(dest)], timeout=600)
    return dest


def has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
