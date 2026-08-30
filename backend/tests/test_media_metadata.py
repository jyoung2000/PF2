"""Metadata parsing + compression pipeline tests (1.6, 1.7)."""
import json
import subprocess
from pathlib import Path

import httpx
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from promptforge.pipeline import media, metadata

A1111_TEXT = (
    "masterpiece, 1girl, cyberpunk city, neon rain\n"
    "Negative prompt: lowres, bad anatomy\n"
    'Steps: 28, Sampler: DPM++ 2M Karras, CFG scale: 7.5, Seed: 1234567, '
    'Size: 512x768, Model hash: abc123, Model: dreamshaper_8, '
    'Lora hashes: "detail: 456", Version: v1.7.0'
)


def make_a1111_png(path: Path, size=(64, 96)):
    img = Image.new("RGB", size, (40, 60, 80))
    info = PngInfo()
    info.add_text("parameters", A1111_TEXT)
    img.save(path, "PNG", pnginfo=info)


COMFY_PROMPT = {
    "3": {"class_type": "KSampler",
          "inputs": {"seed": 42, "steps": 20, "cfg": 8.0, "sampler_name": "euler",
                     "positive": ["6", 0], "negative": ["7", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a majestic owl, golden hour"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, jpeg artifacts"}},
}


def make_comfy_png(path: Path):
    img = Image.new("RGB", (64, 64), (10, 10, 10))
    info = PngInfo()
    info.add_text("prompt", json.dumps(COMFY_PROMPT))
    info.add_text("workflow", json.dumps({"nodes": [{"id": 3}]}))
    img.save(path, "PNG", pnginfo=info)


def make_test_video(path: Path, seconds=1, size="320x240"):
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size}:rate=12",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], check=True, capture_output=True)


def test_parse_a1111_full():
    parsed = metadata.parse_a1111(A1111_TEXT)
    assert parsed["prompt"] == "masterpiece, 1girl, cyberpunk city, neon rain"
    assert parsed["negative_prompt"] == "lowres, bad anatomy"
    p = parsed["params"]
    assert p["steps"] == 28
    assert p["sampler"] == "DPM++ 2M Karras"
    assert p["cfg_scale"] == 7.5
    assert p["seed"] == 1234567
    assert p["size"] == "512x768"
    assert p["model"] == "dreamshaper_8"
    assert p["lora_hashes"] == "detail: 456"


def test_parse_a1111_prompt_only():
    parsed = metadata.parse_a1111("just a prompt with no params")
    assert parsed["prompt"] == "just a prompt with no params"
    assert parsed["params"] == {}


def test_png_a1111_extraction(tmp_path):
    f = tmp_path / "a.png"
    make_a1111_png(f)
    parsed = metadata.extract_metadata(f)
    assert parsed["prompt"].startswith("masterpiece")
    assert parsed["params"]["seed"] == 1234567


def test_png_comfy_extraction(tmp_path):
    f = tmp_path / "c.png"
    make_comfy_png(f)
    parsed = metadata.extract_metadata(f)
    assert parsed["prompt"] == "a majestic owl, golden hour"
    assert parsed["negative_prompt"] == "blurry, jpeg artifacts"
    assert parsed["params"]["seed"] == 42
    assert parsed["params"]["sampler"] == "euler"
    assert parsed["params"]["model"] == "sd_xl_base_1.0.safetensors"
    assert parsed["params"]["workflow"] == {"nodes": [{"id": 3}]}


def test_extract_metadata_never_raises(tmp_path):
    f = tmp_path / "garbage.png"
    f.write_bytes(b"not an image at all")
    assert metadata.extract_metadata(f) == {}
    assert metadata.extract_metadata(tmp_path / "missing.png") == {}


def test_compress_image_smaller_and_valid(tmp_path):
    src = tmp_path / "big.png"
    # noisy image so PNG is reasonably large
    import random
    random.seed(1)
    img = Image.new("RGB", (2600, 1400))
    img.putdata([(random.randrange(256),) * 3 for _ in range(2600 * 1400 // 100)] * 100)
    img.save(src, "PNG")
    dest = tmp_path / "out.webp"
    res = media.compress_image(src, dest, quality=82, max_dim=2048)
    assert dest.exists()
    assert res.stored_bytes < res.original_bytes
    with Image.open(dest) as out:
        assert out.format == "WEBP"
        assert max(out.size) == 2048  # downscaled
    assert res.width == out.size[0] and res.height == out.size[1]


def test_image_thumb(tmp_path):
    src = tmp_path / "src.png"
    Image.new("RGB", (1200, 800), (200, 30, 30)).save(src, "PNG")
    dest = tmp_path / "t.webp"
    media.make_image_thumb(src, dest)
    with Image.open(dest) as t:
        assert t.format == "WEBP"
        assert max(t.size) <= media.THUMB_DIM


def test_compress_video_and_thumb(tmp_path):
    src = tmp_path / "in.mp4"
    make_test_video(src, seconds=1, size="1920x1440")  # taller than 1080
    dest = tmp_path / "out.mp4"
    res = media.compress_video(src, dest, crf=30, max_height=1080)
    assert dest.exists() and res.stored_bytes > 0
    assert res.height <= 1080 and res.height > 0
    assert res.duration_s and 0.5 < res.duration_s < 2.0
    probe = media.probe_video(dest)
    assert probe["height"] <= 1080
    thumb = tmp_path / "vt.webp"
    media.make_video_thumb(dest, thumb)
    with Image.open(thumb) as t:
        assert t.format == "WEBP"


def test_video_type_guess():
    assert media.guess_media_type("https://x/y.mp4?sig=1") == "video"
    assert media.guess_media_type("https://x/y.jpeg") == "image"
    assert media.guess_media_type("https://x/y", "video/webm") == "video"
    assert media.guess_media_type("https://x/y", "image/png") == "image"


def test_download_uses_client_and_rejects_empty(tmp_path):
    calls = {}

    def handler(request):
        calls["url"] = str(request.url)
        return httpx.Response(200, content=b"12345")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    dest = tmp_path / "f.bin"
    n = media.download("https://cdn.example/file.bin", dest, client)
    assert n == 5 and dest.read_bytes() == b"12345"

    def empty(request):
        return httpx.Response(200, content=b"")

    client2 = httpx.Client(transport=httpx.MockTransport(empty))
    with pytest.raises(media.MediaError):
        media.download("https://cdn.example/e.bin", tmp_path / "e.bin", client2)
