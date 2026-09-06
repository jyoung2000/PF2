"""Browser Use engine (Browser Intelligence Level 4, spec §6/§9).

browser-use (MIT) runs short autonomous research tasks: navigate a permitted
site, find the requested content, return schema-shaped results. PF2 keeps it
on the tightest leash the library offers:

- llm is ALWAYS passed explicitly (their default otherwise calls the
  browser-use cloud gateway) and is built from PF2's configured provider;
- write-capable actions are excluded from the registry (no typing, no file
  writes, no `evaluate` JS) — clicking/navigating/scrolling/extracting stay;
- `allowed_domains` mirrors the PF2 policy allowlist, enforced by their
  SecurityWatchdog on top of our own checks;
- telemetry/cloud-sync/logging-takeover/default-extension downloads are all
  disabled via env before import; the chromium binary is pinned so nothing
  ever tries to download a browser.
"""
from __future__ import annotations

import asyncio
import os

from ..logbus import bus
from . import policy
from .schemas import result_model, rows_from

MAX_STEPS = 10

# read-only research: strip anything that writes to pages, files, or runs JS
EXCLUDED_ACTIONS = ["input", "send_keys", "select_dropdown", "upload_file",
                    "write_file", "replace_file", "read_file", "evaluate",
                    "save_as_pdf"]


def _harden_env() -> None:
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    os.environ.setdefault("BROWSER_USE_CLOUD_SYNC", "false")
    os.environ.setdefault("BROWSER_USE_SETUP_LOGGING", "false")
    os.environ.setdefault("BROWSER_USE_DISABLE_EXTENSIONS", "1")
    os.environ.setdefault("BROWSER_USE_HEADLESS", "true")
    os.environ.pop("BROWSER_USE_DISABLE_SECURITY", None)


def available() -> bool:
    try:
        _harden_env()
        import browser_use  # noqa: F401
        return True
    except ImportError:
        return False


def unavailable_reason() -> str:
    return ("the `browser-use` package isn't installed — it ships in the "
            "Docker image (requirements-browser.txt)")


def _chromium_path() -> str | None:
    return os.environ.get("PF_CHROMIUM_PATH") or None


def _bu_domains() -> list[str]:
    out: list[str] = []
    for d in policy.allowed_domains():
        out.append(d)
        out.append(f"*.{d}")
    return out


def _llm_from_settings():
    """Map PF2's configured provider onto a browser-use chat model. `mock`
    and `companion` have no browser-use client — callers inject `llm=` in
    tests, and companion users fall back to another engine."""
    from .. import settings_store
    from ..db import session_scope
    with session_scope() as s:
        provider = str(settings_store.get(s, "llm_provider") or "")
        cfg = {k: settings_store.get(s, k) for k in (
            "anthropic_api_key", "anthropic_model", "openai_api_key",
            "openai_base_url", "openai_model", "ollama_url", "ollama_model",
            "grok_api_key", "grok_base_url", "grok_model")}
    if provider == "anthropic" and cfg.get("anthropic_api_key"):
        from browser_use import ChatAnthropic
        return ChatAnthropic(model=str(cfg.get("anthropic_model") or "claude-sonnet-5"),
                             api_key=str(cfg["anthropic_api_key"]))
    if provider in ("openai", "openai_compatible") and cfg.get("openai_api_key"):
        from browser_use import ChatOpenAI
        return ChatOpenAI(model=str(cfg.get("openai_model") or "gpt-4o-mini"),
                          api_key=str(cfg["openai_api_key"]),
                          base_url=str(cfg.get("openai_base_url") or None) or None,
                          add_schema_to_system_prompt=True)
    if provider == "grok" and cfg.get("grok_api_key"):
        from browser_use import ChatOpenAI
        return ChatOpenAI(model=str(cfg.get("grok_model") or "grok-3-mini"),
                          api_key=str(cfg["grok_api_key"]),
                          base_url=str(cfg.get("grok_base_url") or "https://api.x.ai/v1"),
                          add_schema_to_system_prompt=True)
    if provider == "ollama":
        from browser_use import ChatOllama
        return ChatOllama(model=str(cfg.get("ollama_model") or "llama3.1"),
                          host=str(cfg.get("ollama_url") or "http://localhost:11434"))
    raise RuntimeError(
        "Browser Use needs a configured AI provider (Anthropic, "
        "OpenAI-compatible, Grok or Ollama) — set one under Settings → AI, "
        "or use the Stagehand/deterministic engines.")


