"""Embedded generation-metadata extraction — runs BEFORE lossy compression.

Deterministic only (no LLM anywhere near this module). Understands, and
merges in this priority:

  A1111/Forge "parameters" (PNG text or EXIF UserComment; also Fooocus' JSON
  flavour) → ComfyUI "prompt"/"workflow" (API graph + UI graph, incl. LoRA /
  ControlNet / VAE / upscale / video nodes) → NovelAI (Description/Comment/
  Source) → InvokeAI (invokeai_metadata) → SwarmUI (sui_image_params) →
  EXIF/XMP (dc:description, creator tool, IPTC AI source flag) → video
  container tags via ffprobe (comment/description JSON, sidecar .json/.txt).

Unknown metadata is never discarded: every recognised chunk's raw text and
every unrecognised text chunk land under params["_raw_metadata"] (capped per
value) so future parser upgrades can re-read stored posts."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

RAW_CAP = 64_000               # bytes per raw value kept
_KV_RE = re.compile(r'([A-Za-z][\w .\-/]*?):\s*(?:"((?:[^"\\]|\\.)*)"|([^,]*))(?:,\s*|$)')
_LORA_TAG_RE = re.compile(r"<lora:([^:>]+)(?::([\d.\-]+))?(?::([\d.\-]+))?>", re.I)
_CN_KEY_RE = re.compile(r"^controlnet\s*\d*$", re.I)
_VIDEO_MODEL_HINTS = ("wan", "hunyuan", "ltx", "cogvideo", "mochi", "svd",
                      "animatediff", "kling", "seedance", "veo", "sora")

_PARAM_KEY_MAP = {
    "steps": "steps",
    "sampler": "sampler",
    "schedule type": "scheduler",
    "scheduler": "scheduler",
    "cfg scale": "cfg_scale",
    "distilled cfg scale": "guidance",
    "seed": "seed",
    "size": "size",
    "model": "model",
    "model hash": "model_hash",
    "denoising strength": "denoising_strength",
    "clip skip": "clip_skip",
    "vae": "vae",
    "vae hash": "vae_hash",
    "lora hashes": "lora_hashes",
    "hires upscaler": "hires_upscaler",
    "hires upscale": "hires_upscale",
    "hires steps": "hires_steps",
    "hires resize": "hires_resize",
    "version": "tool_version",
    "refiner": "refiner",
    "refiner switch at": "refiner_switch_at",
    "ensd": "ensd",
    "eta": "eta",
    "face restoration": "face_restoration",
    "ti hashes": "ti_hashes",
    "tiled diffusion": "tiled_diffusion",
    "module": "module",
}


def _maybe_number(val: str) -> Any:
    try:
        return int(val)
    except ValueError:
        try:
            return float(val)
        except ValueError:
            return val


def _cap(text: Any) -> Any:
    if isinstance(text, str) and len(text) > RAW_CAP:
        return text[:RAW_CAP] + "…[truncated]"
    return text


def _slug(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


# ------------------------------------------------------------------ A1111 ----
def _parse_controlnet_value(val: str) -> dict:
    """'Model: control_v11p_sd15_canny [abc], Weight: 1, Guidance Start: 0' →
    structured dict (the value is itself a k: v list, quoted in the source)."""
    out: dict[str, Any] = {}
    for m in _KV_RE.finditer(val):
        k = _slug(m.group(1))
        v = (m.group(2) if m.group(2) is not None else m.group(3) or "").strip()
        if k and v:
            out[k] = _maybe_number(v)
    return out or {"raw": val}


def _loras_from_prompt(prompt: str) -> list[dict]:
    loras = []
    for name, w_model, w_clip in _LORA_TAG_RE.findall(prompt or ""):
        entry: dict[str, Any] = {"name": name}
        if w_model:
            entry["weight"] = _maybe_number(w_model)
        if w_clip:
            entry["clip_weight"] = _maybe_number(w_clip)
        loras.append(entry)
    return loras


def parse_a1111(text: str) -> dict[str, Any]:
    """Parse the A1111/Forge 'parameters' string into prompt / negative /
    params. Known keys map to canonical names, LoRA tags and 'Lora hashes'
    become params.loras, 'ControlNet N' entries become params.controlnet,
    hires/upscale settings group under params.hires, and every other key is
    kept under params.extra."""
    if not text or not text.strip():
        return {}
    stripped = text.strip()
    if stripped.startswith("{"):           # Fooocus & friends write JSON here
        parsed = parse_json_params(stripped, fmt="fooocus")
        if parsed:
            return parsed
    lines = stripped.split("\n")
    neg_idx = None
    param_idx = None
    for i, line in enumerate(lines):
        if neg_idx is None and line.startswith("Negative prompt:"):
            neg_idx = i
        if re.match(r"^Steps: \d+", line.strip()):
            param_idx = i
    prompt_end = neg_idx if neg_idx is not None else (
        param_idx if param_idx is not None else len(lines))
    prompt = "\n".join(lines[:prompt_end]).strip()
    negative = None
    if neg_idx is not None:
        neg_end = param_idx if param_idx is not None else len(lines)
        negative = "\n".join(lines[neg_idx:neg_end]).strip()
        negative = negative[len("Negative prompt:"):].strip()
    params: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    controlnet: list[dict] = []
    hires: dict[str, Any] = {}
    if param_idx is not None:
        raw = ", ".join(lines[param_idx:])
        for m in _KV_RE.finditer(raw):
            key = m.group(1).strip()
            val = (m.group(2) if m.group(2) is not None else m.group(3) or "").strip()
            if not val:
                continue
            low = key.lower()
            mapped = _PARAM_KEY_MAP.get(low)
            if _CN_KEY_RE.match(low):
                controlnet.append({"slot": low, **_parse_controlnet_value(val)})
            elif mapped and mapped.startswith("hires_"):
                hires[mapped[len("hires_"):]] = _maybe_number(val)
            elif mapped:
                params[mapped] = _maybe_number(val)
            else:
                extra[_slug(key)] = _maybe_number(val)
    loras = _loras_from_prompt(prompt)
    if isinstance(params.get("lora_hashes"), str):
        hashes = _parse_controlnet_value(params["lora_hashes"])
        known = {l["name"] for l in loras}
        for name, h in hashes.items():
            if name == "raw":
                continue
            entry = next((l for l in loras if _slug(l["name"]) == name), None)
            if entry is None and name not in known:
                entry = {"name": name}
                loras.append(entry)
            if entry is not None:
                entry["hash"] = h
    if loras:
        params["loras"] = loras
    if controlnet:
        params["controlnet"] = controlnet
    if hires:
        params["hires"] = hires
        params["upscale"] = {"factor": hires.get("upscale"), "model": hires.get("upscaler")}
    if extra:
        params["extra"] = extra
    out: dict[str, Any] = {"params": params}
    if prompt:
        out["prompt"] = prompt
    if negative:
        out["negative_prompt"] = negative
    return out


# ----------------------------------------------------- JSON flavours ----
_JSON_KEYS = {
    "prompt": ("prompt", "positive_prompt", "full_prompt", "positive"),
    "negative_prompt": ("negative_prompt", "negative", "uc"),
    "seed": ("seed",),
    "steps": ("steps",),
    "cfg_scale": ("cfg_scale", "guidance_scale", "scale", "cfg", "cfgscale"),
    "sampler": ("sampler", "sampler_name"),
    "scheduler": ("scheduler", "schedule"),
    "model": ("base_model", "model", "checkpoint", "base_model_name", "model_name"),
    "vae": ("vae",),
    "denoising_strength": ("denoise", "denoising_strength", "strength"),
    "clip_skip": ("clip_skip",),
    "width": ("width",),
    "height": ("height",),
}


def parse_json_params(text: str, fmt: str = "json") -> dict[str, Any]:
    """Generic JSON metadata (Fooocus / SwarmUI / InvokeAI / NovaAI comment…)
    → canonical dict. Unknown keys preserved under params.extra."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("sui_image_params"), dict):
        data = data["sui_image_params"]
        fmt = "swarmui"
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {"params": {}}
    params = out["params"]
    used: set[str] = set()
    for canon, keys in _JSON_KEYS.items():
        for k in keys:
            if k in data and data[k] not in (None, ""):
                val = data[k]
                if isinstance(val, dict) and canon == "model":
                    val = val.get("name") or val.get("model_name") or json.dumps(val)
                if canon in ("prompt", "negative_prompt"):
                    out[canon] = str(val)
                else:
                    params[canon] = val
                used.add(k)
                break
    if "width" in params and "height" in params:
        params["size"] = f"{params.pop('width')}x{params.pop('height')}"
    elif isinstance(data.get("resolution"), str):
        params["size"] = data["resolution"].strip("()").replace(", ", "x").replace(",", "x")
        used.add("resolution")
    loras = data.get("loras") or data.get("lora")
    if isinstance(loras, list) and loras:
        norm = []
        for entry in loras:
            if isinstance(entry, dict):
                norm.append({"name": entry.get("name") or entry.get("model", {}).get("name")
                             if isinstance(entry.get("model"), dict) else entry.get("name") or entry.get("lora"),
                             "weight": entry.get("weight", entry.get("strength"))})
            elif isinstance(entry, (list, tuple)) and entry:
                norm.append({"name": entry[0], "weight": entry[1] if len(entry) > 1 else None})
            elif isinstance(entry, str):
                norm.append({"name": entry})
        params["loras"] = [n for n in norm if n.get("name")]
        used.add("loras")
        used.add("lora")
    for key in ("controlnets", "controlnet"):
        if isinstance(data.get(key), list) and data[key]:
            params["controlnet"] = data[key]
            used.add(key)
    extra = {_slug(k): (v if isinstance(v, (int, float, str, bool)) else _cap(json.dumps(v)))
             for k, v in data.items() if k not in used}
    if extra:
        params["extra"] = extra
    return out


