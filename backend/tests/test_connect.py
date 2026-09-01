"""Phase X5: one-click in-app login. Fake-browser tests of the WS connect
protocol (frames, input forwarding, auto-save on the X auth cookie, manual
save, busy lock, origin check, timeouts, no-browser-stack error) + the
session upload/disconnect REST endpoints."""
import json

import pytest
from starlette.websockets import WebSocketDisconnect

from promptforge import db as db_mod
from promptforge.scrapers import connect, get_adapter


# ------------------------------------------------------------------ fakes ---
class FakeKeyboard:
    def __init__(self):
        self.typed, self.pressed, self.inserted = [], [], []

    async def type(self, text, delay=0):
        self.typed.append(text)

    async def press(self, combo):
        self.pressed.append(combo)

    async def insert_text(self, text):
        self.inserted.append(text)


class FakeMouse:
    def __init__(self):
        self.clicks, self.wheels = [], []

    async def click(self, x, y):
        self.clicks.append((x, y))

    async def wheel(self, dx, dy):
        self.wheels.append((dx, dy))


class FakePage:
    def __init__(self):
        self.keyboard, self.mouse = FakeKeyboard(), FakeMouse()
        self.goto_urls = []
        self.local_keys: list[str] = []

    async def goto(self, url, **kw):
        self.goto_urls.append(url)

    async def screenshot(self, **kw):
        return b"\xff\xd8fake-jpeg"

    async def evaluate(self, script):
        return list(self.local_keys)


class FakeContext:
    def __init__(self):
        self.cookie_list: list[dict] = []

    async def cookies(self):
        return list(self.cookie_list)

    async def storage_state(self):
        return {"cookies": list(self.cookie_list), "origins": []}


def install_fake_browser(monkeypatch):
    page, ctx = FakePage(), FakeContext()
    closed = []

    async def closer():
        closed.append(True)

    async def fake_launch(platform):
        return connect.BrowserHandle(page, ctx, closer)

    monkeypatch.setattr(connect, "_launch", fake_launch)
    return page, ctx, closed


def recv_json(ws, want_t=None, tries=40):
    """Next JSON control message, skipping binary frames."""
    for _ in range(tries):
        msg = ws.receive()
        if msg.get("text") is not None:
            data = json.loads(msg["text"])
            if want_t is None or data.get("t") == want_t:
                return data
    raise AssertionError(f"no {want_t or 'json'} message arrived")


def recv_frame(ws, tries=40):
    for _ in range(tries):
        msg = ws.receive()
        if msg.get("bytes"):
            return msg["bytes"]
    raise AssertionError("no binary frame arrived")


# ---------------------------------------------------------------- protocol --
def test_connect_x_auto_saves_on_auth_cookie(client, app_env, monkeypatch):
    page, ctx, closed = install_fake_browser(monkeypatch)
    # sticky 'expired' state from a dead session must clear on reconnect
    with db_mod.session_scope() as s:
        st = get_adapter("x").get_state(s)
        st.state = {"session_expired": True}
    with client.websocket_connect("/api/ws/connect/x") as ws:
        assert recv_json(ws)["state"] == "launching"
        assert recv_json(ws)["state"] == "live"
        assert page.goto_urls == ["https://x.com/login"]
        assert recv_frame(ws) == b"\xff\xd8fake-jpeg"

        ws.send_text(json.dumps({"t": "click", "x": 640, "y": 300}))
        ws.send_text(json.dumps({"t": "text", "text": "h"}))
        ws.send_text(json.dumps({"t": "text", "text": "my long password"}))
        ws.send_text(json.dumps({"t": "key", "key": "a", "ctrl": True}))
        ws.send_text(json.dumps({"t": "key", "key": "Enter"}))
        ws.send_text(json.dumps({"t": "scroll", "dy": 120}))
        # the user finishes logging in → X sets its session cookie
        ctx.cookie_list.append(
            {"name": "auth_token", "value": "tok123", "domain": ".x.com"})
        assert recv_json(ws, "status")  # more status/frames until detected
        assert recv_json(ws, "saved")

    assert page.mouse.clicks == [(640.0, 300.0)]
    assert page.keyboard.typed == ["h"]                    # real key events
    assert page.keyboard.inserted == ["my long password"]  # paste path
    assert "Control+a" in page.keyboard.pressed
    assert "Enter" in page.keyboard.pressed
    assert page.mouse.wheels == [(0, 120.0)]
    assert closed  # browser shut down with the socket

    saved = json.loads((app_env.sessions_dir / "x.json").read_text())
    assert saved["cookies"][0]["name"] == "auth_token"
    with db_mod.session_scope() as s:
        assert get_adapter("x").session_status(s) == "valid"  # expired cleared


