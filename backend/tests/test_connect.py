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

    async def goto(self, url, **kw):
        self.goto_urls.append(url)

    async def screenshot(self, **kw):
        return b"\xff\xd8fake-jpeg"


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