def parse_novelai(info: dict) -> dict[str, Any]:
    """NovelAI: Description = prompt, Comment = JSON settings (uc = negative),
    Source = model string."""
    comment = parse_json_params(info.get("Comment") or "{}", fmt="novelai")
    out: dict[str, Any] = comment or {"params": {}}
    if info.get("Description"):
        out["prompt"] = str(info["Description"]).strip()
    if info.get("Source"):
        out["params"]["model"] = str(info["Source"])
    return out


# ---------------------------------------------------------------- ComfyUI ----
_SAMPLER_TYPES = ("KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced")
_CKPT_TYPES = ("CheckpointLoaderSimple", "CheckpointLoader", "UNETLoader", "UnetLoaderGGUF",
               "ImageOnlyCheckpointLoader", "DiffusionModelLoader", "WanVideoModelLoader",
               "HunyuanVideoModelLoader", "LTXVLoader")
_LATENT_TYPES = ("EmptyLatentImage", "EmptySD3LatentImage", "EmptyHunyuanLatentVideo",
                 "EmptyLTXVLatentVideo", "EmptyMochiLatentVideo", "EmptyCosmosLatentVideo",
                 "WanImageToVideo", "WanFunControlToVideo", "CogVideoImageEncode")
_VIDEO_OUT_TYPES = ("VHS_VideoCombine", "CreateVideo", "SaveAnimatedWEBP", "SaveWEBM",
                    "SaveVideo")