async def _research_async(instruction: str, start_url: str | None, schema: dict | None,
                          storage_state: str | None, max_steps: int,
                          llm=None, headless: bool = True) -> dict:
    _harden_env()
    from browser_use import Agent, BrowserProfile, BrowserSession, Tools
    if start_url:
        policy.check_url(start_url)
    profile = BrowserProfile(
        executable_path=_chromium_path(), headless=headless,
        chromium_sandbox=False, user_data_dir=None,
        storage_state=storage_state if storage_state and os.path.isfile(storage_state) else None,
        allowed_domains=_bu_domains(), enable_default_extensions=False,
        keep_alive=False)
    session = BrowserSession(browser_profile=profile)
    tools = Tools(exclude_actions=list(EXCLUDED_ACTIONS))
    task = "\n\n".join(x for x in (
        policy.RESEARCH_POLICY, policy.INJECTION_PREAMBLE,
        f"Start at: {start_url}" if start_url else None,
        f"Research task: {instruction}",
        "When done, call done with the structured result.") if x)
    out_model = result_model(schema) if schema else None
    agent = Agent(task=task, llm=llm or _llm_from_settings(),
                  browser_session=session, tools=tools,
                  output_model_schema=out_model,
                  use_vision=False, use_judge=False, enable_planning=False,
                  enable_signal_handler=False, calculate_cost=False)
    try:
        history = await agent.run(max_steps=max(2, min(MAX_STEPS, max_steps)))
    finally:
        try:
            await session.kill()
        except Exception:  # noqa: BLE001 — cleanup must never mask the run error
            pass
    rows: list[dict] = []
    final = history.final_result()
    if out_model is not None and final:
        try:
            rows = rows_from(out_model.model_validate_json(final), schema)
        except Exception:  # noqa: BLE001 — non-conforming output is reported, not trusted
            rows = []
    return {"rows": rows, "final": policy.sanitize_text(final or "")[:4000],
            "steps": len(history), "urls": [u for u in history.urls() if u],
            "errors": [e for e in history.errors() if e]}


def research(instruction: str, start_url: str | None = None, schema: dict | None = None,
             storage_state: str | None = None, max_steps: int = 6,
             llm=None, headless: bool = True) -> dict:
    return asyncio.run(_research_async(instruction, start_url, schema,
                                       storage_state, max_steps, llm, headless))


def extract(url: str, instruction: str, schema: dict | None,
            storage_state: str | None = None, platform: str | None = None,
            llm=None, headless: bool = True) -> list[dict]:
    """Facade contract: one-page extraction = a 3-step research run pinned
    to the page."""
    out = research(f"Open the page and extract: {instruction}. Do not leave "
                   "the page except to expand its own content.",
                   start_url=url, schema=schema, storage_state=storage_state,
                   max_steps=4, llm=llm, headless=headless)
    return out["rows"]


def propose_workflow(**_kw):
    raise RuntimeError(
        "Browser Use does research runs, not selector-level workflow "
        "proposals — workflow discovery/repair uses the Stagehand engine.")


def smoke() -> dict:
    try:
        _harden_env()
        import browser_use
        return {"ok": True, "version": getattr(browser_use, "__version__", "?")}
    except Exception as e:  # noqa: BLE001
        bus.warn("browserintel", f"browser-use smoke failed: {e}")
        return {"ok": False, "error": policy.sanitize_text(str(e))[:200]}
