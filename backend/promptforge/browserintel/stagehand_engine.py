"""Stagehand engine (Browser Intelligence Levels 2–3, spec §6/§34).

Stagehand v4 (MIT, Python SDK `stagehand`) drives an installed Chromium over
CDP — no Playwright, no Node worker, no browser downloads. PF2 uses exactly
three of its capabilities:

- observe(instruction)  → concrete Actions {selector, method, arguments}
  which we translate into the policy-validated replayable workflow ops;
- extract(instruction, model) → schema-shaped data from the current page;
- selector proposal for extraction (an extract call whose SCHEMA asks for
  selectors, grounded in the page snapshot) when learning a workflow.

LLM: never Stagehand's built-in provider list. We inject a callable
(`model=<async fn>`) that routes every inference through PF2's OWN LLM
stack (run_llm → Anthropic / OpenAI-compatible / Ollama / companion / mock),
so provider neutrality (§56), the daily budget (D12) and MockLLM testing
(D26) all apply to browser AI too. Telemetry is pinned to a dead local
endpoint. Profiles: per-platform user-data dirs under
DATA_DIR/browser-profiles/{platform} (§13) — never the shared default.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from ..config import get_config
from ..logbus import bus
from . import policy
from .schemas import result_model, rows_from

OBSERVE_METHOD_TO_OP = {"click": "click", "fill": "fill", "press": "press",
                        "doubleClick": "click", "scrollTo": "scroll"}
MAX_STEPS = 12
DEAD_TRACES = "http://127.0.0.1:9/v1/traces"


def available() -> bool:
    try:
        import stagehand  # noqa: F401
        return True
    except ImportError:
        return False


def unavailable_reason() -> str:
    return ("the `stagehand` package isn't installed — it ships in the Docker "
            "image (requirements-browser.txt); pip install stagehand for dev")


def _chromium_path() -> str | None:
    return os.environ.get("PF_CHROMIUM_PATH") or os.environ.get("CHROME_PATH") or None


def profile_dir(platform: str | None) -> str:
    d = get_config().data_dir / "browser-profiles" / (platform or "research")
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


# ------------------------------------------------------------- LLM bridge --
def _pf2_llm_callable():
    """An async `model=` callable that answers Stagehand's structured
    requests through PF2's provider-neutral LLM stack. The system prompt
    always carries the read-only research policy + injection preamble."""
    from ..llm import client as llm_client

    async def generate(params):
        schema = None
        fmt = getattr(params, "response_format", None)
        name = getattr(fmt, "name", "response") if fmt else "response"
        if fmt is not None and getattr(fmt, "schema_", None) is not None:
            dumped = fmt.schema_
            schema = dumped.model_dump() if hasattr(dumped, "model_dump") else dict(dumped)
        parts = []
        for m in getattr(params, "messages", []) or []:
            content = getattr(m, "content", None)
            if isinstance(content, list):
                text = " ".join(getattr(c, "text", "") or "" for c in content)
            else:
                text = getattr(content, "text", None) or str(content or "")
            parts.append(policy.sanitize_text(text))
        system = "\n\n".join(x for x in (
            policy.RESEARCH_POLICY, policy.INJECTION_PREAMBLE,
            getattr(params, "system_prompt", None)) if x)
        user = "\n".join(parts)
        if schema:
            user += ("\n\nRespond with ONLY a JSON object matching this schema "
                     "(no prose):\n" + json.dumps(schema)[:6000])
        text = await asyncio.to_thread(
            llm_client.run_llm, f"browser:{name}", system, user, 2000)
        data = _parse_json(text)
        from stagehand import (LLMRole, LLMStructuredGenerateResult,
                               LLMTextContent)
        return LLMStructuredGenerateResult.model_validate({
            "role": LLMRole.assistant,
            "content": LLMTextContent(type="text", text=text[:4000]),
            "output_format": "json_schema",
            "structured_content": data,
            "stop_reason": "stop", "usage": None})

    return generate


def _parse_json(text: str):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    if start >= 0:
        text = text[start:]
    return json.loads(text)


# ---------------------------------------------------------------- session --
def unpacked_extension_id(path: str) -> str:
    """Chrome derives an unpacked extension's id from its absolute path
    (sha256 → first 32 nibbles mapped onto a–p). Needed by the fallback
    launcher below, where we load the extension ourselves."""
    import hashlib
    digest = hashlib.sha256(path.encode()).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


async def _launch_with_preloaded_extension(platform: str | None, headless: bool):
    """Fallback for Chrome/Chromium builds without the `Extensions.
    loadUnpacked` CDP method (Stagehand's normal injection path): start the
    browser ourselves with --load-extension and attach over CDP using the
    deterministic extension id."""
    import json as _json
    import socket
    import subprocess
    import urllib.request

    import stagehand as _sh
    from stagehand import local_browser
    ext_dir = str(Path(_sh.__file__).parent / "_extension")
    if not Path(ext_dir).is_dir():
        raise RuntimeError("the stagehand package ships no bundled extension directory")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    profile = profile_dir(platform)
    args = [_chromium_path() or "chromium", f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}", "--no-sandbox", "--disable-gpu",
            f"--load-extension={ext_dir}", f"--disable-extensions-except={ext_dir}",
            "--enable-unsafe-extension-debugging", "about:blank"]
    if headless:
        args.insert(4, "--headless=new")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).read()
            break
        except Exception:  # noqa: BLE001 — polling for browser start
            await asyncio.sleep(0.25)
    else:
        proc.terminate()
        raise RuntimeError("the fallback browser never opened its CDP port")
    browser = await local_browser.connect(cdp_url=f"http://127.0.0.1:{port}",
                                          extension_id=unpacked_extension_id(ext_dir))
    browser._pf2_proc = proc  # closed with the browser by _close()
    return browser


async def _close(browser) -> None:
    try:
        await browser.close()
    finally:
        proc = getattr(browser, "_pf2_proc", None)
        if proc is not None:
            proc.terminate()


async def _open(platform: str | None, headless: bool = True, llm=None):
    from stagehand import Stagehand, local_browser
    try:
        browser = await local_browser.launch(
            executable_path=_chromium_path(), headless=headless,
            chromium_sandbox=False, user_data_dir=profile_dir(platform),
            preserve_user_data_dir=True)
    except Exception as e:  # noqa: BLE001
        if "loadUnpacked" not in str(e):
            raise
        bus.warn("browserintel", "this Chromium build has no Extensions.loadUnpacked "
                                 "— attaching Stagehand via --load-extension instead")
        browser = await _launch_with_preloaded_extension(platform, headless)
    create_kwargs: dict = {"browser": browser, "model": llm or _pf2_llm_callable(),
                           "self_heal": False}
    for extra in ({"telemetry": {"traces": {"endpoint": DEAD_TRACES}}},
                  {"system_prompt": policy.RESEARCH_POLICY + " " + policy.INJECTION_PREAMBLE}):
        try:
            sh = await Stagehand.create(**create_kwargs, **extra)
            create_kwargs.update(extra)
            await sh.close()
        except TypeError:
            continue
        except Exception:
            create_kwargs.update(extra)
            break
    sh = await Stagehand.create(**create_kwargs)
    pages = await browser.context.pages()
    page = pages[0] if pages else None
    return browser, sh, page


async def _goto(page, url: str) -> None:
    policy.check_url(url)
    await page.goto(url)


# ------------------------------------------------------------- operations --
async def _extract_async(url: str, instruction: str, schema: dict | None,
                         storage_state: str | None = None, platform: str | None = None,
                         llm=None, headless: bool = True) -> list[dict]:
    browser, sh, page = await _open(platform, headless, llm)
    try:
        await _goto(page, url)
        model = result_model(schema)
        result = await sh.extract(
            f"{policy.INJECTION_PREAMBLE}\n\n{instruction}", model)
        return rows_from(result.data, schema)
    finally:
        try:
            await sh.close()
        finally:
            await _close(browser)


def extract(url: str, instruction: str, schema: dict | None,
            storage_state: str | None = None, platform: str | None = None,
            llm=None, headless: bool = True) -> list[dict]:
    return asyncio.run(_extract_async(url, instruction, schema, storage_state,
                                      platform, llm, headless))


async def _propose_async(start_url: str, task: str, schema: dict,
                         params: dict, platform: str | None,
                         llm=None, headless: bool = True) -> list[dict]:
    """Learn a replayable workflow: observe the interactions the task needs,
    then ask for the extraction selectors, grounded in the live page."""
    browser, sh, page = await _open(platform, headless, llm)
    try:
        await _goto(page, start_url)
        actions: list[dict] = [{"op": "goto", "url": start_url}]
        interact = await sh.observe(
            f"{policy.INJECTION_PREAMBLE}\n\nIdentify the page interactions "
            f"needed to: {task}. Only read-only interactions (open search, "
            "submit a query with Enter, reveal results).")
        for a in (interact.data or [])[:6]:
            method = getattr(a, "method", None) or ""
            op = OBSERVE_METHOD_TO_OP.get(method)
            sel = getattr(a, "selector", None)
            if not op or not sel:
                continue
            if op == "fill":
                args = list(getattr(a, "arguments", None) or [])
                actions.append({"op": "fill", "selector": sel,
                                "value_from": "query",
                                "value": args[0] if args else None})
                actions.append({"op": "press", "selector": sel, "key": "Enter"})
            elif op == "press":
                actions.append({"op": "press", "selector": sel, "key": "Enter"})
            elif op == "scroll":
                actions.append({"op": "scroll", "times": 3})
            else:
                actions.append({"op": op, "selector": sel})
        actions.append({"op": "wait", "timeout_ms": 1200})
        from pydantic import BaseModel, create_model
        fields = (schema or {}).get("fields") or {"title": "string", "url": "string"}
        SelectorPlan: type[BaseModel] = create_model(  # noqa: N806
            "SelectorPlan",
            items_selector=(str, ...),
            **{f"{k}_selector": (str | None, None) for k in fields},
            **{f"{k}_attr": (str | None, None) for k in fields})
        plan = await sh.extract(
            f"{policy.INJECTION_PREAMBLE}\n\nFor the repeated result items on "
            f"this page ({task}): give a CSS selector for one result item "
            "container (items_selector) and, per field, a CSS selector "
            "RELATIVE to that container plus the attribute to read "
            "('text', 'href', or 'src').", SelectorPlan)
        p = plan.data
        extract_fields = {}
        for k in fields:
            sel = getattr(p, f"{k}_selector", None)
            if sel:
                extract_fields[k] = {"selector": sel,
                                     "attr": getattr(p, f"{k}_attr", None) or "text"}
        actions.append({"op": "extract", "items": p.items_selector,
                        "fields": extract_fields})
        return policy.check_workflow_actions(actions)
    finally:
        try:
            await sh.close()
        finally:
            await _close(browser)


def propose_workflow(start_url: str, task: str, schema: dict | None = None,
                     params: dict | None = None, storage_state: str | None = None,
                     platform: str | None = None, llm=None,
                     headless: bool = True) -> list[dict]:
    return asyncio.run(_propose_async(start_url, task, schema or {}, params or {},
                                      platform, llm, headless))


def smoke() -> dict:
    """Cheap non-AI liveness check for /api/health: launch + goto about:blank."""
    async def _run():
        from stagehand import local_browser
        browser = await local_browser.launch(
            executable_path=_chromium_path(), headless=True,
            chromium_sandbox=False)
        try:
            pages = await browser.context.pages()
            return {"ok": True, "pages": len(pages)}
        finally:
            await _close(browser)
    try:
        return asyncio.run(_run())
    except Exception as e:  # noqa: BLE001
        bus.warn("browserintel", f"stagehand smoke failed: {e}")
        return {"ok": False, "error": policy.sanitize_text(str(e))[:200]}
