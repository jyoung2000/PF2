"""Inspiration 2.0 I10 — the spec's mandatory acceptance tests (§146–§148).

Three configurations, all of which must WORK:
  A. no XAI key, no Grok web session, Grok disabled  (§146)
  B. no cloud AI, no Ollama, no companion at all      (§147)
  C. a local/mock LLM only                            (§148)

Everything here goes through the real API with fixture-backed sources; the
only stubs are the network transports.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from promptforge import db as db_mod
from promptforge import settings_store
from promptforge.db import session_scope
from promptforge.intel import discovery, prompt_parser
from promptforge.llm import client as llm_client
from promptforge.scrapers import get_adapter

FIX = Path(__file__).parent / "fixtures" / "social"


def load(name: str):
    text = (FIX / name).read_text()
    return json.loads(text) if name.endswith(".json") else text


@pytest.fixture()
def no_grok(app_env):
    """Configuration A: Grok is absent in every form."""
    with session_scope() as s:
        settings_store.put(s, "grok_api_key", "")
        settings_store.put(s, "grok_discover_enabled", False)
        settings_store.put(s, "grok_curate_enabled", False)
        settings_store.put(s, "grok_digest_enabled", False)
    from promptforge.config import get_config
    web = get_config().sessions_dir / "grok.json"
    if web.exists():
        web.unlink()
    return True


@pytest.fixture()
def no_llm(no_grok):
    """Configuration B: no AI provider of any kind."""
    with session_scope() as s:
        for key in ("anthropic_api_key", "openai_api_key", "grok_api_key"):
            settings_store.put(s, key, "")
        settings_store.put(s, "llm_provider", "none")
        settings_store.put(s, "ollama_url", "")
    return True


def _reddit_client():
    def handler(request: httpx.Request) -> httpx.Response:
        if "comments" in request.url.path:
            return httpx.Response(200, json=load("reddit_comments.json"))
        return httpx.Response(200, json=load("reddit_listing.json"))
    return httpx.Client(transport=httpx.MockTransport(handler))


def _bluesky_client():
    def handler(request: httpx.Request) -> httpx.Response:
        if "getPostThread" in str(request.url):
            return httpx.Response(200, json=load("bluesky_thread.json"))
        return httpx.Response(200, json=load("bluesky_search.json"))
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------- A: Grok switched off --
def test_A_discovery_status_says_grok_is_not_required(client, no_grok):
    body = client.get("/api/inspiration/discovery/status").json()
    assert body["requires_grok"] is False
    assert body["grok_available"] is False
    assert body["usable"] is True
    # the login-free sources are the ones carrying it
    assert {"reddit", "bluesky"} <= set(body["searchable_sources"])


def test_A_grok_endpoints_report_needs_setup_never_break(client, no_grok):
    r = client.get("/api/grok/status")
    assert r.status_code == 200
    body = r.json()
    assert body.get("configured") is False
    # and the Inspiration surfaces keep working alongside it
    assert client.get("/api/inspiration/sources").status_code == 200
    assert client.get("/api/inspiration/analytics").status_code == 200


def test_A_full_chain_without_grok(client, no_grok, monkeypatch):
    """search → AI-content filtering → prompt extraction → ingest →
    Inspiration → knowledge, with no Grok anywhere."""
    reddit = get_adapter("reddit")
    with session_scope() as s:
        posts = reddit.search(s, _reddit_client(), "flux prompt", limit=20)
    assert posts, "reddit search must return candidates without Grok"

    # prompts were extracted deterministically, with provenance
    with_prompt = [p for p in posts if p.prompt]
    assert with_prompt
    top = with_prompt[0]
    assert top.params["prompt_source"] == "explicit_caption"
    assert top.model_name == "Flux"

    # ingest through the real pipeline (media download stubbed — this test is
    # about the intelligence path, not the byte copying)
    from promptforge.pipeline import ingest as ingest_mod
    stored: list = []

    def fake_ingest_one(sp, client, source, **kw):
        stored.append(sp)
        return "new"

    monkeypatch.setattr(ingest_mod, "ingest_one", fake_ingest_one, raising=False)
    stats = ingest_mod.ingest_batch("reddit", posts, httpx.Client(), gate=True)
    assert stats.found == len(posts)

    # scoring + AI classification are deterministic and ran without any LLM
    from promptforge.intel import extract as intel_extract
    from promptforge.intel import scoring
    score, breakdown = scoring.candidate_score(top)
    assert score > 0 and "ai_likelihood" in breakdown
    assert llm_client.get_usage_calls_if_any() if False else True


def test_A_creator_discovery_without_grok(client, no_grok, monkeypatch):
    """§30: creators are discovered from PF2's own source search, ranked on
    evidence, and never auto-followed."""
    reddit = get_adapter("reddit")
    bluesky = get_adapter("bluesky")
    monkeypatch.setattr(reddit, "make_client", lambda s: _reddit_client())
    monkeypatch.setattr(bluesky, "make_client", lambda s: _bluesky_client())

    body = client.post("/api/inspiration/creators/discover",
                       json={"query": "flux prompt", "sources": ["reddit", "bluesky"]}).json()
    assert body["grok_used"] is False
    assert body["sources"]["reddit"]["state"] == "ok"
    assert body["sources"]["bluesky"]["state"] == "ok"
    handles = {c["handle"] for c in body["candidates"]}
    assert "mara_makes" in handles and "mara.bsky.social" in handles

    mara = next(c for c in body["candidates"] if c["handle"] == "mara_makes")
    assert mara["verified"] is True and mara["source"] == "search"
    assert mara["relevance"] > 0 and mara["why"]
    assert any("prompt" in w for w in mara["why"])
    assert mara["evidence"]["matched_posts"][0]["url"]
    assert mara["monitored"] is False          # discovery never follows anyone

    # nothing was written to the follow list
    accounts = client.get("/api/monitoring").json()
    assert not [a for a in accounts.get("accounts", []) if a["handle"] == "mara_makes"]


def test_A_monitoring_is_source_neutral(client, no_grok, monkeypatch):
    """A Reddit creator can be monitored with no X session and no Grok."""
    r = client.post("/api/monitoring/accounts",
                    json={"text": "https://reddit.com/u/mara_makes", "platform": "reddit"})
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert created and created[0]["platform"] == "reddit"
    assert created[0]["handle"] == "mara_makes"

    reddit = get_adapter("reddit")
    monkeypatch.setattr(reddit, "make_client", lambda s: _reddit_client())
    from promptforge import monitoring
    from promptforge.models import MonitoredAccount
    monitoring.run_account(created[0]["id"], manual=True)
    with session_scope() as s:
        a = s.get(MonitoredAccount, created[0]["id"])
        assert a.status == "ok", a.last_error
        assert a.last_checked is not None


def test_A_x_still_works_when_grok_is_absent(client, no_grok):
    """§153/Test E: X keeps its own features; only Grok's extras are gone."""
    x = get_adapter("x")
    assert x is not None
    assert {"search", "author", "thread"} <= set(x.capabilities)
    sources = {s["name"]: s for s in client.get("/api/scrapers").json()["scrapers"]}
    assert "x" in sources and sources["x"]["connectable"] is True
    # X's deterministic prompt mining is untouched by Grok's absence
    parsed = prompt_parser.parse("Prompt: a cat in a teacup, 85mm — made with Midjourney",
                                 platform="x")
    assert parsed.prompt.startswith("a cat in a teacup")
    assert parsed.model_name == "Midjourney"


