"""LLM client that rides the companion GPU bridge (9.2): Ollama on the
desktop, proxied over the paired WebSocket. Free — the analysis budget is
ignored (D12)."""
from __future__ import annotations

from ..companion.manager import CompanionOffline, hub
from .client import LLMClient, LLMError


class CompanionLLMClient(LLMClient):
    name = "companion"
    free = True

    def __init__(self, model: str):
        self.model = model or "llama3.1"

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        try:
            result = hub.request_sync("ollama.chat", {
                "model": self.model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "options": {"num_predict": max_tokens},
            })
        except CompanionOffline as e:
            raise LLMError("companion offline — the desktop app isn't "
                           "connected; jobs queue until it returns") from e
        except Exception as e:
            raise LLMError(f"companion call failed: {e}") from e
        if isinstance(result, dict):
            message = result.get("message")
            if isinstance(message, dict):
                return str(message.get("content", ""))
            if "response" in result:
                return str(result["response"])
        raise LLMError("companion returned an unexpected Ollama payload")

    def test(self) -> dict:
        if not hub.online:
            return {"ok": False,
                    "detail": "Companion is offline — run the desktop app and "
                              "pair it (Settings → Companion)."}
        try:
            tags = hub.request_sync("ollama.tags", {}, timeout=20)
            models = [m.get("name", "") for m in (tags or {}).get("models", [])]
            if models and self.model.split(":")[0] not in \
                    [m.split(":")[0] for m in models]:
                return {"ok": False, "models": models,
                        "detail": f"Companion is up but Ollama lacks "
                                  f"'{self.model}' — run: ollama pull {self.model}"}
            return {"ok": True, "models": models,
                    "detail": f"Companion online · {len(models)} Ollama "
                              f"model(s) · using {self.model}"}
        except Exception as e:
            return {"ok": False, "detail": f"Companion test failed: {e}"}
