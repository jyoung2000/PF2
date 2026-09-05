"""Replicate adapter (file named _provider to avoid pip-package shadowing,
D37). Test = GET /v1/account — free."""
from __future__ import annotations

import httpx

from .base import (GenerationProvider, ProviderError, apply_image_inputs,
                   build_common_payload, data_uri)

API = "https://api.replicate.com/v1"


class ReplicateProvider(GenerationProvider):
    name = "replicate"
    label = "Replicate"
    key_setting = "replicate_api_token"
    key_url = "https://replicate.com/account/api-tokens"

    def auth_headers(self, key: str) -> dict:
        return {"Authorization": f"Bearer {key}"}

    def test_connection(self, key: str) -> dict:
        if not key:
            return {"ok": False, "detail": "No Replicate token — create one at "
                                           f"{self.key_url} and paste it here."}
        with self._client(key) as c:
            try:
                resp = c.get(f"{API}/account")
            except httpx.HTTPError as e:
                return {"ok": False,
                        "detail": f"Can't reach Replicate ({type(e).__name__})."}
        if resp.status_code == 401:
            return {"ok": False, "detail": "Replicate rejected the token (401) "
                                           f"— regenerate it at {self.key_url}."}
        if resp.status_code >= 400:
            return {"ok": False,
                    "detail": f"Replicate error HTTP {resp.status_code}."}
        username = resp.json().get("username", "?")
        return {"ok": True, "detail": f"Connected as {username}"}

    def _file_url(self, c: httpx.Client, path_or_url: str) -> str:
        """Replicate takes data URIs only for small files; larger local
        files go through its files API (POST /v1/files → urls.get)."""
        if path_or_url.startswith(("http://", "https://", "data:")):
            return path_or_url
        from pathlib import Path
        p = Path(path_or_url)
        if p.stat().st_size <= 200_000:
            return data_uri(path_or_url)
        resp = c.post(f"{API}/files", files={"content": (p.name, p.read_bytes())})
        if resp.status_code >= 400:
            raise ProviderError(f"Replicate file upload failed (HTTP {resp.status_code}).", "upload")
        url = ((resp.json() or {}).get("urls") or {}).get("get")
        if not url:
            raise ProviderError("Replicate file upload returned no URL.", "upload")
        return url

    def submit(self, key: str, model_id: str, prompt: str,
               negative: str | None, params: dict, kind: str) -> str:
        common = build_common_payload(prompt, negative, params, kind)
        inputs: dict = {"prompt": prompt}
        if negative:
            inputs["negative_prompt"] = negative
        if kind == "video":
            inputs["duration"] = common.get("duration", 5)
        else:
            inputs["width"] = common["width"]
            inputs["height"] = common["height"]
        if "seed" in common:
            inputs["seed"] = common["seed"]
        with self._client(key) as c:
            apply_image_inputs(inputs, params, {"image": "image", "end_image": "end_image",
                                                "references": "image_input", "strength": "prompt_strength"},
                               convert=lambda v: self._file_url(c, v))
            resp = c.post(f"{API}/models/{model_id}/predictions",
                          json={"input": inputs})
        if resp.status_code == 401:
            raise ProviderError("Replicate rejected the token (401).", "auth")
        if resp.status_code == 404:
            raise ProviderError(f"Replicate doesn't know model '{model_id}' — "
                                "fix it in the pricing catalog.", "model")
        if resp.status_code == 422:
            raise ProviderError(f"Replicate rejected the input (422): "
                                f"{resp.text[:200]}", "params")
        if resp.status_code >= 400:
            raise ProviderError(f"Replicate error HTTP {resp.status_code}: "
                                f"{resp.text[:200]}", "submit")
        pred_id = resp.json().get("id")
        if not pred_id:
            raise ProviderError("Replicate returned no prediction id.", "submit")
        return pred_id

    def poll(self, key: str, model_id: str, job_ref: str) -> dict:
        with self._client(key) as c:
            resp = c.get(f"{API}/predictions/{job_ref}")
        if resp.status_code >= 400:
            return {"status": "failed",
                    "error": f"Replicate poll HTTP {resp.status_code}"}
        data = resp.json()
        status = data.get("status")
        if status in ("starting", "queued"):
            return {"status": "queued"}
        if status == "processing":
            return {"status": "running"}
        if status == "succeeded":
            output = data.get("output")
            url = None
            if isinstance(output, str):
                url = output
            elif isinstance(output, list) and output:
                url = output[0] if isinstance(output[0], str) else None
            if not url:
                return {"status": "failed",
                        "error": "Replicate returned no output url"}
            return {"status": "succeeded", "output_url": url}
        return {"status": "failed",
                "error": str(data.get("error") or f"status {status}")}
