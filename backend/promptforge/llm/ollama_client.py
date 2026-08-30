"""Direct Ollama client — free local analysis (budget ignored)."""
from __future__ import annotations

import httpx

from .client import LLMClient, LLMError


class OllamaClient(LLMClient):
    name = "ollama"
    free = True

    def __init__(self, base_url: str, model: str,
                 transport: httpx.BaseTransport | None = None):
        self.base = (base_url or "http://localhost:11434").rstrip("/")
        self.model = model or "llama3.1"
        kw: dict = {"timeout": 300}
        if transport is not None:
            kw["transport"] = transport
        self.http = httpx.Client(**kw)

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        try:
            resp = self.http.post(
                f"{self.base}/api/chat",
                json={"model": self.model, "stream": False,
                      "options": {"num_predict": max_tokens},
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]})
        except httpx.HTTPError as e:
            raise LLMError(
                f"Can't reach Ollama at {self.base} ({type(e).__name__}) — is "
                "it running? From Docker use http://host.docker.internal:11434 "
                "or pair the desktop companion instead.") from e
        if resp.status_code == 404:
            raise LLMError(
                f"Ollama doesn't have model '{self.model}' — run: "
                f"ollama pull {self.model}")
        if resp.status_code >= 400:
            raise LLMError(f"Ollama error HTTP {resp.status_code}: "
                           f"{resp.text[:200]}")
        return (resp.json().get("message") or {}).get("content", "")

    def list_models(self) -> list[str]:
        try:
            resp = self.http.get(f"{self.base}/api/tags")
            resp.raise_for_status()
            return [m.get("name", "") for m in resp.json().get("models", [])]
        except httpx.HTTPError as e:
            raise LLMError(f"Can't reach Ollama at {self.base}: "
                           f"{type(e).__name__}") from e

    def test(self) -> dict:
        try:
            models = self.list_models()
            if self.model.split(":")[0] not in [m.split(":")[0] for m in models]:
                return {"ok": False, "models": models,
                        "detail": f"Ollama is up but model '{self.model}' isn't "
                                  f"pulled — run: ollama pull {self.model}"}
            return {"ok": True, "models": models,
                    "detail": f"Ollama up · {len(models)} model(s) · using "
                              f"{self.model}"}
        except LLMError as e:
            return {"ok": False, "detail": str(e)}
