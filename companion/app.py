#!/usr/bin/env python3
"""PromptForge Companion — desktop GPU bridge (9.3).

Connects OUTBOUND over an authenticated WebSocket to your PromptForge server
and proxies your local Ollama (http://localhost:11434) to it — model list,
generate and chat calls ONLY. No file access, no shell, nothing else.

Quick start (from source):
    pip install -r requirements.txt
    python app.py --server http://TOWER:5643 --code 123456
The pairing token is stored next to this file (companion_token.json) so later
runs just need:  python app.py --server http://TOWER:5643

Flags: --headless (no tray icon), --ollama URL, --name "My PC".
Windows .exe: see build_companion.ps1 (PyInstaller one-liner).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from collections import deque
from pathlib import Path

import httpx

TOKEN_FILE = Path(__file__).resolve().parent / "companion_token.json"
ALLOWED_METHODS = {"ollama.tags": ("GET", "/api/tags"),
                   "ollama.chat": ("POST", "/api/chat"),
                   "ollama.generate": ("POST", "/api/generate")}
RECONNECT_MIN_S, RECONNECT_MAX_S = 3, 60


class MiniLog:
    def __init__(self, size: int = 300):
        self.lines: deque[str] = deque(maxlen=size)

    def add(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        self.lines.append(line)
        print(line, flush=True)


class CompanionCore:
    """All logic, tray-free — unit-testable and usable with --headless."""

    def __init__(self, server: str, token: str, ollama: str, name: str,
                 log: MiniLog | None = None,
                 ollama_transport: httpx.BaseTransport | None = None):
        self.server = server.rstrip("/")
        self.token = token
        self.ollama = ollama.rstrip("/")
        self.name = name
        self.log = log or MiniLog()
        self.connected = False
        self.models: list[str] = []
        self.stop_event = asyncio.Event()
        kw: dict = {"timeout": 600}
        if ollama_transport is not None:
            kw["transport"] = ollama_transport
        self.http = httpx.AsyncClient(**kw)

    # ---- ollama proxy (the ONLY thing the companion does) ------------------
    async def handle_request(self, method: str, payload: dict) -> dict:
        if method not in ALLOWED_METHODS:
            raise ValueError(f"method '{method}' not allowed")
        verb, path = ALLOWED_METHODS[method]
        url = f"{self.ollama}{path}"
        if verb == "GET":
            resp = await self.http.get(url)
        else:
            body = dict(payload or {})
            body["stream"] = False  # keep the bridge simple + robust
            resp = await self.http.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    async def fetch_models(self) -> list[str]:
        try:
            data = await self.handle_request("ollama.tags", {})
            self.models = [m.get("name", "") for m in data.get("models", [])]
        except Exception as e:
            self.log.add(f"ollama unreachable at {self.ollama}: {e}")
            self.models = []
        return self.models

    # ---- websocket loop ----------------------------------------------------
    def ws_url(self) -> str:
        base = self.server.replace("http://", "ws://").replace("https://", "wss://")
        return f"{base}/api/companion/ws?token={self.token}"

    async def run(self) -> None:
        import websockets
        backoff = RECONNECT_MIN_S
        while not self.stop_event.is_set():
            try:
                self.log.add(f"connecting to {self.server} …")
                async with websockets.connect(self.ws_url(),
                                              max_size=32 * 1024 * 1024) as ws:
                    self.connected = True
                    backoff = RECONNECT_MIN_S
                    await self.fetch_models()
                    await ws.send(json.dumps({"t": "hello", "name": self.name,
                                              "ollama_models": self.models}))
                    self.log.add(f"connected — {len(self.models)} Ollama model(s)")
                    async for raw in ws:
                        await self._on_message(ws, raw)
            except asyncio.CancelledError:
                break
            except Exception as e:
                code = getattr(e, "code", None) or getattr(e, "rcvd", None)
                if "4001" in str(code) or "4001" in str(e):
                    self.log.add("server rejected the token — re-pair with a "
                                 "fresh code from Settings → Companion")
                    break
                self.log.add(f"disconnected ({type(e).__name__}: {e}) — "
                             f"retrying in {backoff}s")
            finally:
                self.connected = False
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(RECONNECT_MAX_S, backoff * 2)

    async def _on_message(self, ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        msg_type = msg.get("t")
        if msg_type == "ping":
            await ws.send(json.dumps({"t": "pong"}))
            return
        if msg_type != "request":
            return
        req_id = msg.get("id")
        method = msg.get("method", "")
        self.log.add(f"→ {method}")
        try:
            data = await self.handle_request(method, msg.get("payload") or {})
            await ws.send(json.dumps({"t": "result", "id": req_id,
                                      "ok": True, "data": data}))
        except Exception as e:
            await ws.send(json.dumps({"t": "result", "id": req_id, "ok": False,
                                      "error": f"{type(e).__name__}: {e}"}))
            self.log.add(f"✗ {method}: {e}")


# ------------------------------------------------------------- pairing ------
def pair(server: str, code: str, name: str) -> str:
    resp = httpx.post(f"{server.rstrip('/')}/api/companion/pair",
                      json={"code": code, "name": name}, timeout=20)
    if resp.status_code == 401:
        raise SystemExit("Pairing failed: " + resp.json().get("detail", "bad code"))
    resp.raise_for_status()
    token = resp.json()["token"]
    TOKEN_FILE.write_text(json.dumps({"server": server, "token": token,
                                      "name": name}))
    print(f"✓ Paired with {server} — token stored in {TOKEN_FILE.name}")
    return token


def load_token(server: str | None) -> tuple[str | None, str | None]:
    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text())
            return data.get("token"), server or data.get("server")
        except ValueError:
            pass
    return None, server


# ---------------------------------------------------------------- tray ------
def run_tray(core: CompanionCore, loop: asyncio.AbstractEventLoop) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("pystray/Pillow not installed — running headless "
              "(pip install pystray pillow for the tray icon)")
        return

    def make_icon(connected: bool) -> "Image.Image":
        img = Image.new("RGBA", (64, 64), (14, 15, 18, 255))
        d = ImageDraw.Draw(img)
        color = (80, 220, 130, 255) if connected else (120, 120, 130, 255)
        d.ellipse([14, 14, 50, 50], fill=(255, 106, 61, 255))
        d.ellipse([40, 40, 58, 58], fill=color)
        return img

    def start_with_windows(icon, item) -> None:
        if sys.platform != "win32":
            core.log.add("start-with-Windows is a Windows-only toggle")
            return
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_ALL_ACCESS)
        name = "PromptForgeCompanion"
        try:
            winreg.QueryValueEx(key, name)
            winreg.DeleteValue(key, name)
            core.log.add("start with Windows: OFF")
        except FileNotFoundError:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, sys.argv[0])
            core.log.add("start with Windows: ON")
        winreg.CloseKey(key)

    def show_log(icon, item) -> None:
        print("\n".join(core.lines_snapshot()))

    core.lines_snapshot = lambda: list(core.log.lines)  # type: ignore[attr-defined]

    def quit_app(icon, item) -> None:
        loop.call_soon_threadsafe(core.stop_event.set)
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: ("● connected to " + core.server)
                         if core.connected else "○ disconnected",
                         None, enabled=False),
        pystray.MenuItem(lambda item: f"Ollama models: {len(core.models)}",
                         None, enabled=False),
        pystray.MenuItem("Start with Windows (toggle)", start_with_windows),
        pystray.MenuItem("Show log in console", show_log),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("PromptForge Companion", make_icon(False),
                        "PromptForge Companion", menu)

    def refresher():
        while icon.visible if hasattr(icon, "visible") else True:
            icon.icon = make_icon(core.connected)
            time.sleep(3)

    threading.Thread(target=refresher, daemon=True).start()
    icon.run()


# ---------------------------------------------------------------- main ------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--server", help="PromptForge URL, e.g. http://TOWER:5643")
    parser.add_argument("--code", help="6-digit pairing code from Settings → Companion")
    parser.add_argument("--name", default=None, help="how this PC appears in Settings")
    parser.add_argument("--ollama", default="http://localhost:11434")
    parser.add_argument("--headless", action="store_true", help="no tray icon")
    args = parser.parse_args()

    import socket
    name = args.name or socket.gethostname() or "Desktop"

    token, server = load_token(args.server)
    if args.code:
        if not args.server:
            print("--code needs --server", file=sys.stderr)
            return 2
        token = pair(args.server, args.code.strip(), name)
        server = args.server
    if not token or not server:
        print("Not paired yet. Get a code from PromptForge Settings → "
              "Companion, then run:\n"
              "  python app.py --server http://YOUR-SERVER:5643 --code 123456",
              file=sys.stderr)
        return 2

    core = CompanionCore(server, token, args.ollama, name)
    loop = asyncio.new_event_loop()

    if args.headless:
        try:
            loop.run_until_complete(core.run())
        except KeyboardInterrupt:
            pass
        return 0

    runner = threading.Thread(
        target=lambda: loop.run_until_complete(core.run()), daemon=True)
    runner.start()
    run_tray(core, loop)
    loop.call_soon_threadsafe(core.stop_event.set)
    runner.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
