"""Embedded generation-metadata extraction — runs BEFORE lossy compression.

Understands:
- A1111/Forge "parameters" PNG text chunk (and the same string in EXIF UserComment)
- ComfyUI "workflow"/"prompt" PNG chunks (workflow JSON preserved, prompt text +
  sampler params pulled from common node types)
Deterministic only — no LLM anywhere near this module.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

_KV_RE = re.compile(r'([A-Za-z][\w .-]*?):\s*(?:"((?:[^"\\]|\\.)*)"|([^,]*))(?:,\s*|$)')

_PARAM_KEY_MAP = {
    "steps": "steps",
    "sampler": "sampler",
    "schedule type": "scheduler",
    "cfg scale": "cfg_scale",
    "seed": "seed",
    "size": "size",
    "model": "model",
    "model hash": "model_hash",
    "denoising strength": "denoising_strength",
    "clip skip": "clip_skip",
    "vae": "vae",
    "lora hashes": "lora_hashes",
    "hires upscaler": "hires_upscaler",
}


def parse_a1111(text: str) -> dict[str, Any]:
    """Parse the A1111 'parameters' string into prompt / negative / params."""
    if not text or not text.strip():
        return {}
    lines = text.strip().split("\n")
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
    if param_idx is not None:
        raw = ", ".join(lines[param_idx:])
        for m in _KV_RE.finditer(raw):
            key = m.group(1).strip().lower()
            val = (m.group(2) if m.group(2) is not None else m.group(3) or "").strip()
            mapped = _PARAM_KEY_MAP.get(key)
            if mapped:
                params[mapped] = _maybe_number(val)
    out: dict[str, Any] = {"params": params}
    if prompt:
        out["prompt"] = prompt
    if negative:
        out["negative_prompt"] = negative
    return out


def _maybe_number(val: str) -> Any:
    try:
        return int(val)
    except ValueError:
        try:
            return float(val)
        except ValueError:
            return val


def parse_comfyui(prompt_json: str | None, workflow_json: str | None) -> dict[str, Any]:
    """Extract prompt text + sampler params from ComfyUI API-format JSON; keep
    the full workflow under params.workflow."""
    out: dict[str, Any] = {"params": {}}
    graph: dict | None = None
    if prompt_json:
        try:
            graph = json.loads(prompt_json)
        except (ValueError, TypeError):
            graph = None
    if workflow_json:
        try:
            out["params"]["workflow"] = json.loads(workflow_json)
        except (ValueError, TypeError):
            pass
    if not isinstance(graph, dict):
        return out if (out["params"]) else {}

    positives: list[str] = []
    negatives: list[str] = []
    neg_node_ids: set[str] = set()
    # KSampler nodes name their negative conditioning input
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        if "Sampler" in str(node.get("class_type", "")):
            inputs = node.get("inputs", {})
            for key in ("seed", "noise_seed"):
                if isinstance(inputs.get(key), (int, float)):
                    out["params"]["seed"] = int(inputs[key])
            if isinstance(inputs.get("steps"), (int, float)):
                out["params"]["steps"] = int(inputs["steps"])
            if isinstance(inputs.get("cfg"), (int, float)):
                out["params"]["cfg_scale"] = inputs["cfg"]
            if isinstance(inputs.get("sampler_name"), str):
                out["params"]["sampler"] = inputs["sampler_name"]
            neg = inputs.get("negative")
            if isinstance(neg, list) and neg:
                neg_node_ids.add(str(neg[0]))
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        if node.get("class_type", "").startswith("CLIPTextEncode"):
            text = node.get("inputs", {}).get("text")
            if isinstance(text, str) and text.strip():
                (negatives if str(node_id) in neg_node_ids else positives).append(text.strip())
        if node.get("class_type") == "CheckpointLoaderSimple":
            ckpt = node.get("inputs", {}).get("ckpt_name")
            if isinstance(ckpt, str):
                out["params"]["model"] = ckpt
    if positives:
        out["prompt"] = "\n".join(positives)
    if negatives:
        out["negative_prompt"] = "\n".join(negatives)
    return out


def _exif_user_comment(img: Image.Image) -> str | None:
    try:
        exif = img.getexif()
        if not exif:
            return None
        # 0x9286 UserComment lives in the Exif IFD
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


def extract_metadata(path: str | Path) -> dict[str, Any]:
    """Best-effort metadata dict {prompt?, negative_prompt?, params{}} from an
    image file. Never raises; returns {} when nothing found."""
    try:
        with Image.open(path) as img:
            info = dict(getattr(img, "text", {}) or {})
            info.update({k: v for k, v in img.info.items() if isinstance(v, str)})
            if "parameters" in info:
                parsed = parse_a1111(info["parameters"])
                if parsed:
                    return parsed
            if "prompt" in info or "workflow" in info:
                parsed = parse_comfyui(info.get("prompt"), info.get("workflow"))
                if parsed.get("prompt") or parsed.get("params"):
                    return parsed
            comment = _exif_user_comment(img)
            if comment:
                parsed = parse_a1111(comment)
                if parsed:
                    return parsed
    except Exception:
        return {}
    return {}
