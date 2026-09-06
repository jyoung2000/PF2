"""Anthropic Messages API client."""
from __future__ import annotations

import httpx

from .client import LLMClient, LLMError, LLMNotConfigured


class AnthropicClient(LLMClient):
    name = "anthropic"
    free = False

    def __init__(self, api_key: str, model: str,
                 transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise LLMNotConfigured(
                "Anthropic API key missing — paste it in Settings → Knowledge "
                "engine.")
        self.api_key = api_key
        self.model = model or "claude-sonnet-5"
        kw: dict = {"timeout": 120}
        if transport is not None:
            kw["transport"] = transport
        self.http = httpx.Client(**kw)

    supports_vision = True

    def complete_vision(self, system: str, user: str, images: list[bytes],
                        max_tokens: int = 1500) -> str:
        """Messages API with image content blocks (Phase 2 evaluation)."""
        import base64
        content: list[dict] = []
        for raw in images[:8]:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": _media_type(raw),
                "data": base64.b64encode(raw).decode("ascii")}})
        content.append({"type": "text", "text": user})
        return self._post({"model": self.model, "max_tokens": max_tokens,
                           "system": system,
                           "messages": [{"role": "user", "content": content}]})

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        return self._post({"model": self.model, "max_tokens": max_tokens,
                           "system": system,
                           "messages": [{"role": "user", "content": user}]})

    def _post(self, payload: dict) -> str:
        resp = self.http.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"},
            json=payload)
        if resp.status_code == 401:
            raise LLMError("Anthropic rejected the API key (401) — check it in "
                           "Settings → Knowledge engine.")
        if resp.status_code == 429:
            raise LLMError("Anthropic rate limit hit (429) — analysis will "
                           "retry on the next scheduled pass.")
        if resp.status_code >= 400:
            raise LLMError(f"Anthropic error HTTP {resp.status_code}: "
                           f"{resp.text[:200]}")
        data = resp.json()
        parts = [b.get("text", "") for b in data.get("content", [])
                 if b.get("type") == "text"]
        return "".join(parts)


def _media_type(raw: bytes) -> str:
    if raw[:8].startswith(b"\x89PNG"):
        return "image/png"
    if raw[:3] == b"GIF":
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"