def test_connect_manual_save_other_site(client, app_env, monkeypatch):
    _page, ctx, _closed = install_fake_browser(monkeypatch)
    ctx.cookie_list = [{"name": "mj_session", "value": "v", "domain": ".midjourney.com"}]
    with client.websocket_connect("/api/ws/connect/midjourney") as ws:
        recv_json(ws, "status")
        ws.send_text(json.dumps({"t": "save"}))
        assert recv_json(ws, "saved")
    assert (app_env.sessions_dir / "midjourney.json").is_file()


def test_connect_busy_unknown_and_no_stack(client, app_env, monkeypatch):
    install_fake_browser(monkeypatch)
    with client.websocket_connect("/api/ws/connect/x") as ws:
        recv_json(ws, "status")
        with client.websocket_connect("/api/ws/connect/x") as ws2:
            assert "already open" in recv_json(ws2, "error")["message"]
        ws.send_text(json.dumps({"t": "cancel"}))
    with client.websocket_connect("/api/ws/connect/notasite") as ws:
        assert "no in-app login" in recv_json(ws, "error")["message"]

    async def broken(platform):
        raise RuntimeError("browser stack isn't installed — use the Docker image")
    monkeypatch.setattr(connect, "_launch", broken)
    with client.websocket_connect("/api/ws/connect/x") as ws:
        recv_json(ws, "status")
        assert "Docker image" in recv_json(ws, "error")["message"]


def test_connect_rejects_cross_origin(client, app_env, monkeypatch):
    install_fake_browser(monkeypatch)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
                "/api/ws/connect/x",
                headers={"origin": "http://evil.example"}) as ws:
            ws.receive()
    assert exc.value.code == 4403
    # same-origin (and origin-less non-browser clients) still get through
    with client.websocket_connect(
            "/api/ws/connect/x",
            headers={"origin": "http://testserver"}) as ws:
        assert recv_json(ws)["state"] == "launching"
        ws.send_text(json.dumps({"t": "cancel"}))


def test_connect_hard_timeout(client, app_env, monkeypatch):
    install_fake_browser(monkeypatch)
    monkeypatch.setattr(connect, "MAX_LIFETIME", 0)
    with client.websocket_connect("/api/ws/connect/x") as ws:
        recv_json(ws, "status")
        assert "Timed out" in recv_json(ws, "error")["message"]


def messages_until_frames(ws, frames=3):
    """JSON messages seen while `frames` binary frames go by (≈ a couple of
    idle ticks) — for asserting that something did NOT happen."""
    seen, n = [], 0
    while n < frames:
        msg = ws.receive()
        if msg.get("bytes"):
            n += 1
        elif msg.get("text") is not None:
            seen.append(json.loads(msg["text"]))
    return seen


def test_generic_detection_saves_without_closing(client, app_env, monkeypatch):
    """TensorArt has no known cookie marker → generic detection: a new
    auth-looking cookie/localStorage key AFTER the first input saves
    (non-final) and keeps streaming; page-load cookies and csrf noise never
    trigger it."""
    page, ctx, closed = install_fake_browser(monkeypatch)
    ctx.cookie_list = [{"name": "session_id", "value": "set-on-load"}]  # baseline
    with client.websocket_connect("/api/ws/connect/tensorart") as ws:
        recv_json(ws, "status")
        ws.send_text(json.dumps({"t": "click", "x": 10, "y": 10}))
        # noise that must not count
        ctx.cookie_list.append({"name": "csrf_token", "value": "x"})
        ctx.cookie_list.append({"name": "_ga_session", "value": "x"})
        assert not [m for m in messages_until_frames(ws, 3) if m.get("t") == "saved"]
        assert not (app_env.sessions_dir / "tensorart.json").exists()
        # the real thing: localStorage auth entry appears after login
        page.local_keys.append("firebase:authUser:abc")
        saved = recv_json(ws, "saved")
        assert saved["final"] is False and "Keep going" in saved["message"]
        assert (app_env.sessions_dir / "tensorart.json").is_file()
        # still live: frames keep coming, manual re-save still works
        recv_frame(ws)
        ws.send_text(json.dumps({"t": "save"}))
        assert recv_json(ws, "saved")["final"] is True
    assert closed


def test_known_marker_midjourney_finishes(client, app_env, monkeypatch):
    _page, ctx, _closed = install_fake_browser(monkeypatch)
    with client.websocket_connect("/api/ws/connect/midjourney") as ws:
        recv_json(ws, "status")
        recv_frame(ws)
        ctx.cookie_list.append(
            {"name": "__Host-Midjourney.AuthUserTokenV3_r", "value": "tok"})
        assert recv_json(ws, "saved")["final"] is True
    assert (app_env.sessions_dir / "midjourney.json").is_file()


