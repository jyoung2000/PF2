"""Browser Intelligence (I8): policy, workflow store, deterministic replay,
the repair loop, budgets, and real-engine integration on fixture pages.

Engine tests run the REAL libraries (playwright / stagehand / browser-use)
against a local fixture server with deterministic mock LLMs plugged into the
engines' own injection points (D26 posture: real plumbing, canned model).
They skip, with the reason, where an engine isn't installed — the core suite
never needs browser deps."""
from __future__ import annotations

import http.server
import json
import os
import threading
from pathlib import Path

import pytest

# the dev/CI sandbox ships chromium as a bare binary (no playwright-managed
# browser dirs) — same escape hatch the connect flow uses (D56)
if not os.environ.get("PF_CHROMIUM_PATH") and os.path.exists("/opt/pw-browsers/chromium"):
    os.environ["PF_CHROMIUM_PATH"] = "/opt/pw-browsers/chromium"

from promptforge import settings_store
from promptforge.browserintel import base as bi
from promptforge.browserintel import diagnostics, playwright_engine, policy, workflows
from promptforge.db import session_scope

FIXTURES = Path(__file__).parent / "fixtures" / "browserintel"

SEARCH_WORKFLOW = [
    {"op": "goto", "url": "http://127.0.0.1:1/search.html"},   # tests rewrite the port
    {"op": "fill", "selector": "#q", "value_from": "query"},
    {"op": "click", "selector": "#go"},
    {"op": "wait", "selector": ".post", "timeout_ms": 8000},
    {"op": "extract", "items": ".post",
     "fields": {"title": {"selector": ".title", "attr": "text"},
                "url": {"selector": ".title", "attr": "href"},
                "author": {"selector": ".author", "attr": "text"},
                "body": {"selector": ".body", "attr": "text"}}},
]


@pytest.fixture(scope="module")
def fixture_server():
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(FIXTURES), **kw)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _has_playwright() -> bool:
    return playwright_engine.available()


# ------------------------------------------------------------------ policy --
def test_policy_allowlist(app_env):
    assert policy.host_allowed("https://www.reddit.com/r/StableDiffusion/")
    assert policy.host_allowed("https://public.api.bsky.app/xrpc/x")
    assert policy.host_allowed("http://127.0.0.1:8123/fixture.html")
    assert not policy.host_allowed("https://evil.example/steal")
    assert not policy.host_allowed("file:///etc/passwd")
    assert not policy.host_allowed("ftp://reddit.com/x")
    with pytest.raises(policy.PolicyViolation):
        policy.check_url("https://not-a-source.invalid/")
    # user-added domains extend the fence
    with session_scope() as s:
        settings_store.put(s, "browser_intel_extra_domains", ["my-forum.example"])
    assert policy.host_allowed("https://ai.my-forum.example/gallery")


def test_policy_workflow_validation(app_env):
    ok = [{"op": "goto", "url": "https://reddit.com/search?q={query}"},
          {"op": "extract", "items": ".x", "fields": {"t": {"selector": "a"}}}]
    assert policy.check_workflow_actions(ok)
    with pytest.raises(policy.PolicyViolation):
        policy.check_workflow_actions([{"op": "goto", "url": "https://evil.example/"}])
    with pytest.raises(policy.PolicyViolation):
        policy.check_workflow_actions([{"op": "eval", "code": "alert(1)"}])
    with pytest.raises(policy.PolicyViolation):
        policy.check_workflow_actions([{"op": "press", "selector": "#q", "key": "F12"}])
    with pytest.raises(policy.PolicyViolation):
        policy.check_workflow_actions([])


def test_policy_sanitize():
    dirty = {"cookies": [{"name": "auth", "value": "secret"}],
             "url": "https://x.com/ok",
             "note": "Authorization: Bearer abcdef1234567890abcd and pfc_deadbeefdeadbeef1234",
             "nested": {"api_key": "sk-live-123", "fine": "keep me"}}
    clean = policy.sanitize(dirty)
    assert clean["cookies"] == "••••"
    assert clean["nested"]["api_key"] == "••••"
    assert clean["nested"]["fine"] == "keep me"
    assert "abcdef" not in clean["note"] and "pfc_" not in clean["note"]
    assert clean["url"].endswith("/ok")


# --------------------------------------------------------- workflow store ---
def test_workflow_versions_and_health(app_env):
    with session_scope() as s:
        v1 = workflows.save_version(s, "fixture", "search", SEARCH_WORKFLOW, "manual")
        assert (v1.version, v1.status) == (1, "active")
        v2 = workflows.save_version(s, "fixture", "search", SEARCH_WORKFLOW, "stagehand",
                                    repaired=True)
        assert (v2.version, v2.status) == (2, "active")
        assert s.get(type(v1), v1.id).status == "superseded"
        active = workflows.get_active(s, "fixture", "search")
        assert active.id == v2.id
    workflows.mark_result(v2.id, ok=False, error="boom cookie=abc123", broken=True)
    with session_scope() as s:
        wf = workflows.get_active(s, "fixture", "search")
        assert wf is None  # broken ⇒ not active
        d = workflows.workflow_dict(s.get(type(v1), v2.id))
        assert d["health"] == "needs_repair" and "cookie" in d["last_error"]
    # AI-proposed junk is rejected before it can ever be saved
    with session_scope() as s, pytest.raises(policy.PolicyViolation):
        workflows.save_version(s, "fixture", "search",
                               [{"op": "goto", "url": "https://evil.example"}], "stagehand")


