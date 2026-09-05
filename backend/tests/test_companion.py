"""Companion tests (9.1–9.3): pairing lifecycle, WS auth, request bridge,
LLM-over-companion, offline job queue + drain, desktop core proxy logic."""
import json
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

from promptforge import db as db_mod, settings_store
from promptforge.companion import pairing
from promptforge.companion.manager import CompanionOffline, drain_job_queue, hub
from promptforge.models import Companion, LlmJob

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "companion"))


@pytest.fixture(autouse=True)
def clean_hub():
    yield
    hub._ws = None
    hub._companion_id = None
    hub._futures.clear()


def test_pairing_lifecycle(client):
    code = client.post("/api/companion/pairing-code").json()["code"]
    assert len(code) == 6
    r = client.post("/api/companion/pair", json={"code": code, "name": "My PC"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert token.startswith("pfc_")
    cid = r.json()["companion_id"]
    # token stored hashed, never raw
    with db_mod.session_scope() as s:
        row = s.get(Companion, cid)
        assert row.token_sha256 == pairing.hash_token(token)
        assert token not in row.token_sha256
    # single-use code
    assert client.post("/api/companion/pair",
                       json={"code": code, "name": "x"}).status_code == 401
    # bad code
    r = client.post("/api/companion/pair", json={"code": "000000", "name": "x"})
    assert r.status_code == 401 and "Settings" in r.json()["detail"]
    # list + revoke
    listing = client.get("/api/companion").json()
    assert listing["companions"][0]["name"] == "My PC"
    assert listing["online"] is False
    assert client.delete(f"/api/companion/{cid}").status_code == 200
    assert client.get("/api/companion").json()["companions"] == []


def test_ws_rejects_bad_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/companion/ws?token=pfc_wrong") as ws:
            ws.receive_json()


def _paired_token(client) -> str:
    code = client.post("/api/companion/pairing-code").json()["code"]
    return client.post("/api/companion/pair",
                       json={"code": code, "name": "GPU rig"}).json()["token"]


def test_ws_hello_and_request_bridge(client):
    token = _paired_token(client)
    with client.websocket_connect(f"/api/companion/ws?token={token}") as ws:
        ws.send_json({"t": "hello", "name": "GPU rig",
                      "ollama_models": ["llama3.1:8b", "qwen2.5"]})
        # give the server loop a beat to process (bounded wait — the hello is
        # handled on the app's event loop, not synchronously with send_json)
        for _ in range(50):
            status = client.get("/api/companion").json()
            if status["online"]:
                break
            time.sleep(0.05)
        assert status["online"] is True
        assert "llama3.1:8b" in status["models"]

        # request bridge: server-side sync call ↔ this test playing companion
        result_box: dict = {}

        def call():
            result_box["result"] = hub.request_sync(
                "ollama.chat", {"model": "llama3.1"}, timeout=10)

        t = threading.Thread(target=call)
        t.start()
        req = ws.receive_json()
        assert req["t"] == "request" and req["method"] == "ollama.chat"
        ws.send_json({"t": "result", "id": req["id"], "ok": True,
                      "data": {"message": {"content": "hi from the GPU"}}})
        t.join(timeout=10)
        assert result_box["result"]["message"]["content"] == "hi from the GPU"
    # socket closed → offline again (disconnect is processed asynchronously)
    for _ in range(50):
        if not hub.online:
            break
        time.sleep(0.05)
    assert hub.online is False
    with pytest.raises(CompanionOffline):
        hub.request_sync("ollama.tags", {})


def test_companion_llm_client_and_test(client):
    from promptforge.llm.companion_client import CompanionLLMClient
    llm = CompanionLLMClient("llama3.1")
    # offline → clear error mentioning offline (queues upstream)
    from promptforge.llm.client import LLMError
    with pytest.raises(LLMError, match="offline"):
        llm.complete("sys", "user")
    assert llm.test()["ok"] is False

    token = _paired_token(client)
    with client.websocket_connect(f"/api/companion/ws?token={token}") as ws:
        ws.send_json({"t": "hello", "name": "rig", "ollama_models": ["llama3.1"]})
        box: dict = {}

        def call():
            box["out"] = llm.complete("system prompt", "user prompt")

        t = threading.Thread(target=call)
        t.start()
        req = ws.receive_json()
        assert req["payload"]["messages"][0]["content"] == "system prompt"
        ws.send_json({"t": "result", "id": req["id"], "ok": True,
                      "data": {"message": {"content": "analyzed!"}}})
        t.join(timeout=10)
        assert box["out"] == "analyzed!"


def test_jobs_queue_offline_and_drain(app_env):
    from promptforge.knowledge import engine
    from tests.conftest import seed_post
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "companion")
    seed_post(model_family="flux", prompt="queued while offline")
    engine.analyze_family("flux")  # companion offline → job queued
    from sqlalchemy import select
    with db_mod.session_scope() as s:
        jobs = s.execute(select(LlmJob)).scalars().all()
        assert len(jobs) == 1 and jobs[0].status == "queued"
    # companion comes back (simulate by switching provider to mock) → drain
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "mock")
    from promptforge.llm.client import mock_instance
    mock_instance.responses = [json.dumps({"profile": "drained", "guidance": "",
                                           "reference_images": "", "notes": []})]
    drained = drain_job_queue()
    assert drained == 1
    with db_mod.session_scope() as s:
        job = s.execute(select(LlmJob)).scalars().one()
        assert job.status == "done"


def test_desktop_core_proxy_logic():
    from app import ALLOWED_METHODS, CompanionCore, MiniLog

    calls = []

    def ollama(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path,
                      request.content and json.loads(request.content)))
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.1"}]})
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"content": "pong"}})
        return httpx.Response(404)

    core = CompanionCore("http://server:5643", "pfc_x", "http://localhost:11434",
                         "Test PC", MiniLog(),
                         ollama_transport=httpx.MockTransport(ollama))
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        tags = loop.run_until_complete(core.handle_request("ollama.tags", {}))
        assert tags["models"][0]["name"] == "llama3.1"
        chat = loop.run_until_complete(core.handle_request(
            "ollama.chat", {"model": "llama3.1",
                            "messages": [{"role": "user", "content": "hi"}]}))
        assert chat["message"]["content"] == "pong"
        # stream forced off on the wire
        assert calls[-1][2]["stream"] is False
        # ONLY ollama endpoints — anything else refused
        with pytest.raises(ValueError, match="not allowed"):
            loop.run_until_complete(core.handle_request("shell.exec", {}))
        assert set(ALLOWED_METHODS) == {"ollama.tags", "ollama.chat",
                                        "ollama.generate"}
        assert core.ws_url() == \
            "ws://server:5643/api/companion/ws?token=pfc_x"
    finally:
        loop.run_until_complete(core.http.aclose())
        loop.close()


def test_companion_download_zip(client):
    r = client.get("/api/companion/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    import io
    import zipfile
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "promptforge-companion/app.py" in names
    assert "promptforge-companion/requirements.txt" in names
