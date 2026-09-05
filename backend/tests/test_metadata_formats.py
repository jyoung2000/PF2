"""Phase I2: generation-metadata parsers across formats. Raw metadata is
never discarded; unknown keys survive under params.extra / _raw_metadata."""
import json
import subprocess
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from promptforge.pipeline import metadata as md

FIX = Path(__file__).parent / "fixtures"

A1111_RICH = (
    "cinematic portrait of a sailor, <lora:filmgrain_v2:0.6> <lora:eyes:0.4:0.8>, 85mm\n"
    "Negative prompt: lowres, extra fingers\n"
    "Steps: 30, Sampler: DPM++ 2M, Schedule type: Karras, CFG scale: 5.5, Seed: 99, "
    "Size: 832x1216, Model hash: abc123, Model: juggernautXL_v9, VAE: sdxl_vae.safetensors, "
    "Denoising strength: 0.45, Clip skip: 2, Hires upscale: 2, Hires steps: 12, "
    "Hires upscaler: 4x-UltraSharp, "
    'ControlNet 0: "Module: canny, Model: control_v11p_sd15_canny [d14c016b], Weight: 0.8, '
    'Guidance Start: 0, Guidance End: 0.9", '
    'Lora hashes: "filmgrain_v2: 1a2b3c, eyes: 4d5e6f", Refiner: refinerXL, Refiner switch at: 0.8, '
    "Version: v1.9.4, ADetailer model: face_yolov8n.pt, Some Future Key: 42"
)


def png_with(tmp_path, name, **chunks):
    im = Image.new("RGB", (16, 16), (200, 100, 50))
    info = PngInfo()
    for k, v in chunks.items():
        info.add_text(k, v)
    p = tmp_path / name
    im.save(p, pnginfo=info)
    return p


def test_a1111_rich_lora_controlnet_hires_extra():
    out = md.parse_a1111(A1111_RICH)
    p = out["params"]
    assert out["prompt"].startswith("cinematic portrait")
    assert out["negative_prompt"] == "lowres, extra fingers"
    assert p["steps"] == 30 and p["scheduler"] == "Karras" and p["cfg_scale"] == 5.5
    assert p["model"] == "juggernautXL_v9" and p["vae"] == "sdxl_vae.safetensors"
    assert p["denoising_strength"] == 0.45 and p["clip_skip"] == 2
    assert p["hires"] == {"upscale": 2, "steps": 12, "upscaler": "4x-UltraSharp"}
    assert p["upscale"] == {"factor": 2, "model": "4x-UltraSharp"}
    cn = p["controlnet"][0]
    assert cn["model"].startswith("control_v11p_sd15_canny") and cn["weight"] == 0.8
    assert cn["module"] == "canny" and cn["guidance_end"] == 0.9
    loras = {l["name"]: l for l in p["loras"]}
    assert loras["filmgrain_v2"] == {"name": "filmgrain_v2", "weight": 0.6, "hash": "1a2b3c"}
    assert loras["eyes"]["clip_weight"] == 0.8 and loras["eyes"]["hash"] == "4d5e6f"
    assert p["refiner"] == "refinerXL" and p["refiner_switch_at"] == 0.8
    assert p["tool_version"] == "v1.9.4"
    # unknown keys are kept, never dropped
    assert p["extra"]["adetailer_model"] == "face_yolov8n.pt"
    assert p["extra"]["some_future_key"] == 42


def test_comfy_video_workflow_from_fixture():
    prompt_json = (FIX / "comfy_video_prompt.json").read_text()
    out = md.parse_comfyui(prompt_json, None)
    p = out["params"]
    assert out["prompt"].startswith("a red kite")
    assert out["negative_prompt"] == "blurry, static, watermark"
    assert p["model"] == "wan2.1_i2v_480p_14B_fp8.safetensors"
    assert p["seed"] == 777 and p["steps"] == 20 and p["cfg_scale"] == 6.0
    assert p["sampler"] == "uni_pc" and p["scheduler"] == "simple" and p["denoise"] == 1.0
    assert p["size"] == "832x480"
    assert p["loras"] == [{"name": "wan_orbit_v1.safetensors", "weight": 0.7, "clip_weight": None}]
    assert p["references"] == ["harbor_ref.png"]
    assert p["video"]["frames"] == 81 and p["video"]["fps"] == 16
    assert p["video"]["duration_s"] == 5.06 and p["video"]["mode"] == "image-to-video"
    assert p["video"]["model"].startswith("wan2.1")


