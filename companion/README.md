# PromptForge Companion — desktop GPU bridge

Bridges your desktop's Ollama into your PromptForge server so the knowledge
engine, technique tagging, template generation and Enhance run FREE on your
GPU. Outbound-only WebSocket: no port forwarding, works over LAN or Tailscale.
Proxies Ollama endpoints ONLY (tags / generate / chat) — no file access, no shell.

## Run from source (any OS)
    pip install -r requirements.txt
    python app.py --server http://TOWER:5643 --code 123456   # first run: pair
    python app.py                                            # later runs

`--headless` skips the tray icon. The pairing token lands in
`companion_token.json` next to the script.

## Windows .exe
Build locally: `powershell -File build_companion.ps1` → `dist\PromptForgeCompanion.exe`
(or use the `build-companion-exe` GitHub Actions workflow and download the artifact).