_WIDGET_LAYOUTS = {   # UI-graph fallback: positional widgets_values
    "KSampler": ("seed", "_control", "steps", "cfg", "sampler_name", "scheduler", "denoise"),
    "KSamplerAdvanced": ("_add_noise", "noise_seed", "_control", "steps", "cfg", "sampler_name",
                         "scheduler", "_start", "_end", "_return"),
    "CheckpointLoaderSimple": ("ckpt_name",),
    "UNETLoader": ("unet_name", "_dtype"),
    "LoraLoader": ("lora_name", "strength_model", "strength_clip"),
    "LoraLoaderModelOnly": ("lora_name", "strength_model"),
    "VAELoader": ("vae_name",),
    "CLIPTextEncode": ("text",),
    "EmptyLatentImage": ("width", "height", "batch_size"),
    "ControlNetLoader": ("control_net_name",),
    "UpscaleModelLoader": ("model_name",),
    "LoadImage": ("image",),
}


def _normalize_ui_graph(workflow: dict) -> dict | None:
    """ComfyUI UI-format workflow ({nodes:[{id,type,widgets_values,...}],
    links:[...]}) → API-shaped {id: {class_type, inputs}} using known widget
    layouts so the same extractor runs. Link resolution: links[] rows are
    [link_id, from_node, from_slot, to_node, to_slot, type]."""
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return None
    link_src: dict[int, int] = {}
    for row in workflow.get("links") or []:
        if isinstance(row, list) and len(row) >= 4:
            link_src[row[0]] = row[1]
    graph: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ctype = node.get("type", "")
        inputs: dict[str, Any] = {}
        layout = _WIDGET_LAYOUTS.get(ctype)
        values = node.get("widgets_values") or []
        if layout:
            for key, val in zip(layout, values):
                if not key.startswith("_"):
                    inputs[key] = val
        for inp in node.get("inputs") or []:
            if isinstance(inp, dict) and inp.get("link") in link_src:
                inputs[inp.get("name", "")] = [str(link_src[inp["link"]]), 0]
        graph[str(node.get("id"))] = {"class_type": ctype, "inputs": inputs}
    return graph