def test_comfy_ui_graph_fallback_and_api_under_workflow_key():
    ui = {"nodes": [
        {"id": 1, "type": "CheckpointLoaderSimple", "widgets_values": ["flux1-dev.safetensors"]},
        {"id": 2, "type": "CLIPTextEncode", "widgets_values": ["golden retriever astronaut"],
         "inputs": [{"name": "clip", "link": 10}]},
        {"id": 3, "type": "CLIPTextEncode", "widgets_values": ["ugly"],
         "inputs": [{"name": "clip", "link": 11}]},
        {"id": 4, "type": "KSampler", "widgets_values": [5, "fixed", 25, 3.5, "euler", "normal", 1.0],
         "inputs": [{"name": "positive", "link": 20}, {"name": "negative", "link": 21}]},
        {"id": 5, "type": "LoraLoader", "widgets_values": ["cinematic.safetensors", 0.9, 0.9]},
        {"id": 6, "type": "VAELoader", "widgets_values": ["ae.safetensors"]},
        {"id": 7, "type": "EmptyLatentImage", "widgets_values": [1024, 1024, 1]},
        {"id": 8, "type": "ControlNetLoader", "widgets_values": ["cn_depth.safetensors"]},
        {"id": 9, "type": "UpscaleModelLoader", "widgets_values": ["4x_foolhardy.pth"]},
    ], "links": [[10, 1, 1, 2, 0, "CLIP"], [11, 1, 1, 3, 0, "CLIP"],
                 [20, 2, 0, 4, 1, "CONDITIONING"], [21, 3, 0, 4, 2, "CONDITIONING"]]}
    out = md.parse_comfyui(None, json.dumps(ui))
    p = out["params"]
    assert out["prompt"] == "golden retriever astronaut" and out["negative_prompt"] == "ugly"
    assert p["model"] == "flux1-dev.safetensors" and p["vae"] == "ae.safetensors"
    assert p["seed"] == 5 and p["steps"] == 25 and p["cfg_scale"] == 3.5
    assert p["sampler"] == "euler" and p["scheduler"] == "normal"
    assert p["size"] == "1024x1024"
    assert p["loras"][0]["name"] == "cinematic.safetensors"
    assert p["controlnet"] == [{"model": "cn_depth.safetensors"}]
    assert p["upscale"] == {"model": "4x_foolhardy.pth"}
    assert p["workflow"] == ui
    # an API graph stored under the "workflow" key still parses
    api = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.ckpt"}},
           "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "moss temple"}}}
    out2 = md.parse_comfyui(None, json.dumps(api))
    assert out2["prompt"] == "moss temple" and out2["params"]["model"] == "x.ckpt"


def test_novelai_invokeai_swarmui_fooocus(tmp_path):
    nai = png_with(tmp_path, "nai.png", Software="NovelAI", Description="1girl, rain, neon",
                   Source="NovelAI Diffusion V4 Full",
                   Comment=json.dumps({"steps": 23, "sampler": "k_euler_ancestral", "seed": 4242,
                                       "scale": 5.0, "uc": "lowres", "width": 832, "height": 1216,
                                       "noise_schedule": "karras"}))
    out = md.extract_metadata(nai)
    p = out["params"]
    assert out["prompt"] == "1girl, rain, neon" and out["negative_prompt"] == "lowres"
    assert p["model"] == "NovelAI Diffusion V4 Full" and p["seed"] == 4242
    assert p["cfg_scale"] == 5.0 and p["size"] == "832x1216" and p["metadata_format"] == "novelai"
    assert p["extra"]["noise_schedule"] == "karras"
    assert "novelai_comment" in p["_raw_metadata"]

    inv = png_with(tmp_path, "inv.png", invokeai_metadata=json.dumps({
        "positive_prompt": "brutalist library", "negative_prompt": "text",
        "seed": 12, "steps": 30, "cfg_scale": 7, "scheduler": "dpmpp_2m",
        "model": {"name": "juggernaut", "base": "sdxl"},
        "width": 1024, "height": 768,
        "loras": [{"model": {"name": "add_detail"}, "weight": 0.5}],
        "controlnets": [{"model": "canny", "weight": 0.6}]}))
    out = md.extract_metadata(inv)
    p = out["params"]
    assert out["prompt"] == "brutalist library" and p["model"] == "juggernaut"
    assert p["loras"] == [{"name": "add_detail", "weight": 0.5}]
    assert p["controlnet"][0]["model"] == "canny" and p["size"] == "1024x768"
    assert p["metadata_format"] == "invokeai"

    sw = png_with(tmp_path, "sw.png", sui_image_params=json.dumps({"sui_image_params": {
        "prompt": "desert monolith", "negativeprompt": "", "model": "flux1-schnell",
        "seed": 3, "steps": 4, "cfgscale": 1.0, "width": 1024, "height": 1024}}))
    out = md.extract_metadata(sw)
    assert out["prompt"] == "desert monolith" and out["params"]["model"] == "flux1-schnell"
    assert out["params"]["cfg_scale"] == 1.0 and out["params"]["metadata_format"] == "swarmui"

    foo = png_with(tmp_path, "foo.png", parameters=json.dumps({
        "prompt": "koi pond", "negative_prompt": "blur", "steps": 30, "sampler": "dpmpp_2m_sde_gpu",
        "scheduler": "karras", "seed": 8, "base_model": "juggernautXL_v8Rundiffusion.safetensors",
        "guidance_scale": 4.0, "resolution": "(1152, 896)",
        "loras": [["sd_xl_offset_example-lora_1.0.safetensors", 0.1]], "version": "Fooocus v2.5"}))
    out = md.extract_metadata(foo)
    p = out["params"]
    assert out["prompt"] == "koi pond" and p["model"].startswith("juggernautXL")
    assert p["size"] == "1152x896" and p["cfg_scale"] == 4.0
    assert p["loras"] == [{"name": "sd_xl_offset_example-lora_1.0.safetensors", "weight": 0.1}]
    assert p["metadata_format"] == "fooocus" and p["extra"]["version"] == "Fooocus v2.5"