def test_auth_like_names():
    assert connect._auth_like("access_token")
    assert connect._auth_like("firebase:authUser:x")
    assert connect._auth_like("PHPSESSID")
    assert not connect._auth_like("csrf_token")
    assert not connect._auth_like("_ga_session")
    assert not connect._auth_like("theme")


def test_scrapers_report_auth_kind_and_session_for_all_browser_sites(client, app_env):
    from promptforge import settings_store
    by = {s["name"]: s for s in client.get("/api/scrapers").json()["scrapers"]}
    assert by["lexica"]["auth_kind"] == "none" and by["lexica"]["session_status"] is None
    assert by["civitai"]["auth_kind"] == "api_key"
    assert by["civitai"]["key_configured"] is False
    assert "civitai.com" in by["civitai"]["key_url"]
    for site in ("tensorart", "seaart", "pixai"):      # login optional
        assert by[site]["session_status"] == "missing"
        assert by[site]["session_optional"] is True
        assert by[site]["connectable"] is True
    assert by["midjourney"]["session_optional"] is False
    assert by["x"]["session_optional"] is False
    with db_mod.session_scope() as s:
        settings_store.put(s, "civitai_api_key", "civ-key")
    assert client.get("/api/scrapers").json()["scrapers"]
    by = {s["name"]: s for s in client.get("/api/scrapers").json()["scrapers"]}
    assert by["civitai"]["key_configured"] is True


def test_civitai_test_connection(client, app_env, monkeypatch):
    import httpx
    from promptforge import settings_store
    from promptforge.scrapers.civitai import CivitaiAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") == "Bearer civ-good":
            return httpx.Response(200, json={"items": [], "metadata": {}})
        return httpx.Response(401, json={"error": "Unauthorized"})

    def fake_make_client(self, s, transport=None):
        key = settings_store.get(s, "civitai_api_key")
        return httpx.Client(
            headers={"Authorization": f"Bearer {key}"} if key else {},
            transport=httpx.MockTransport(handler))
    monkeypatch.setattr(CivitaiAdapter, "make_client", fake_make_client)

    r = client.post("/api/scrapers/civitai/test").json()
    assert r["ok"] is False and "No API key" in r["detail"]
    with db_mod.session_scope() as s:
        settings_store.put(s, "civitai_api_key", "civ-bad")
    r = client.post("/api/scrapers/civitai/test").json()
    assert r["ok"] is False and "401" in r["detail"]
    with db_mod.session_scope() as s:
        settings_store.put(s, "civitai_api_key", "civ-good")
    r = client.post("/api/scrapers/civitai/test").json()
    assert r["ok"] is True and "NSFW" in r["detail"]

    # real make_client + an injected dead transport → network failure mode
    monkeypatch.undo()

    def down(request):
        raise httpx.ConnectError("no route")
    with db_mod.session_scope() as s:
        out = CivitaiAdapter().test_connection(s, transport=httpx.MockTransport(down))
    assert out["ok"] is False and "Can't reach" in out["detail"]
    assert client.post("/api/scrapers/lexica/test").status_code == 404


def test_login_url_env_override(monkeypatch):
    assert connect.login_url("x") == "https://x.com/login"
    monkeypatch.setenv("PF_LOGIN_URL_X", "http://127.0.0.1:9/fake")
    assert connect.login_url("x") == "http://127.0.0.1:9/fake"
    assert connect.login_url("nope") is None


# ------------------------------------------------------------- session REST --
def test_session_upload_and_disconnect(client, app_env):
    state = {"cookies": [{"name": "auth_token", "value": "v",
                          "domain": ".x.com", "path": "/"}], "origins": []}
    # mark expired first — a fresh upload must clear it
    with db_mod.session_scope() as s:
        get_adapter("x").get_state(s).state = {"session_expired": True}

    r = client.post("/api/scrapers/x/session",
                    files={"file": ("x.json", json.dumps(state).encode(),
                                    "application/json")})
    assert r.status_code == 200
    assert r.json()["session_status"] == "valid"
    assert json.loads((app_env.sessions_dir / "x.json").read_text()) == state

    # junk and wrong targets rejected
    assert client.post("/api/scrapers/x/session",
                       files={"file": ("x.json", b"not json", "text/plain")}
                       ).status_code == 422
    assert client.post("/api/scrapers/x/session",
                       files={"file": ("x.json", b'{"cookies": "nope"}',
                                       "application/json")}).status_code == 422
    assert client.post("/api/scrapers/civitai/session",
                       files={"file": ("x.json", json.dumps(state).encode(),
                                       "application/json")}).status_code == 404

    r = client.delete("/api/scrapers/x/session")
    assert r.status_code == 200
    assert r.json()["session_status"] == "missing"
    assert not (app_env.sessions_dir / "x.json").exists()
    assert client.delete("/api/scrapers/civitai/session").status_code == 404
