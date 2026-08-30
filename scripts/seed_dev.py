"""Seed the dev database with realistic posts THROUGH the real pipeline
(download→metadata→compress→thumbs→store→FTS). Run:
  backend/.venv/bin/python scripts/seed_dev.py [count]
"""
from __future__ import annotations

import io
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from promptforge import db  # noqa: E402
from promptforge.pipeline.ingest import ingest_batch  # noqa: E402
from promptforge.scrapers.base import ScrapedPost  # noqa: E402

PROMPTS = [
    ("cinematic portrait of a lighthouse keeper, dramatic rim light, 85mm, film grain", "flux.1-dev", "civitai"),
    ("isometric cutaway of a tiny ramen shop at midnight, warm neon, ultra detailed", "FLUX.1 [dev]", "civitai"),
    ("brutalist concrete cathedral in fog, god rays, wide angle, muted palette", "SDXL 1.0", "civitai"),
    ("macro shot of a mechanical hummingbird, brass gears, shallow depth of field", "Midjourney v7", "civitai"),
    ("FPV drone dive down a neon canyon city, motion blur, rain streaks", "Kling 2.1", "civitai"),
    ("watercolor field of poppies under a storm sky, loose brushwork", "Stable Diffusion 3.5", "lexica"),
    ("character sheet of a wandering botanist, turnaround, soft studio light", "Pony Diffusion V6", "civitai"),
    ("y2k chrome wordmark on holographic background, vaporwave product shot", "flux.1-schnell", "lexica"),
    ("low-poly floating islands with waterfalls at dusk, orthographic", "SDXL Turbo", "lexica"),
    ("noir alley in the rain, silhouette under sodium light, anamorphic flare", "flux.1-dev", "civitai"),
    ("orbit shot around a glass chess set, caustics, black backdrop", "Wan 2.2", "civitai"),
    ("double exposure portrait blended with pine forest, high key", "Midjourney v6.1", "civitai"),
]

PALETTES = [(255, 106, 61), (61, 130, 255), (61, 255, 150), (240, 220, 90),
            (200, 90, 255), (90, 220, 240), (250, 250, 250), (140, 90, 60)]


def fake_image(w: int, h: int, seed: int) -> bytes:
    rnd = random.Random(seed)
    base = PALETTES[seed % len(PALETTES)]
    img = Image.new("RGB", (w, h), tuple(int(c * 0.25) for c in base))
    d = ImageDraw.Draw(img)
    for _ in range(26):
        x0, y0 = rnd.randint(-w // 2, w), rnd.randint(-h // 2, h)
        x1, y1 = x0 + rnd.randint(40, w // 2), y0 + rnd.randint(40, h // 2)
        color = tuple(min(255, max(0, c + rnd.randint(-80, 80))) for c in base)
        if rnd.random() < 0.5:
            d.ellipse([x0, y0, x1, y1], fill=color)
        else:
            d.rectangle([x0, y0, x1, y1], fill=color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def fake_video(seed: int) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "v.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=duration=2:size=640x360:rate=12",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
        ], check=True, capture_output=True)
        return out.read_bytes()


def main(count: int) -> None:
    db.init_db()
    payloads: dict[str, bytes] = {}
    posts: list[ScrapedPost] = []
    sizes = [(768, 1152), (1024, 1024), (832, 1216), (1216, 832), (640, 960), (1024, 1536)]
    for i in range(count):
        prompt, model, platform = PROMPTS[i % len(PROMPTS)]
        is_video = "FPV" in prompt or "orbit" in prompt.lower()
        url = f"https://seed.local/{i}.{'mp4' if is_video else 'png'}"
        if is_video:
            payloads[url] = fake_video(i)
        else:
            w, h = sizes[i % len(sizes)]
            payloads[url] = fake_image(w, h, i)
        posts.append(ScrapedPost(
            platform=platform,
            platform_post_id=f"seed-{i}",
            media_url=url,
            media_type="video" if is_video else "image",
            prompt=prompt,
            negative_prompt="lowres, watermark" if i % 3 == 0 else None,
            model_name=model,
            params={"seed": 1000 + i, "steps": 20 + i % 15, "cfg_scale": 3.5 + (i % 5),
                    "sampler": "Euler a"},
            author=f"artist_{i % 5}",
            source_url=f"https://example.com/post/{i}",
            nsfw=(i % 11 == 10),
        ))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payloads[str(request.url)])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    stats = ingest_batch("seed", posts, client)
    print(f"seeded: {stats.new} new, {stats.duplicates} dupes, {stats.errors} errors")
    if stats.error_messages:
        print("\n".join(stats.error_messages))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 12)