def test_xmp_exif_and_unknown_chunks_preserved(tmp_path):
    xmp = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description '
           'xmp:CreatorTool="Midjourney" Iptc4xmpExt:DigitalSourceType='
           '"http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia">'
           '<dc:description><rdf:Alt><rdf:li xml:lang="x-default">a whale made of glass --ar 16:9 --v 6'
           '</rdf:li></rdf:Alt></dc:description></rdf:Description></rdf:RDF></x:xmpmeta>')
    p = png_with(tmp_path, "x.png", **{"XML:com.adobe.xmp": xmp, "MysteryTool": "opaque-blob-123"})
    out = md.extract_metadata(p)
    assert out["prompt"] == "a whale made of glass --ar 16:9 --v 6"
    assert out["params"]["tool"] == "Midjourney"
    assert out["params"]["declared_ai_generated"] is True
    assert out["params"]["metadata_format"] == "xmp"
    assert out["params"]["_raw_metadata"]["chunk_mysterytool"] == "opaque-blob-123"
    assert "xmp" in out["params"]["_raw_metadata"]

    # EXIF UserComment carrying JSON (some tools) — JPEG
    im = Image.new("RGB", (16, 16), (1, 2, 3))
    exif = Image.Exif()
    ifd = {0x9286: b"ASCII\x00\x00\x00" + json.dumps({"prompt": "exif json prompt", "seed": 5}).encode()}
    exif[0x8769] = ifd
    jp = tmp_path / "e.jpg"
    im.save(jp, exif=exif.tobytes())
    out = md.extract_metadata(jp)
    assert out["prompt"] == "exif json prompt" and out["params"]["seed"] == 5
    assert out["params"]["metadata_format"] == "exif"


def test_merge_priority_and_multi_format(tmp_path):
    p = png_with(tmp_path, "m.png",
                 parameters="a1111 prompt\nSteps: 10, Sampler: Euler, Seed: 1",
                 prompt=json.dumps({"1": {"class_type": "CheckpointLoaderSimple",
                                          "inputs": {"ckpt_name": "comfy.ckpt"}},
                                    "2": {"class_type": "CLIPTextEncode",
                                          "inputs": {"text": "comfy prompt"}}}))
    out = md.extract_metadata(p)
    assert out["prompt"] == "a1111 prompt"                 # first format wins
    assert out["params"]["model"] == "comfy.ckpt"           # params union
    assert out["params"]["metadata_format"] == "a1111"
    assert out["params"]["metadata_formats"] == ["a1111", "comfyui"]
    assert {"parameters", "comfyui_prompt"} <= set(out["params"]["_raw_metadata"])


def test_video_container_tags_and_sidecar(tmp_path):
    vid = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=0.5",
                    "-metadata", 'comment={"prompt": "orbit around a lighthouse", "model": "kling-2.1", "duration": 5}',
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vid)], check=True)
    out = md.extract_video_metadata(vid)
    assert out["prompt"] == "orbit around a lighthouse"
    assert out["params"]["model"] == "kling-2.1"
    assert out["params"]["metadata_format"] == "video_tags"
    assert out["params"]["_raw_metadata"]["video_tags"]["comment"].startswith("{")
    # sidecar wins nothing over tags but is merged + preserved
    (tmp_path / "clip.mp4.json").write_text(json.dumps({"negative_prompt": "shaky", "seed": 9}))
    out2 = md.extract_video_metadata(vid)
    assert out2["negative_prompt"] == "shaky" and out2["params"]["seed"] == 9
    assert "sidecar" in out2["params"]["_raw_metadata"]
    assert md.extract_video_metadata(tmp_path / "nope.mp4") == {}