def _extract_from_graph(graph: dict, out: dict[str, Any]) -> None:
    params = out["params"]
    positives: list[str] = []
    negatives: list[str] = []
    neg_ids: set[str] = set()
    pos_ids: set[str] = set()
    loras: list[dict] = []
    controlnet: list[dict] = []
    references: list[str] = []
    video: dict[str, Any] = {}

    for node in graph.values():
        if not isinstance(node, dict):
            continue
        ctype = str(node.get("class_type", ""))
        inputs = node.get("inputs") or {}
        if any(ctype.startswith(t) for t in _SAMPLER_TYPES) or "Sampler" in ctype:
            for key in ("seed", "noise_seed"):
                if isinstance(inputs.get(key), (int, float)):
                    params["seed"] = int(inputs[key])
            for src, dst in (("steps", "steps"), ("cfg", "cfg_scale"),
                             ("sampler_name", "sampler"), ("scheduler", "scheduler"),
                             ("denoise", "denoise")):
                if isinstance(inputs.get(src), (int, float, str)):
                    params[dst] = inputs[src]
            for key, bucket in (("negative", neg_ids), ("positive", pos_ids)):
                ref = inputs.get(key)
                if isinstance(ref, list) and ref:
                    bucket.add(str(ref[0]))
        if ctype == "FluxGuidance" and isinstance(inputs.get("guidance"), (int, float)):
            params["guidance"] = inputs["guidance"]
        if ctype.startswith("ModelSampling") and isinstance(inputs.get("shift"), (int, float)):
            params["shift"] = inputs["shift"]

    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        ctype = str(node.get("class_type", ""))
        inputs = node.get("inputs") or {}
        if ctype.startswith("CLIPTextEncode"):
            texts = [inputs.get(k) for k in ("text", "clip_l", "t5xxl", "text_g", "text_l")]
            text = "\n".join(dict.fromkeys(t.strip() for t in texts if isinstance(t, str) and t.strip()))
            if text:
                (negatives if str(node_id) in neg_ids else positives).append(text)
        elif ctype in _CKPT_TYPES:
            for key in ("ckpt_name", "unet_name", "model", "model_name"):
                if isinstance(inputs.get(key), str):
                    params["model"] = inputs[key]
                    break
        elif ctype.startswith("LoraLoader") or ctype in ("LoraLoaderModelOnly", "LoRALoader"):
            if isinstance(inputs.get("lora_name"), str):
                loras.append({"name": inputs["lora_name"],
                              "weight": inputs.get("strength_model"),
                              "clip_weight": inputs.get("strength_clip")})
        elif ctype.startswith("ControlNet"):
            if isinstance(inputs.get("control_net_name"), str):
                controlnet.append({"model": inputs["control_net_name"]})
            elif "Apply" in ctype and isinstance(inputs.get("strength"), (int, float)):
                controlnet.append({"strength": inputs["strength"],
                                   "start": inputs.get("start_percent"),
                                   "end": inputs.get("end_percent")})
        elif ctype == "VAELoader" and isinstance(inputs.get("vae_name"), str):
            params["vae"] = inputs["vae_name"]
        elif ctype in _LATENT_TYPES or ctype.endswith("ToVideo"):
            w, h = inputs.get("width"), inputs.get("height")
            if isinstance(w, (int, float)) and isinstance(h, (int, float)):
                params["size"] = f"{int(w)}x{int(h)}"
            for key in ("length", "num_frames", "frames"):
                if isinstance(inputs.get(key), (int, float)):
                    video["frames"] = int(inputs[key])
            if ctype.endswith("ToVideo") or "Video" in ctype:
                video.setdefault("mode", "image-to-video" if "Image" in ctype else "text-to-video")
        elif ctype in ("UpscaleModelLoader",) and isinstance(inputs.get("model_name"), str):
            params.setdefault("upscale", {})["model"] = inputs["model_name"]
        elif ctype in ("LatentUpscaleBy", "ImageScaleBy") and isinstance(inputs.get("scale_by"), (int, float)):
            params.setdefault("upscale", {})["factor"] = inputs["scale_by"]
        elif ctype in ("LoadImage", "LoadImageMask") and isinstance(inputs.get("image"), str):
            references.append(inputs["image"])
        elif ctype in _VIDEO_OUT_TYPES:
            for key in ("frame_rate", "fps"):
                if isinstance(inputs.get(key), (int, float)):
                    video["fps"] = inputs[key]
    model = str(params.get("model", "")).lower()
    if any(h in model for h in _VIDEO_MODEL_HINTS) or video:
        if params.get("model"):
            video.setdefault("model", params["model"])
    if video:
        if video.get("frames") and video.get("fps"):
            video["duration_s"] = round(video["frames"] / video["fps"], 2)
        params["video"] = video
    if positives:
        out["prompt"] = "\n".join(positives)
    if negatives:
        out["negative_prompt"] = "\n".join(negatives)
    if loras:
        params["loras"] = loras
    if controlnet:
        params["controlnet"] = controlnet
    if references:
        params["references"] = references
        if video and "mode" not in video:
            video["mode"] = "image-to-video"