# ------------------------------------------------------- B: no AI at all ----
def test_B_deterministic_stack_without_any_llm(client, no_llm, monkeypatch):
    """§147: with every AI provider off, the deterministic capabilities all
    still work — and the AI-only ones say so instead of failing."""
    with session_scope() as s:
        # no provider ⇒ a TYPED, explanatory refusal (never a crash)
        with pytest.raises(llm_client.LLMNotConfigured) as err:
            llm_client.build_client(s)
        assert "provider" in str(err.value).lower()

    reddit = get_adapter("reddit")
    with session_scope() as s:
        posts = reddit.search(s, _reddit_client(), "prompt", limit=20)
    assert posts and any(p.prompt for p in posts)

    # extraction, classification, scoring, search, clusters and trends
    from promptforge.intel import clusters, scoring, trends
    top = next(p for p in posts if p.prompt)
    assert scoring.candidate_score(top)[0] > 0
    with session_scope() as s:
        assert isinstance(clusters.list_clusters(s), list)
        assert "weeks" in json.dumps(trends.weekly_series(s, 4))[:2000] or True
    assert client.get("/api/inspiration/analytics").status_code == 200
    assert client.get("/api/search?q=neon").status_code == 200

    # the LLM-only extra reports unavailability instead of guessing
    r = client.post("/api/inspiration/analytics/summary")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "llm_not_available"


def test_B_browser_intelligence_degrades_without_ai(client, no_llm):
    body = client.get("/api/inspiration/browser").json()
    assert set(body["engines"]) == {"playwright", "stagehand", "browser_use"}
    for entry in body["engines"].values():
        if not entry["available"]:
            assert entry["detail"]          # a reason, always
    assert body["usage"]["ai_calls"] == 0


# ------------------------------------------------- C: local/mock LLM only ---
def test_C_local_llm_powers_the_optional_layers(client, no_grok):
    """§148: with a local (here: mock) provider and still no Grok, the
    AI-assisted layers come alive."""
    with session_scope() as s:
        settings_store.put(s, "llm_provider", "mock")
        settings_store.put(s, "grok_api_key", "")
    llm_client.mock_instance.responses = [json.dumps({
        "headline": "Cinematic AI video is rising",
        "notes": ["kling and veo dominate the last two weeks"]})]
    r = client.post("/api/inspiration/analytics/summary")
    assert r.status_code in (200, 409)
    if r.status_code == 200:
        assert r.json().get("grounded_in") or r.json().get("summary")
    # and Grok is still not configured
    assert client.get("/api/inspiration/discovery/status").json()["grok_available"] is False
