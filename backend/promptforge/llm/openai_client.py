"""OpenAI-compatible chat-completions client (any base URL)."""
from __future__ import annotations

import httpx

from .client import LLMClient, LLMError, LLMNotConfigured


class OpenAIClient(LLMClient):
    name = "openai"
    free = False

    def __init__(self, base_url: str, api_key: str, model: str,
                 transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise LLMNotConfigured(
                "OpenAI-compatible API key missing — paste it in Settings → "
                "Knowledge engine.")
        self.base = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model or "gpt-4o-mini"
        kw: dict = {"timeout": 120,
                    "headers": {"Authorization": f"Bearer {api_key}"}}
        if transport is not None:
            kw["transport"] = transport
        self.http = httpx.Client(**kw)

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        resp = self.http.post(
            f"{self.base}/chat/completions",
            json={"model": self.model, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]})
        if resp.status_code == 401:
            raise LLMError(f"The endpoint at {self.base} rejected the API key "
                           "(401) — check key and base URL.")
        if resp.status_code >= 400:
            raise LLMError(f"LLM endpoint error HTTP {resp.status_code}: "
                           f"{resp.text[:200]}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Unexpected response shape from {self.base}") from e