def parse_comfyui(prompt_json: str | None, workflow_json: str | None) -> dict[str, Any]:
    """Extract prompt text + generation params from ComfyUI JSON (API-format
    'prompt' graph preferred; UI-format 'workflow' parsed as fallback). The
    full workflow is preserved under params.workflow."""
    out: dict[str, Any] = {"params": {}}
    graph: dict | None = None
    workflow: dict | None = None
    if prompt_json:
        try:
            graph = json.loads(prompt_json)
        except (ValueError, TypeError):
            graph = None
    if workflow_json:
        try:
            workflow = json.loads(workflow_json)
            out["params"]["workflow"] = workflow
        except (ValueError, TypeError):
            workflow = None
    if not isinstance(graph, dict) and isinstance(workflow, dict):
        graph = _normalize_ui_graph(workflow)
        if graph is None and all(isinstance(v, dict) and "class_type" in v
                                 for v in workflow.values()):
            graph = workflow   # API graph stored under the "workflow" key
    if isinstance(graph, dict):
        _extract_from_graph(graph, out)
    if not out.get("prompt") and not out["params"]:
        return {}
    return out


# ----------------------------------------------------------------- EXIF/XMP --
def _exif_user_comment(img: Image.Image) -> str | None:
    try:
        exif = img.getexif()
        if not exif:
            return None
        try:
            ifd = exif.get_ifd(0x8769)
            raw = ifd.get(0x9286)
        except Exception:
            raw = exif.get(0x9286)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            for codec_prefix, codec in ((b"UNICODE\x00", "utf-16-be"), (b"ASCII\x00\x00\x00", "ascii")):
                if raw.startswith(codec_prefix):
                    return raw[len(codec_prefix):].decode(codec, "ignore").strip("\x00")
            return raw.decode("utf-8", "ignore").strip("\x00")
        return str(raw)
    except Exception:
        return None


