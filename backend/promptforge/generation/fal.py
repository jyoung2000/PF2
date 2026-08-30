"""fal.ai adapter — queue API (submit + poll). Test = status GET on a
nonexistent request id: 401 ⇒ bad key, 404/422 ⇒ key OK, never charges (D10)."""
from __future__ import annotations

import httpx

from .base import GenerationProvider, ProviderError, build_common_payload

QUEUE = "https://queue.fal.run"
PROBE_MODEL = "fal-ai/flux/dev"
PROBE_ID = "00000000-0000-0000-0000-000000000000"


class FalProvider(GenerationProvider):
    name = "fal"
    label = "fal.ai"
    key_setting = "fal_api_key"
    key_url = "https://fal.ai/dashboard/keys"

    def auth_headers(self, key: str) -> dict:
        return {"Authorization": f"Key {key}"}

    def test_connection(self, key: str) -> dict:
        if not key:
            return {"ok": False, "detail": "No fal.ai key — create one at "
                                           f"{self.key_url} and paste it here."}
        with self._client(key) as c:
            try:
                resp = c.get(f"{QUEUE}/{PROBE_MODEL}/requests/{PROBE_ID}/status")
            except httpx.HTTPError as e:
                return {"ok": False, "detail": f"Can't reach fal.ai "
                                               f"({type(e).__name__})."}
        if resp.status_code in (401, 403):
            return {"ok": False, "detail": "fal.ai rejected the key (401) — "
                                           f"regenerate it at {self.key_url}."}
        # unknown request id with a valid key → 404/422/400
        return {"ok": True, "detail": "fal.ai key accepted"}

    def submit(self, key: str, model_id: str, prompt: str,
               negative: str | None, params: dict, kind: str) -> str:
        common = build_common_payload(prompt, negative, params, kind)
        payload: dict = {"prompt": common["prompt"]}
        if negative:
            payload["negative_prompt"] = negative
        if kind == "video":
            payload["duration"] = common.get("duration", 5)
            if params.get("resolution"):
                payload["resolution"] = params["resolution"]
        else:
            payload["image_size"] = {"width": common["width"],
                                     "height": common["height"]}
            payload["num_images"] = 1
        if "seed" in common:
            payload["seed"] = common["seed"]
        with self._client(key) as c:
            resp = c.post(f"{QUEUE}/{model_id}", json=payload)
        if resp.status_code in (401, 403):
            raise ProviderError("fal.ai rejected the key (401).", "auth")
        if resp.status_code == 404:
            raise ProviderError(f"fal.ai doesn't know model '{model_id}' — "
                                "fix it in Settings → AI providers → pricing.",
                                "model")
        if resp.status_code == 422:
            raise ProviderError(f"fal.ai rejected the request (422): "
                                f"{resp.text[:200]}", "params")
        if resp.status_code >= 400:
            raise ProviderError(f"fal.ai error HTTP {resp.status_code}: "
                                f"{resp.text[:200]}", "submit")
        data = resp.json()
        request_id = data.get("request_id")
        if not request_id:
            raise ProviderError("fal.ai returned no request id.", "submit")
        return request_id

    def poll(self, key: str, model_id: str, job_ref: str) -> dict:
        with self._client(key) as c:
            resp = c.get(f"{QUEUE}/{model_id}/requests/{job_ref}/status")
            if resp.status_code >= 400:
                return {"status": "failed",
                        "error": f"fal.ai status HTTP {resp.status_code}"}
            status = resp.json().get("status")
            if status in ("IN_QUEUE",):
                return {"status": "queued"}
            if status in ("IN_PROGRESS",):
                return {"status": "running"}
            if status != "COMPLETED":
                return {"status": "failed", "error": f"fal.ai status {status}"}
            result = c.get(f"{QUEUE}/{model_id}/requests/{job_ref}")
        if result.status_code >= 400:
            return {"status": "failed",
                    "error": f"fal.ai result HTTP {result.status_code}"}
        data = result.json()
        url = None
        images = data.get("images")
        if isinstance(images, list) and images and isinstance(images[0], dict):
            url = images[0].get("url")
        if not url and isinstance(data.get("video"), dict):
            url = data["video"].get("url")
        if not url and isinstance(data.get("output"), str):
            url = data["output"]
        if not url:
            return {"status": "failed", "error": "fal.ai returned no output url"}
        return {"status": "succeeded", "output_url": url}
