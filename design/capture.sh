#!/usr/bin/env bash
# Regenerate design/preview/ — the browsable static copy of the container GUI.
#
# Builds the frontend, seeds a throwaway demo library, serves it with the real
# FastAPI app on :5643, captures every screen, then stops the server. The
# capture is whatever the app renders, so run this after any GUI change.
#
#   bash design/capture.sh [data_dir]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${1:-${TMPDIR:-/tmp}/promptforge-preview}"
PORT=5643
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "backend venv missing — run bash scripts/dev_setup.sh first" >&2; exit 1; }

echo "→ building the frontend"
(cd "$ROOT/frontend" && npm run build >/dev/null)

echo "→ seeding a demo library in $DATA_DIR"
rm -rf "$DATA_DIR"
PF_DISABLE_SCHEDULER=1 "$PY" "$ROOT/design/preview_seed.py" library "$DATA_DIR"

echo "→ starting the app on :$PORT"
( cd "$ROOT/backend" && PF_DATA_DIR="$DATA_DIR" PF_DISABLE_SCHEDULER=1 PF_DISABLE_GEN_WORKER=1 \
  exec .venv/bin/uvicorn promptforge.main:app --host 127.0.0.1 --port "$PORT" ) \
  > "$DATA_DIR/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break
  sleep 0.5
done

"$PY" "$ROOT/design/preview_seed.py" film "http://127.0.0.1:$PORT"

echo "→ capturing every screen"
node "$ROOT/design/capture.mjs" "http://127.0.0.1:$PORT" "$ROOT/design/preview/"

echo "✓ design/preview/index.html is up to date"
