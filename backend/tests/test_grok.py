"""Phase X3 tests: Grok client + test-connection failure modes, discover with
de-dupe, curation writes (inferred vs stated, whitelists, tags), budget,
digest, and clean no-ops when the key is missing."""
import json

import httpx
import pytest
from sqlalchemy import select

from promptforge import db as db_mod, settings_store
from promptforge.integrations import grok
from promptforge.models import MonitoredAccount, Post
from tests.conftest import seed_post


def configure(key="xai-good"):
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_api_key", key)


def xai_server(state):
    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        if auth != "Bearer xai-good":
            return httpx.Response(401, json={"error": "invalid key"})
        path = request.url.path
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [
                {"id": "grok-3-mini"}, {"id": "grok-4"},
                {"id": "embedding-1"}]})
        if path.endswith("/chat/completions"):
            body = json.loads(request.content)
            state["requests"] = state.get("requests", []) + [body]
            reply = state.get("reply", "{}")
            return httpx.Response(200, json={
                "choices": [{"message": {"role": "assistant",
                                         "content": reply}}]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


# ------------------------------------------------------------ connection ----
def test_test_connection_modes(app_env):
    state: dict = {}
    t = xai_server(state)
    with db_mod.session_scope() as s:
        with pytest.raises(grok.GrokError, match="console.x.ai"):
            grok.test_connection(s, t)                      # no key
    configure()
    with db_mod.session_scope() as s:
        result = grok.test_connection(s, t)
        assert result["ok"] is True
        assert result["models"] == ["grok-3-mini", "grok-4"]  # grok-only filter
    configure("xai-bad")
    with db_mod.session_scope() as s:
        with pytest.raises(grok.GrokError, match="401"):
            grok.test_connection(s, t)

    def down(request):
        raise httpx.ConnectError("no route")
    configure()
    with db_mod.session_scope() as s:
        with pytest.raises(grok.GrokError, match="Can't reach"):
            grok.test_connection(s, httpx.MockTransport(down))


def test_api_test_endpoint(client, app_env, monkeypatch):
    state: dict = {}
    monkeypatch.setattr(grok, "_client",
                        lambda key, transport=None: httpx.Client(
                            headers={"Authorization": f"Bearer {key}"},
                            transport=xai_server(state)))
    r = client.post("/api/grok/test")
    assert r.status_code == 400  # not configured
    configure()
    r = client.post("/api/grok/test")
    assert r.status_code == 200 and "grok-4" in r.json()["models"]


# -------------------------------------------------------------- discover ----
def test_discover_dedupes_and_validates(app_env):
    configure()
    with db_mod.session_scope() as s:
        s.add(MonitoredAccount(handle="alreadywatched", platform="x"))
    state = {"reply": json.dumps([
        {"handle": "@FreshCreator", "display_name": "Fresh",
         "reason": "posts daily Kling videos", "sample": "orbit shot of..."},
        {"handle": "alreadywatched", "reason": "known"},
        {"handle": "not a handle!!", "reason": "junk"},
        {"handle": "FreshCreator", "reason": "duplicate spelling"},
    ])}
    candidates = grok.discover_creators("cinematic AI video",
                                        transport=xai_server(state))
    assert [c["handle"] for c in candidates] == ["freshcreator", "alreadywatched"]
    assert candidates[0]["already_monitored"] is False
    assert candidates[1]["already_monitored"] is True
    # live X search was requested
    assert state["requests"][0]["search_parameters"]["sources"] == [{"type": "x"}]
    # usage counted
    with db_mod.session_scope() as s:
        assert grok.get_usage(s)["by"]["discover"] == 1


def test_discover_disabled_and_unconfigured(app_env):
    configure()
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_discover_enabled", False)
    with pytest.raises(grok.GrokError, match="switched off"):
        grok.discover_creators("x", transport=xai_server({}))
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_discover_enabled", True)
        settings_store.put(s, "grok_api_key", "")
    with pytest.raises(grok.GrokError, match="Settings"):
        grok.discover_creators("x", transport=xai_server({}))


def test_discover_endpoint_and_add_flow(client, app_env, monkeypatch):
    configure()
    state = {"reply": json.dumps([
        {"handle": "newartist", "reason": "flux portraits"}])}
    monkeypatch.setattr(grok, "chat",
                        lambda *a, **kw: state["reply"])
    r = client.post("/api/grok/discover", json={"interest": "flux portraits"})
    assert r.status_code == 200
    assert r.json()["candidates"][0]["handle"] == "newartist"
    # review flow: user clicks Add → normal monitoring endpoint, added_by=grok
    r = client.post("/api/monitoring/accounts",
                    json={"text": "newartist", "added_by": "grok",
                          "notes": "flux portraits"})
    created = r.json()["created"][0]
    assert created["added_by"] == "grok" and created["notes"] == "flux portraits"
    assert client.post("/api/grok/discover", json={"interest": "  "}).status_code == 422


# --------------------------------------------------------------- curation ---
def seed_x_post(tweet_id: str, prompt: str, model_name=None, **kw):
    return seed_post(platform="x", platform_post_id=tweet_id, prompt=prompt,
                     model_name=model_name,
                     model_family=None if model_name is None else "flux",
                     params={"prompt_confidence": "low",
                             "engagement": {"likes": 50}}, **kw)


def test_curate_writes_verdicts(app_env):
    configure()
    p1 = seed_x_post("9001", "dreamy orbit around a glass garden")   # no model
    p2 = seed_x_post("9002", "flux portrait", model_name="Flux")     # stated
    p3 = seed_x_post("9003", "my cat photo lol")                     # not AI
    state = {"reply": json.dumps({
        str(p1): {"ai_media": True, "model": "Kling",
                  "model_confidence": "inferred",
                  "tags": ["glassy", "Garden "],
                  "techniques": ["orbit", "fake-slug"]},
        str(p2): {"ai_media": True, "model": "Flux",
                  "model_confidence": "stated", "tags": [], "techniques": []},
        str(p3): {"ai_media": False, "model": None,
                  "model_confidence": None, "tags": [], "techniques": []},
    })}
    curated = grok.curate_batch(transport=xai_server(state))
    assert curated == 3
    with db_mod.session_scope() as s:
        a = s.get(Post, p1)
        assert a.model_name == "Kling"                # inferred fills blank
        assert a.model_family == "kling"
        assert a.params["model_inferred"] is True
        assert a.params["grok"]["ai_media"] is True
        assert a.params["grok"]["model_confidence"] == "inferred"
        assert a.technique_tags == ["orbit"]          # whitelist enforced
        assert [t.name for t in a.tags] == ["garden", "glassy"] or \
               sorted(t.name for t in a.tags) == ["garden", "glassy"]
        b = s.get(Post, p2)
        assert b.model_name == "Flux"                 # stated model untouched
        assert "model_inferred" not in b.params
        c = s.get(Post, p3)
        assert c.params["grok"]["ai_media"] is False  # kept, never deleted
    # tag search reaches grok-added tags
    with db_mod.session_scope() as s:
        from promptforge import fts
        assert s.get(Post, p1).id in fts.search_posts(s, "glassy")
    # nothing pending → 0 without an API call
    assert grok.curate_batch(transport=xai_server({"reply": "{}"})) == 0


def test_curate_budget_and_tick_noop(app_env, monkeypatch):
    configure()
    seed_x_post("9100", "one")
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_curate_daily_budget", 1)
        settings_store.put(s, "grok_usage",
                           {"date": grok._usage(s)["date"], "calls": 1,
                            "by": {"curate": 1}})
    with pytest.raises(grok.GrokBudgetExceeded):
        grok.curate_batch(transport=xai_server({"reply": "{}"}))
    # tick logs and stops instead of raising
    calls = []
    monkeypatch.setattr(grok, "curate_batch",
                        lambda **kw: (_ for _ in ()).throw(
                            grok.GrokBudgetExceeded("over")))
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_curate_enabled", True)
    assert grok.curate_tick() == 0
    # key missing → tick is a silent no-op
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_api_key", "")
    monkeypatch.setattr(grok, "curate_batch",
                        lambda **kw: calls.append(1) or 1)
    assert grok.curate_tick() == 0 and calls == []


# ----------------------------------------------------------------- digest ---
def test_digest_builds_stores_and_routes(app_env, monkeypatch):
    configure()
    with db_mod.session_scope() as s:
        s.add(MonitoredAccount(handle="auroraforge", platform="x"))
    seed_post(platform="x", platform_post_id="d1", author="@auroraforge",
              prompt="lighthouse surf", model_family="flux",
              params={"engagement": {"likes": 812}},
              technique_tags=["orbit"])
    state = {"reply": "Aurora Forge shipped a standout Flux piece; orbit shots trending."}
    sent = []
    monkeypatch.setattr("promptforge.integrations.discord_rest.send_message",
                        lambda token, ch, payload: sent.append((ch, payload)))
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_digest_to_discord", True)
        settings_store.put(s, "discord_bot_token", "tok")
        settings_store.put(s, "discord_channel_id", "c1")
    digest = grok.build_digest(transport=xai_server(state))
    assert "orbit shots trending" in digest["text"]
    with db_mod.session_scope() as s:
        stored = settings_store.get(s, "grok_last_digest")
        assert stored["text"] == digest["text"]
    assert sent and sent[0][0] == "c1"
    assert "Grok digest" in sent[0][1]["embeds"][0]["title"]
    # model/technique counts fed to Grok
    assert "'flux': 1" in state["requests"][0]["messages"][1]["content"]


def test_digest_tick_gating(app_env, monkeypatch):
    ran = []
    monkeypatch.setattr(grok, "build_digest", lambda **kw: ran.append(1) or {"at": "x", "text": "t"})
    # disabled / unconfigured → no-op
    assert grok.digest_tick() is None and ran == []
    configure()
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_digest_enabled", True)
        settings_store.put(s, "grok_digest_hours", 24)
    assert grok.digest_tick() is not None and len(ran) == 1
    # fresh digest stored → interval gate holds
    from datetime import datetime, timezone
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_last_digest",
                           {"at": datetime.now(timezone.utc).isoformat(),
                            "text": "fresh"})
    assert grok.digest_tick() is None and len(ran) == 1
    assert grok.digest_tick(force=True) is not None and len(ran) == 2


# ------------------------------------------------------------- LLM factory --
def test_grok_as_knowledge_provider(app_env):
    from promptforge.llm import client as llm_client
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "grok")
        # no key → provider_status not_configured, build raises NotConfigured
        assert llm_client.provider_status(s, "grok")["status"] == "not_configured"
        with pytest.raises(llm_client.LLMNotConfigured, match="Grok"):
            llm_client.build_client(s)
        settings_store.put(s, "grok_api_key", "xai-good")
        client_obj = llm_client.build_client(s)
        assert client_obj.name == "grok"
        assert client_obj.free is False               # budget applies
        assert "x.ai" in client_obj.base
        assert llm_client.provider_status(s, "grok")["status"] == "configured"