# ------------------------------------------------------------------ budget --
def test_ai_budget(app_env):
    with session_scope() as s:
        settings_store.put(s, "browser_intel_daily_ai_calls", 2)
        bi.check_ai_budget(s)
    bi.bump_usage("test", ai_calls=2, seconds=3)
    with session_scope() as s:
        with pytest.raises(bi.BudgetExhausted):
            bi.check_ai_budget(s)
        usage = bi.get_usage(s)
        assert usage["ai_calls"] == 2 and usage["browser_seconds"] == 3


def test_availability_reports_truthfully(app_env):
    out = bi.availability()
    assert set(out["engines"]) == {"playwright", "stagehand", "browser_use"}
    for entry in out["engines"].values():
        assert entry["available"] in (True, False)
        if not entry["available"]:
            assert entry["detail"]
    with session_scope() as s:
        settings_store.put(s, "browser_intel_mode", "off")
        assert bi._ai_engines(s) == []
        settings_store.put(s, "browser_intel_mode", "auto")


# ------------------------------------------- deterministic replay (real) ----
@pytest.mark.skipif(not _has_playwright(), reason="playwright not installed")
def test_playwright_replay_and_fence(app_env, fixture_server):
    actions = json.loads(json.dumps(SEARCH_WORKFLOW))
    actions[0]["url"] = f"{fixture_server}/search.html"
    result = playwright_engine.run_actions(actions, {"query": "flux"})
    rows = result["rows"]
    assert len(rows) == 3
    assert rows[0]["title"].startswith("Neon alley")
    assert rows[0]["author"] == "@mara"
    assert "prompt:" in rows[0]["body"]
    # the injection post arrives as DATA — nothing acted on it
    assert any("IGNORE PREVIOUS INSTRUCTIONS" in (r["title"] or "") for r in rows)
    # a page that tries to redirect off-allowlist stays fenced
    fence = playwright_engine.run_actions(
        [{"op": "goto", "url": f"{fixture_server}/redirector.html"},
         {"op": "wait", "timeout_ms": 700},
         {"op": "extract", "fields": {"here": {"selector": "body", "attr": "text"}}}], {})
    assert "not-allowed.invalid" not in (fence["final_url"] or "")


@pytest.mark.skipif(not _has_playwright(), reason="playwright not installed")
def test_workflow_break_and_stub_repair(app_env, fixture_server, monkeypatch):
    """The full self-healing loop with a stub AI engine: replay against the
    redesigned page fails → repair proposes the v2 selectors → verified →
    saved as version 2 → replay succeeds. (Real-engine repair below.)"""
    actions = json.loads(json.dumps(SEARCH_WORKFLOW))
    actions[0]["url"] = f"{fixture_server}/search_v2.html"   # site redesigned
    with session_scope() as s:
        wf = workflows.save_version(s, "fixture2", "search", actions, "manual",
                                    schema={"fields": {"title": "string"}})
        wf_id = wf.id

    repaired_actions = [
        {"op": "goto", "url": f"{fixture_server}/search_v2.html"},
        {"op": "fill", "selector": "#search-box", "value_from": "query"},
        {"op": "click", "selector": "#submit-btn"},
        {"op": "wait", "selector": ".card", "timeout_ms": 8000},
        {"op": "extract", "items": ".card",
         "fields": {"title": {"selector": ".headline", "attr": "text"},
                    "author": {"selector": ".by", "attr": "text"}}},
    ]

    class StubEngine:
        calls = 0
        @staticmethod
        def available():
            return True
        @staticmethod
        def propose_workflow(**kw):
            StubEngine.calls += 1
            return repaired_actions
        @staticmethod
        def extract(**kw):
            return []

    real = bi._engine_module
    monkeypatch.setattr(bi, "_engine_module",
                        lambda name: StubEngine if name == "stagehand" else real(name))
    out = bi.run_workflow("fixture2", "search", {"query": "kling"})
    assert StubEngine.calls == 1
    assert len(out["rows"]) == 2 and out["rows"][0]["author"] == "@mara"
    with session_scope() as s:
        active = workflows.get_active(s, "fixture2", "search")
        assert active.version == 2 and active.engine == "stagehand"
        assert active.last_repaired is not None
        old = [w for w in workflows.list_workflows(s, "fixture2") if w.id == wf_id][0]
        assert old.status == "broken"
    # diagnostics recorded the failure, sanitized
    diags = diagnostics.list_diagnostics("fixture2")
    assert diags and diags[0]["task"] == "search"


