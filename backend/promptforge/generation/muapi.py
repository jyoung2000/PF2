"""MuAPI adapter (Phase 2, upstream audit).

Five of the reference "API" repositories (Image-Enhancement-API,
Video-Utilities-API, Speech-to-Text-API, Text-to-Speech-API, AI-3D-Model-API)
and Seedance-2.5-API are thin clients over ONE service with an identical
contract, verified in their `examples/quickstart.py` and in
`Seedance-2.5-API/seedance_api.py`:

    POST {base}/{endpoint}                 → {id|request_id|prediction_id}
    GET  {base}/predictions/{id}/result    → {status, …output fields}
    header: x-api-key

That is the same submit/poll shape as our other adapters, so this single file
gives PromptForge real execution for upscaling, background removal, speech
synthesis, transcription, 3D and video→audio — instead of honest placeholders.

MuAPI is one provider among several: nothing requires it, every capability it
serves stays unsupported-with-a-reason when its key is absent, and the routing
policy never prefers it implicitly.

Per-endpoint field names come from the endpoints' published schemas; the
adapter maps our provider-neutral params onto them via ENDPOINT_FIELDS, so a
new endpoint is a catalog entry, not code.
"""
from __future__ import annotations

import httpx

from .base import (GenerationProvider, ProviderError, apply_image_inputs,
                   build_common_payload, image_inputs)

API = "https://api.muapi.ai/api/v1"
PROBE_ID = "00000000-0000-0000-0000-000000000000"

# Terminal states, from the upstream pollers (they disagree slightly, so accept
# every spelling all of them accept).
DONE = {"succeeded", "completed", "success"}
FAILED = {"failed", "error", "cancelled", "canceled"}
QUEUED = {"", "queued", "pending", "starting", "in_queue", "created", "submitted"}

# Endpoints whose primary media input is not `image_url`. Anything absent uses
# the default map below.
ENDPOINT_FIELDS: dict[str, dict] = {
    "openai-whisper": {"audio": "audio_url", "text": None},
    "gemini-audio-vision": {"audio": "audio_url", "text": "prompt"},
    "mmaudio-v2-video-to-video": {"video": "video_url", "text": "prompt"},
    "ai-video-upscaler": {"video": "video_url"},
    "ai-video-upscaler-pro": {"video": "video_url"},
    "topaz-video-upscale": {"video": "video_url"},
    "video-background-remover": {"video": "video_url"},
}
DEFAULT_FIELDS = {"image": "image_url", "references": "images_list",
                  "end_image": "last_image", "text": "prompt"}

# Params we forward verbatim when present (names as published per endpoint).
PASSTHROUGH = ("voice_id", "speed", "volume", "pitch", "emotion", "language",
               "response_format", "resolution", "upscale_factor", "duration",
               "copy_audio", "aspect_ratio", "system_prompt", "model",
               "dialogue", "images_list", "num_images")


def extract_output_url(body: dict) -> str | None:
    """MuAPI result shapes vary per endpoint — check the documented keys in the
    same defensive order the upstream clients use."""
    for key in ("video_url", "audio_url", "image_url", "model_url", "url",
                "output_url", "result_url"):
        v = body.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v
    output = body.get("outputs") or body.get("output") or body.get("result") or {}
    if isinstance(output, dict):
        for key in ("video_url", "audio_url", "image_url", "model_url", "url",
                    "output_url", "glb_url", "pbr_model"):
            v = output.get(key)
            if isinstance(v, str) and v.startswith("http"):
                return v
    if isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, str) and first.startswith("http"):
            return first
        if isinstance(first, dict):
            for key in ("url", "image_url", "video_url", "audio_url"):
                v = first.get(key)
                if isinstance(v, str) and v.startswith("http"):
                    return v
    return None


def extract_text(body: dict) -> str | None:
    """Transcription / audio-analysis endpoints return text, not a file."""
    for key in ("text", "transcript", "transcription", "answer", "response"):
        v = body.get(key)
        if isinstance(v, str) and v.strip():
            return v
    output = body.get("outputs") or body.get("output") or body.get("result") or {}
    if isinstance(output, dict):
        for key in ("text", "transcript", "answer", "response"):
            v = output.get(key)
            if isinstance(v, str) and v.strip():
                return v
    if isinstance(output, str) and output.strip() and not output.startswith("http"):
        return output
    return None


