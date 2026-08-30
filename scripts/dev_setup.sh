#!/usr/bin/env bash
# One-command dev setup: backend venv (python3.12) + frontend deps.
# Usage: bash scripts/dev_setup.sh [--with-browser]
set -euo pipefail
cd "$(dirname "$0")/.."

PY=python3.12
command -v "$PY" >/dev/null 2>&1 || PY=python3

echo "==> Backend venv ($($PY --version))"
if [ ! -d backend/.venv ]; then
  "$PY" -m venv backend/.venv
fi
backend/.venv/bin/pip install -q --upgrade pip
backend/.venv/bin/pip install -q -r backend/requirements.txt -r backend/requirements-dev.txt
if [ "${1:-}" = "--with-browser" ]; then
  backend/.venv/bin/pip install -q -r backend/requirements-browser.txt
  backend/.venv/bin/crawl4ai-setup || echo "crawl4ai-setup failed (Chromium download) — Tier 2 dev only"
fi

if [ -d frontend ] && [ -f frontend/package.json ]; then
  echo "==> Frontend deps"
  (cd frontend && npm ci --silent 2>/dev/null || npm install --silent)
fi

echo "==> Done. Run backend: cd backend && .venv/bin/uvicorn promptforge.main:app --port 5643 --reload"
echo "         Run tests:   cd backend && .venv/bin/python -m pytest -q"
