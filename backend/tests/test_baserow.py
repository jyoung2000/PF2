"""Baserow client + test endpoint (4.1, 4.2) against mocked httpx."""
import httpx
import pytest

from promptforge import db as db_mod, settings_store
from promptforge.integrations.baserow import (BaserowClient, BaserowError,
                                              TABLE_NAME)
from tests.conftest import seed_post

TABLES = [{"id": 771, "name": TABLE_NAME, "database_id": 55},
          {"id": 772, "name": "Other", "database_id": 55}]


def make_router(state=None):
    """A fake Baserow server."""
    state = state if state is not None else {}
    state.setdefault("rows", [])
    state.setdefault("fields", [{"id": 1, "name": "prompt", "type": "long_text"}])
    state.setdefault("uploads", [])

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        auth = request.headers.get("Authorization", "")
        if auth != "Token good-token":
            return httpx.Response(401, json={"error": "ERROR_TOKEN_DOES_NOT_EXIST"})
        if path == "/api/database/tokens/check/":
            return httpx.Response(200, json={"token": "ok"})
        if path == "/api/database/tables/all-tables/":
            return httpx.Response(200, json=TABLES)
        if path == "/api/database/fields/table/771/":
            if request.method == "GET":
                return httpx.Response(200, json=state["fields"])
            body = __import__("json").loads(request.content)
            field = {"id": 100 + len(state["fields"]), **body}
            state["fields"].append(field)
            return httpx.Response(200, json=field)
        if path.startswith("/api/database/fields/"):
            return httpx.Response(200, json={})
        if path == "/api/user-files/upload-file/":
            state["uploads"].append(bytes(request.content))
            return httpx.Response(200, json={"name": "uploaded_abc.webp",
                                             "url": "https://files/x.webp"})
        if path.startswith("/api/database/rows/table/771/") and request.method == "POST":
            body = __import__("json").loads(request.content)
            row = {"id": 9000 + len(state["rows"]), **body}
            state["rows"].append(row)
            return httpx.Response(200, json=row)
        if request.method == "DELETE" and "/rows/table/771/" in path:
            state["deleted"] = path
            return httpx.Response(204)
        return httpx.Response(404, json={"error": "not found", "path": path})

    return handler, state


def client_with(handler, token="good-token"):
    return BaserowClient("https://baserow.example", token,
                         transport=httpx.MockTransport(handler))


def test_full_test_connection_flow(app_env):
    handler, state = make_router()
    c = client_with(handler)
    result = c.test_connection()
    assert result["ok"] is True
    assert result["table_id"] == 771
    assert "PromptForge" in result["summary"]
    # created the missing schema fields and wrote+deleted the probe row
    field_names = {f["name"] for f in state["fields"]}
    assert {"media", "tags", "nsfw", "params_json"} <= field_names
    assert state["rows"][0]["prompt"] == "PromptForge connection test"
    assert "deleted" in state


def test_bad_token_message(app_env):
    handler, _ = make_router()
    c = client_with(handler, token="wrong")
    with pytest.raises(BaserowError) as ei:
        c.test_connection()
    assert "401" in str(ei.value)
    assert "API tokens" in str(ei.value)
    assert ei.value.step == "token"


def test_network_error_message(app_env):
    def down(request):
        raise httpx.ConnectError("boom")
    c = client_with(down)
    with pytest.raises(BaserowError) as ei:
        c.check_token()
    assert "Can't reach Baserow" in str(ei.value)


def test_missing_table_id_guidance(app_env):
    handler, _ = make_router()
    c = client_with(handler)
    with pytest.raises(BaserowError) as ei:
        c.find_or_create_table(999)
    assert "999" in str(ei.value) and "PromptForge" in str(ei.value)


def test_push_post_uploads_compressed_media(app_env, monkeypatch):
    handler, state = make_router()
    media = app_env.data_dir / "media/civitai/m.webp"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"compressed-webp-bytes")
    pid = seed_post(media_path="media/civitai/m.webp", prompt="push me",
                    params={"seed": 5, "_stored_bytes": 21})
    with db_mod.session_scope() as s:
        settings_store.put(s, "baserow_token", "good-token")
        settings_store.put(s, "baserow_url", "https://baserow.example")
        settings_store.put(s, "baserow_table_id", "771")
    from promptforge.integrations import baserow as br
    monkeypatch.setattr(br, "client_from_settings",
                        lambda s, transport=None: client_with(handler))
    result = br.push_post_id(pid)
    assert result["ok"] is True
    assert len(state["uploads"]) == 1
    assert b"compressed-webp-bytes" in state["uploads"][0]  # the compressed file
    row = state["rows"][-1]
    assert row["prompt"] == "push me"
    assert row["media"] == [{"name": "uploaded_abc.webp"}]
    assert '"seed": 5' in row["params_json"]
    assert "_stored_bytes" not in row["params_json"]
    with db_mod.session_scope() as s:
        from promptforge.models import Post
        assert s.get(Post, pid).synced_to_baserow is True
    # second push skips (no duplicate)
    assert br.push_post_id(pid) == {"ok": True, "skipped": "already synced"}


def test_api_test_endpoint_success_and_error(client, monkeypatch):
    handler, _ = make_router()
    from promptforge.integrations import baserow as br
    monkeypatch.setattr(br, "client_from_settings",
                        lambda s, transport=None: client_with(handler))
    with db_mod.session_scope() as s:
        settings_store.put(s, "baserow_token", "good-token")
    r = client.post("/api/integrations/baserow/test")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # status endpoint reflects the successful test
    status = client.get("/api/integrations/status").json()
    assert status["baserow"]["status"] == "connected"

    monkeypatch.setattr(br, "client_from_settings",
                        lambda s, transport=None: client_with(handler, token="bad"))
    r = client.post("/api/integrations/baserow/test")
    assert r.status_code == 400
    assert r.json()["detail"]["step"] == "token"
    assert "401" in r.json()["detail"]["message"]
    status = client.get("/api/integrations/status").json()
    assert status["baserow"]["status"] == "error"