def test_run_workflow_degrades_without_engines(app_env, monkeypatch):
    with session_scope() as s:
        settings_store.put(s, "browser_intel_ai_discovery", False)
    try:
        with pytest.raises(bi.EngineUnavailable):
            bi.run_workflow("nowhere", "search", {})
    finally:
        with session_scope() as s:
            settings_store.put(s, "browser_intel_ai_discovery", True)


# ------------------------------------------------- real engines (fixtures) --
def _has_browser_use() -> bool:
    from promptforge.browserintel import browseruse_engine
    return browseruse_engine.available()


@pytest.mark.skipif(not _has_browser_use(), reason="browser-use not installed")
def test_browser_use_engine_readonly_and_extracts(app_env, fixture_server):
    """The REAL browser-use agent, driven by a deterministic mock LLM: it
    navigates the fixture page, returns schema-validated rows, and its
    registry has no write/JS/file actions at all."""
    import json as _json
    from unittest.mock import AsyncMock

    from browser_use import Tools
    from browser_use.llm.base import BaseChatModel
    from browser_use.llm.views import ChatInvokeCompletion

    from promptforge.browserintel import browseruse_engine as bu

    names = set(Tools(exclude_actions=list(bu.EXCLUDED_ACTIONS)).registry.registry.actions)
    assert not (names & {"evaluate", "write_file", "read_file", "input", "send_keys"})
    assert {"navigate", "extract", "scroll", "done"} <= names

    steps = [
        _json.dumps({"thinking": "", "evaluation_previous_goal": "", "memory": "",
                     "next_goal": "open", "action": [
                         {"navigate": {"url": f"{fixture_server}/search.html"}}]}),
        _json.dumps({"thinking": "", "evaluation_previous_goal": "", "memory": "",
                     "next_goal": "finish", "action": [
                         {"done": {"data": {"items": [{"title": "Neon alley at night — Flux prompt inside"}]},
                                   "success": True}}]}),
    ]
    it = iter(steps)
    llm = AsyncMock(spec=BaseChatModel)
    llm.model = llm.name = llm.model_name = "mock"
    llm.provider = "mock"
    llm._verified_api_keys = True

    async def ainvoke(*a, **kw):
        fmt = a[1] if len(a) >= 2 else kw.get("output_format")
        raw = next(it)
        if fmt is None:
            return ChatInvokeCompletion(completion=raw, usage=None)
        return ChatInvokeCompletion(completion=fmt.model_validate_json(raw), usage=None)

    llm.ainvoke.side_effect = ainvoke

    out = bu.research("List the posts on this page", start_url=f"{fixture_server}/search.html",
                      schema={"fields": {"title": "string"}, "many": True},
                      max_steps=3, llm=llm)
    assert out["rows"] and out["rows"][0]["title"].startswith("Neon alley")
    assert any("search.html" in u for u in out["urls"])


def test_browser_use_refuses_offlist_start(app_env):
    from promptforge.browserintel import browseruse_engine as bu
    with pytest.raises(policy.PolicyViolation):
        bu.research("anything", start_url="https://evil.example/x", llm=object())


def test_stagehand_llm_bridge_is_provider_neutral(app_env, monkeypatch):
    """Stagehand's inference is answered by PF2's own LLM stack: the browser
    AI therefore honours the configured provider, the daily budget and the
    injection preamble — no vendor keys ever reach the browser."""
    pytest.importorskip("stagehand")
    from promptforge.browserintel import stagehand_engine as se

    seen = {}

    def fake_run_llm(purpose, system, user, max_tokens=1500):
        seen.update(purpose=purpose, system=system, user=user)
        return '```json\n{"items": [{"title": "t"}]}\n```'

    monkeypatch.setattr("promptforge.llm.client.run_llm", fake_run_llm)

    class Fmt:
        name = "extract"
        schema_ = None

    class Msg:
        content = "page text with cookie=abc and Bearer secrettoken123456"

    class Params:
        response_format = Fmt()
        messages = [Msg()]
        system_prompt = "stagehand internal"

    import asyncio as _a
    out = _a.run(se._pf2_llm_callable()(Params()))
    got = out.structured_content
    assert json.loads(json.dumps(got, default=lambda o: o.model_dump(mode="json")
                                 if hasattr(o, "model_dump") else str(o))) is not None
    assert "t" in json.dumps(got, default=str)
    assert seen["purpose"] == "browser:extract"
    assert policy.RESEARCH_POLICY[:40] in seen["system"]
    assert policy.INJECTION_PREAMBLE[:40] in seen["system"]
    assert "secrettoken123456" not in seen["user"]     # sanitized before the LLM


def test_stagehand_extension_id_is_deterministic():
    pytest.importorskip("stagehand")
    from promptforge.browserintel import stagehand_engine as se
    a = se.unpacked_extension_id("/opt/x/_extension")
    assert a == se.unpacked_extension_id("/opt/x/_extension")
    assert len(a) == 32 and set(a) <= set("abcdefghijklmnop")
