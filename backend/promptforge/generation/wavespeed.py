"""WaveSpeed AI adapter — v3 predictions API. Test = result GET on a fake id
(401 ⇒ bad key; 404 ⇒ key OK), never charges (D10)."""
from __future__ import annotations

import httpx

from .base import (GenerationProvider, ProviderError, apply_image_inputs,
                   build_common_payload)

API = "https://api.wavespeed.ai/api/v3"
PROBE_ID = "00000000000000000000000000000000"


class WaveSpeedProvider(GenerationProvider):
    name = "wavespeed"
    label = "WaveSpeed AI"
    key_setting = "wavespeed_api_key"
    key_url = "https://wavespeed.ai/dashboard/keys"

    def auth_headers(self, key: str) -> dict:
        return {"Authorization": f"Bearer {key}"}

    def test_connection(self, key: str) -> dict:
        if not key:
            return {"ok": False, "detail": "No WaveSpeed key — create one at "
                                           f"{self.key_url} and paste it here."}
        with self._client(key) as c:
            try:
                resp = c.get(f"{API}/predictions/{PROBE_ID}/result")
            except httpx.HTTPError as e:
                return {"ok": False,
                        "detail": f"Can't reach WaveSpeed ({type(e).__name__})."}
        if resp.status_code in (401, 403):
            return {"ok": False, "detail": "WaveSpeed rejected the key (401) — "
                                           f"regenerate it at {self.key_url}."}
        return {"ok": True, "detail": "WaveSpeed key accepted"}

    def submit(self, key: str, model_id: str, prompt: str,
               negative: str | None, params: dict, kind: str) -> str:
        common = build_common_payload(prompt, negative, params, kind)
        payload: dict = {"prompt": prompt}
        if negative:
            payload["negative_prompt"] = negative
        if kind == "video":
            payload["duration"] = common.get("duration", 5)
        else:
            payload["size"] = f"{common['width']}*{common['height']}"
        if "seed" in common:
            payload["seed"] = common["seed"]
        apply_image_inputs(payload, params, {"image": "image", "end_image": "end_image",
                                             "references": "images", "strength": "strength"})
        with self._client(key) as c:
            resp = c.post(f"{API}/{model_id}", json=payload)
        if resp.status_code in (401, 403):
            raise ProviderError("WaveSpeed rejected the key (401).", "auth")
        if resp.status_code == 404:
            raise ProviderError(f"WaveSpeed doesn't know model '{model_id}' — "
                                "fix it in the pricing catalog.", "model")
        if resp.status_code >= 400:
            raise ProviderError(f"WaveSpeed error HTTP {resp.status_code}: "
                                f"{resp.text[:200]}", "submit")
        data = (resp.json() or {}).get("data") or {}
        job_id = data.get("id")
        if not job_id:
            raise ProviderError("WaveSpeed returned no job id.", "submit")
        return job_id

    def poll(self, key: str, model_id: str, job_ref: str) -> dict:
        with self._client(key) as c:
            resp = c.get(f"{API}/predictions/{job_ref}/result")
        if resp.status_code >= 400:
            return {"status": "failed",
                    "error": f"WaveSpeed poll HTTP {resp.status_code}"}
        data = (resp.json() or {}).get("data") or {}
        status = data.get("status")
        if status in ("created", "queued"):
            return {"status": "queued"}
        if status == "processing":
            return {"status": "running"}
        if status == "completed":
            outputs = data.get("outputs") or []
            if not outputs:
                return {"status": "failed",
                        "error": "WaveSpeed returned no outputs"}
            return {"status": "succeeded", "output_url": outputs[0]}
        return {"status": "failed",
                "error": str(data.get("error") or f"status {status}")}