class MuAPIProvider(GenerationProvider):
    name = "muapi"
    label = "MuAPI"
    key_setting = "muapi_api_key"
    key_url = "https://muapi.ai/access-keys"

    def auth_headers(self, key: str) -> dict:
        return {"x-api-key": key, "Content-Type": "application/json"}

    def test_connection(self, key: str) -> dict:
        """Result GET on a nonexistent id — 401/403 ⇒ bad key, 404 ⇒ key OK.
        Never triggers a paid generation (D10)."""
        if not key:
            return {"ok": False, "detail": "No MuAPI key — create one at "
                                           f"{self.key_url} and paste it here."}
        with self._client(key) as c:
            try:
                resp = c.get(f"{API}/predictions/{PROBE_ID}/result")
            except httpx.HTTPError as e:
                return {"ok": False, "detail": f"Can't reach MuAPI ({type(e).__name__})."}
        if resp.status_code in (401, 403):
            return {"ok": False, "detail": "MuAPI rejected the key (401) — "
                                           f"regenerate it at {self.key_url}."}
        if resp.status_code >= 500:
            return {"ok": False, "detail": f"MuAPI is unavailable (HTTP {resp.status_code}) — "
                                           "try again shortly."}
        return {"ok": True, "detail": "MuAPI key accepted"}

    def _fields(self, model_id: str) -> dict:
        return {**DEFAULT_FIELDS, **ENDPOINT_FIELDS.get(model_id, {})}

    def build_payload(self, model_id: str, prompt: str, negative: str | None,
                      params: dict, kind: str) -> dict:
        fields = self._fields(model_id)
        payload: dict = {}
        if fields.get("text") and prompt:
            payload[fields["text"]] = prompt
        if negative:
            payload["negative_prompt"] = negative
        if kind == "video":
            common = build_common_payload(prompt, negative, params, kind)
            payload.setdefault("duration", common.get("duration", 5))
        elif kind == "image":
            if params.get("aspect_ratio"):
                payload["aspect_ratio"] = params["aspect_ratio"]
        if params.get("seed") not in (None, ""):
            payload["seed"] = params["seed"]
        for key in PASSTHROUGH:
            if params.get(key) not in (None, "", []):
                payload[key] = params[key]

        # media inputs: audio/video land directly, image/reference inputs go
        # through the shared mapper (which handles data URIs for local files)
        inputs = image_inputs(params)
        for key in ("audio", "video"):
            if inputs.get(key) and fields.get(key):
                payload[fields[key]] = str(inputs[key])
        apply_image_inputs(payload, params,
                           {k: v for k, v in fields.items()
                            if k in ("image", "end_image", "references", "strength") and v})
        return payload

    def submit(self, key: str, model_id: str, prompt: str,
               negative: str | None, params: dict, kind: str) -> str:
        payload = self.build_payload(model_id, prompt, negative, params, kind)
        with self._client(key) as c:
            resp = c.post(f"{API}/{model_id}", json=payload)
        if resp.status_code in (401, 403):
            raise ProviderError("MuAPI rejected the key (401).", "auth")
        if resp.status_code == 404:
            raise ProviderError(f"MuAPI doesn't know endpoint '{model_id}' — "
                                "fix it in the model catalog.", "model")
        if resp.status_code == 422:
            raise ProviderError(f"MuAPI rejected the parameters for '{model_id}': "
                                f"{resp.text[:200]}", "params")
        if resp.status_code >= 400:
            raise ProviderError(f"MuAPI error HTTP {resp.status_code}: "
                                f"{resp.text[:200]}", "submit")
        body = resp.json() or {}
        job_id = body.get("id") or body.get("request_id") or body.get("prediction_id")
        if not job_id:
            raise ProviderError("MuAPI returned no request id.", "submit")
        return str(job_id)

    def poll(self, key: str, model_id: str, job_ref: str) -> dict:
        with self._client(key) as c:
            resp = c.get(f"{API}/predictions/{job_ref}/result")
        if resp.status_code >= 400:
            return {"status": "failed", "error": f"MuAPI poll HTTP {resp.status_code}"}
        body = resp.json() or {}
        status = str(body.get("status") or "").lower()
        if status in FAILED:
            return {"status": "failed",
                    "error": str(body.get("error") or f"MuAPI status {status}")}
        if status not in DONE:
            return {"status": "queued" if status in QUEUED else "running"}
        url = extract_output_url(body)
        if url:
            return {"status": "succeeded", "output_url": url}
        text = extract_text(body)
        if text is not None:
            # text results (transcription, audio analysis) carry no file
            return {"status": "succeeded", "output_text": text}
        return {"status": "failed", "error": "MuAPI returned no output"}
