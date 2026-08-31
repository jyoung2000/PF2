"""Phase X5 integration: the in-app connect flow end-to-end with a REAL
headless Chromium against a local stand-in login page (D46 — no live X here).

Drives the actual WS protocol: click into the page, type through forwarded
key events, press Enter; the page sets an ``auth_token`` cookie exactly like
X does on login, the manager auto-detects it and writes the storage_state.

Skips cleanly where the Playwright package isn't installed (D5 — the core
suite never needs the browser stack)."""
import http.server
import json
import os
import threading

import pytest

pytest.importorskip("playwright.async_api")

# the Docker image keeps browsers here too (Dockerfile ENV), so this default
# is correct in-container and on this build host alike
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")

LOGIN_PAGE = b"""<!doctype html><title>stand-in login</title>
<input id="u" style="position:fixed;inset:0;font-size:40px" autocomplete="off">
<script>
document.getElementById('u').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.value === 'hunter2') {
    document.cookie = 'auth_token=integration-ok; path=/';
    document.title = 'logged-in';
  }
});
</script>"""


class _Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(LOGIN_PAGE)

    def log_message(self, *a):
        pass


@pytest.fixture()
def login_server():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Page)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/login.html"
    httpd.shutdown()


def test_real_chromium_connect_flow(client, app_env, login_server, monkeypatch):
    monkeypatch.setenv("PF_LOGIN_URL_X", login_server)
    if os.path.exists("/opt/pw-browsers/chromium"):
        os.environ.setdefault("PF_CHROMIUM_PATH", "/opt/pw-browsers/chromium")

    saw_frame = False
    with client.websocket_connect("/api/ws/connect/x") as ws:
        # wait for the live stream, proving Chromium is up and rendering
        for _ in range(200):
            msg = ws.receive()
            if msg.get("bytes"):
                saw_frame = True
                break
            if msg.get("text"):
                data = json.loads(msg["text"])
                assert data.get("t") != "error", data
        assert saw_frame, "no screencast frame arrived"

        # log in like a human: click the field, type the password, hit Enter
        ws.send_text(json.dumps({"t": "click", "x": 640, "y": 400}))
        for ch in "hunter2":
            ws.send_text(json.dumps({"t": "text", "text": ch}))
        ws.send_text(json.dumps({"t": "key", "key": "Enter"}))

        saved = False
        for _ in range(400):
            msg = ws.receive()
            if msg.get("text"):
                data = json.loads(msg["text"])
                assert data.get("t") != "error", data
                if data.get("t") == "saved":
                    saved = True
                    break
        assert saved, "session was never auto-saved"

    state = json.loads((app_env.sessions_dir / "x.json").read_text())
    names = {c["name"]: c["value"] for c in state["cookies"]}
    assert names.get("auth_token") == "integration-ok"