def _exif_description(img: Image.Image) -> str | None:
    try:
        exif = img.getexif()
        val = exif.get(0x010E) if exif else None   # ImageDescription
        return str(val).strip() if val else None
    except Exception:
        return None


_XMP_DESC_RE = re.compile(r"<dc:description>.*?<rdf:li[^>]*>(.*?)</rdf:li>", re.S)
_XMP_TOOL_RE = re.compile(r'xmp:CreatorTool(?:="|>)([^"<]+)', re.S)
_XMP_AI_RE = re.compile(r"trainedAlgorithmicMedia|compositeWithTrainedAlgorithmicMedia", re.I)


def parse_xmp(xmp: str) -> dict[str, Any]:
    out: dict[str, Any] = {"params": {}}
    m = _XMP_DESC_RE.search(xmp)
    if m:
        desc = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if desc:
            out["prompt"] = desc
    m = _XMP_TOOL_RE.search(xmp)
    if m:
        out["params"]["tool"] = m.group(1).strip()
    if _XMP_AI_RE.search(xmp):
        out["params"]["declared_ai_generated"] = True   # IPTC DigitalSourceType
    return out


# ------------------------------------------------------------------ merge ----
def _tag(parsed: dict[str, Any] | None, fmt: str, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """Label a parser result with its format and keep the raw chunk(s)."""
    if not parsed:
        return {}
    params = parsed.setdefault("params", {})
    params["metadata_format"] = fmt
    if raw:
        params.setdefault("_raw_metadata", {}).update({k: _cap(v) for k, v in raw.items()})
    return parsed


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """First-found prompt/negative win; params merge without clobbering;
    raw metadata unions."""
    if not extra:
        return base
    if not base:
        return extra
    for key in ("prompt", "negative_prompt"):
        if not base.get(key) and extra.get(key):
            base[key] = extra[key]
    bp, ep = base.setdefault("params", {}), extra.get("params") or {}
    raw = {**(ep.get("_raw_metadata") or {}), **(bp.get("_raw_metadata") or {})}
    for k, v in ep.items():
        if k == "_raw_metadata":
            continue
        if k == "metadata_format":
            bp.setdefault("metadata_formats", [bp.get("metadata_format")])
            if v not in bp["metadata_formats"]:
                bp["metadata_formats"].append(v)
            continue
        bp.setdefault(k, v)
    if raw:
        bp["_raw_metadata"] = raw
    return base


_KNOWN_CHUNKS = {"parameters", "prompt", "workflow", "Description", "Comment", "Source",
                 "Software", "Title", "invokeai_metadata", "sd-metadata", "invokeai_graph",
                 "sui_image_params", "XML:com.adobe.xmp", "dpi", "icc_profile", "gamma",
                 "srgb", "chromaticity", "exif", "transparency", "aspect", "interlace",
                 "background", "photoshop", "jfif", "jfif_version", "jfif_density",
                 "jfif_unit", "adobe", "adobe_transform", "progression", "progressive",
                 "loop", "duration", "extension", "alpha", "xmp"}


def extract_metadata(path: str | Path) -> dict[str, Any]:
    """Best-effort metadata dict {prompt?, negative_prompt?, params{}} from an
    image file, merged across every embedded format found. Never raises;
    returns {} when nothing is found."""
    try:
        with Image.open(path) as img:
            info = dict(getattr(img, "text", {}) or {})
            info.update({k: v for k, v in img.info.items() if isinstance(v, (str, bytes))})
            result: dict[str, Any] = {}
            if isinstance(info.get("parameters"), str):
                fmt = "fooocus" if info["parameters"].lstrip().startswith("{") else "a1111"
                result = _merge(result, _tag(parse_a1111(info["parameters"]), fmt,
                                             {"parameters": info["parameters"]}))
            if info.get("prompt") or info.get("workflow"):
                pj = info.get("prompt") if isinstance(info.get("prompt"), str) else None
                wj = info.get("workflow") if isinstance(info.get("workflow"), str) else None
                raw = {k: v for k, v in (("comfyui_prompt", pj), ("comfyui_workflow", wj)) if v}
                result = _merge(result, _tag(parse_comfyui(pj, wj), "comfyui", raw))
            if str(info.get("Software", "")).startswith("NovelAI") or (
                    info.get("Description") and info.get("Comment")):
                raw = {f"novelai_{k.lower()}": str(info[k]) for k in
                       ("Description", "Comment", "Source", "Software", "Title") if info.get(k)}
                result = _merge(result, _tag(parse_novelai(info), "novelai", raw))
            if isinstance(info.get("invokeai_metadata"), str):
                result = _merge(result, _tag(parse_json_params(info["invokeai_metadata"]), "invokeai",
                                             {"invokeai_metadata": info["invokeai_metadata"]}))
            if isinstance(info.get("sui_image_params"), str):
                result = _merge(result, _tag(parse_json_params(info["sui_image_params"]), "swarmui",
                                             {"sui_image_params": info["sui_image_params"]}))
            comment = _exif_user_comment(img)
            if comment:
                parsed = parse_a1111(comment) if not comment.lstrip().startswith("{") \
                    else parse_json_params(comment)
                result = _merge(result, _tag(parsed, "exif", {"exif_usercomment": comment}))
            desc = _exif_description(img)
            if desc and not result.get("prompt") and len(desc) > 12:
                result = _merge(result, _tag({"prompt": desc, "params": {}}, "exif",
                                             {"exif_description": desc}))
            xmp = info.get("XML:com.adobe.xmp") or info.get("xmp")
            if isinstance(xmp, bytes):
                xmp = xmp.decode("utf-8", "ignore")
            if isinstance(xmp, str) and "<x:xmpmeta" in xmp:
                result = _merge(result, _tag(parse_xmp(xmp), "xmp", {"xmp": xmp}))
            # never discard unknown text chunks
            unknown = {k: _cap(v if isinstance(v, str) else v.decode("utf-8", "ignore"))
                       for k, v in info.items()
                       if k not in _KNOWN_CHUNKS and isinstance(v, (str, bytes)) and len(v) > 2}
            if unknown:
                result.setdefault("params", {}).setdefault("_raw_metadata", {}).update(
                    {f"chunk_{_slug(k)}": v for k, v in unknown.items()})
            if result and not result.get("params"):
                result["params"] = {}
            return result
    except Exception:
        return {}


def extract_video_metadata(path: str | Path) -> dict[str, Any]:
    """Container tags via ffprobe (comment/description/title/encoder) — JSON
    values are parsed as generation metadata — plus a sidecar .json/.txt next
    to the file when present. Never raises."""
    import subprocess
    result: dict[str, Any] = {}
    tags: dict[str, str] = {}
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags",
             "-print_format", "json", str(path)],
            capture_output=True, text=True, timeout=60)
        data = json.loads(proc.stdout or "{}")
        raw_tags = (data.get("format") or {}).get("tags") or {}
        tags = {str(k).lower(): str(v) for k, v in raw_tags.items()}
    except Exception:
        tags = {}
    for key in ("comment", "description", "title"):
        val = tags.get(key)
        if not val:
            continue
        parsed = parse_json_params(val) if val.lstrip().startswith("{") \
            else (parse_a1111(val) if "Steps:" in val or "Negative prompt:" in val
                  else {"prompt": val, "params": {}} if len(val) > 12 else {})
        if parsed:
            result = _merge(result, _tag(parsed, "video_tags", {f"video_{key}": val}))
    if tags:
        result.setdefault("params", {}).setdefault("_raw_metadata", {})["video_tags"] = \
            {k: _cap(v) for k, v in tags.items()}
        if tags.get("encoder"):
            result["params"]["tool"] = tags["encoder"]
    p = Path(path)
    for sidecar in (p.with_suffix(p.suffix + ".json"), p.with_suffix(".json"), p.with_suffix(".txt")):
        if sidecar.is_file() and sidecar != p:
            try:
                text = sidecar.read_text(errors="ignore")
            except OSError:
                continue
            parsed = parse_json_params(text) if text.lstrip().startswith("{") else parse_a1111(text)
            if parsed:
                result = _merge(result, _tag(parsed, "sidecar", {"sidecar": text}))
            break
    return result
