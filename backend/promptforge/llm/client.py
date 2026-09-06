"""Provider-agnostic LLM client (6.2) — used ONLY by the knowledge engine and
Prompt Studio, never for scraping/parsing (iron rule).

Providers: anthropic | openai (any OpenAI-compatible base URL) | ollama
(direct URL) | companion (desktop GPU bridge, Phase 9) | mock (tests/dev only,
D26). Budget guard (D12): a per-UTC-day call budget from settings, ignored for
free/local providers (ollama, companion, mock)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import settings_store
from ..db import session_scope
from ..logbus import bus

FREE_PROVIDERS = {"ollama", "companion", "mock"}


class LLMError(Exception):
    pass


class BudgetExceeded(LLMError):
    pass


class LLMNotConfigured(LLMError):
    pass


class VisionUnsupported(LLMError):
    """Raised when a client cannot look at images (Phase 2 evaluation)."""


class LLMClient:
    name = "base"
    free = False

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        raise NotImplementedError

    # -- vision (Phase 2) ---------------------------------------------------
    supports_vision = False

    def complete_vision(self, system: str, user: str, images: list[bytes],
                        max_tokens: int = 1500) -> str:
        """Answer about the given image bytes. Clients that cannot see raise
        VisionUnsupported so the evaluator can report honestly."""
        raise VisionUnsupported(
            f"{self.name} is not configured for image analysis.")

    def test(self) -> dict:
        """{ok: bool, detail: str, models?: [...]}. Never raises."""
        try:
            out = self.complete(
                "You are a connectivity check. Reply with exactly: pong",
                "ping", max_tokens=10)
            return {"ok": True, "detail": f"Replied: {out.strip()[:40]}"}
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


class MockLLM(LLMClient):
    """Deterministic canned client for tests/dev (never selectable in UI)."""
    name = "mock"
    free = True

    def __init__(self, responses: list[str] | None = None):
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str]] = []
        self.vision_calls: list[tuple[str, str, int]] = []

    supports_vision = True

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        self.calls.append((system, user))
        if self.responses:
            return self.responses.pop(0)
        return '{"note": "mock response"}'

    def complete_vision(self, system: str, user: str, images: list[bytes],
                        max_tokens: int = 1500) -> str:
        self.vision_calls.append((system, user, len(images)))
        return self.complete(system, user, max_tokens)


# a process-wide mock instance so tests can preload responses through settings
mock_instance = MockLLM()


def _budget_key_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_usage(s: Session) -> dict:
    usage = settings_store.get(s, "llm_usage", None) or {}
    today = _budget_key_today()
    if usage.get("date") != today:
        return {"date": today, "calls": 0}
    return usage


def _bump_usage(purpose: str) -> None:
    with session_scope() as s:
        usage = get_usage(s)
        usage["calls"] = int(usage.get("calls", 0)) + 1
        usage.setdefault("by_purpose", {})
        usage["by_purpose"][purpose] = int(usage["by_purpose"].get(purpose, 0)) + 1
        settings_store.put(s, "llm_usage", usage)


def check_budget(s: Session, client: LLMClient) -> None:
    if client.free:
        return
    budget = int(settings_store.get(s, "llm_daily_budget") or 0)
    if budget <= 0:
        return
    usage = get_usage(s)
    if int(usage.get("calls", 0)) >= budget:
        raise BudgetExceeded(
            f"Daily LLM analysis budget reached ({budget} calls) — raise it in "
            "Settings → Knowledge engine, or switch to Ollama/companion for "
            "free local analysis.")


def build_client(s: Session) -> LLMClient:
    provider = (settings_store.get(s, "llm_provider") or "").strip().lower()
    if not provider:
        raise LLMNotConfigured(
            "No AI provider configured — pick one in Settings → Knowledge "
            "engine (Anthropic, OpenAI-compatible, Grok, Ollama, or the "
            "desktop companion).")
    if provider == "mock":
        return mock_instance
    if provider == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(settings_store.get(s, "anthropic_api_key"),
                               settings_store.get(s, "anthropic_model"))
    if provider == "openai":
        from .openai_client import OpenAIClient
        return OpenAIClient(settings_store.get(s, "openai_base_url"),
                            settings_store.get(s, "openai_api_key"),
                            settings_store.get(s, "openai_model"))
    if provider == "grok":
        from .openai_client import OpenAIClient
        client = OpenAIClient(settings_store.get(s, "grok_base_url"),
                              settings_store.get(s, "grok_api_key"),
                              settings_store.get(s, "grok_model"))
        client.name = "grok"
        return client
    if provider == "ollama":
        from .ollama_client import OllamaClient
        return OllamaClient(settings_store.get(s, "ollama_base_url"),
                            settings_store.get(s, "ollama_model"))
    if provider == "companion":
        from .companion_client import CompanionLLMClient
        return CompanionLLMClient(settings_store.get(s, "ollama_model"))
    raise LLMNotConfigured(f"Unknown AI provider '{provider}'.")


def run_llm(purpose: str, system: str, user: str, max_tokens: int = 1500) -> str:
    """The one entry point the knowledge engine and Studio use: budget-checked,
    usage-counted, logged."""
    with session_scope() as s:
        client = build_client(s)
        check_budget(s, client)
    out = client.complete(system, user, max_tokens=max_tokens)
    _bump_usage(purpose)
    bus.info("knowledge", f"LLM call ({purpose}) via {client.name}")
    return out


def provider_status(s: Session, provider: str) -> dict:
    provider = (provider or "").lower()
    if not provider:
        return {"status": "not_configured"}
    if provider == "companion":
        try:
            from ..companion.manager import hub
            st = hub.status()
            return {"status": "connected" if st.get("online") else "offline",
                    "provider": "companion", **st}
        except ImportError:
            return {"status": "offline", "provider": "companion"}
    key_map = {"anthropic": "anthropic_api_key", "openai": "openai_api_key",
               "grok": "grok_api_key"}
    if provider in key_map and not settings_store.get(s, key_map[provider]):
        return {"status": "not_configured", "provider": provider}
    return {"status": "configured", "provider": provider,
            "usage": get_usage(s),
            "budget": settings_store.get(s, "llm_daily_budget")}
