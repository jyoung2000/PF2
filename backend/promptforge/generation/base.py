"""Generation provider interface (8.1) — one adapter file per provider so new
providers are a single file + one registry line."""
from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from .. import settings_store


class ProviderError(Exception):
    def __init__(self, message: str, step: str = "unknown"):
        super().__init__(message)
        self.step = step


class GenerationProvider:
    name = "base"
    label = "Base"
    key_setting = ""          # settings key holding the API key
    key_url = ""              # where the user creates a key

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def _client(self, key: str, extra_headers: dict | None = None) -> httpx.Client:
        kw: dict = {"timeout": 60, "headers": self.auth_headers(key)}
        if extra_headers:
            kw["headers"].update(extra_headers)
        if self._transport is not None:
            kw["transport"] = self._transport
        return httpx.Client(**kw)

    def auth_headers(self, key: str) -> dict:
        raise NotImplementedError

    def get_key(self, s: Session) -> str:
        return settings_store.get(s, self.key_setting) or ""

    def is_configured(self, s: Session) -> bool:
        return bool(self.get_key(s))

    # -- contract ------------------------------------------------------------
    def test_connection(self, key: str) -> dict:
        """{ok, detail}. Must NEVER trigger a paid generation (D10)."""
        raise NotImplementedError

    def submit(self, key: str, model_id: str, prompt: str,
               negative: str | None, params: dict, kind: str) -> str:
        """Start a generation → provider job reference (string)."""
        raise NotImplementedError

    def poll(self, key: str, model_id: str, job_ref: str) -> dict:
        """→ {status: queued|running|succeeded|failed, output_url?, error?}"""
        raise NotImplementedError


def build_common_payload(prompt: str, negative: str | None, params: dict,
                         kind: str) -> dict:
    """Provider-neutral fields; adapters reshape as needed."""
    payload: dict = {"prompt": prompt}
    if negative:
        payload["negative_prompt"] = negative
    if kind == "video":
        duration = params.get("duration_s") or 5
        payload["duration"] = int(duration)
    else:
        size = str(params.get("size") or "1024x1024")
        try:
            w, h = (int(x) for x in size.lower().split("x"))
        except ValueError:
            w = h = 1024
        payload["width"], payload["height"] = w, h
    if params.get("seed") not in (None, ""):
        payload["seed"] = params["seed"]
    return payload
