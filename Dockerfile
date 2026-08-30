# PromptForge — single image, multi-stage. amd64, CPU-only, Unraid-ready.

# ---- Stage 1: frontend build -------------------------------------------------
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: runtime --------------------------------------------------------
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PF_DATA_DIR=/data \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# ffmpeg (media pipeline), curl (healthcheck), gosu (PUID/PGID drop), tzdata (TZ)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl gosu tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements-browser.txt ./backend/
RUN pip install -r backend/requirements.txt \
    && pip install -r backend/requirements-browser.txt \
    # Playwright Chromium for the Tier 2 (browser) scrapers; world-readable so
    # the runtime user (PUID) can launch it
    && (crawl4ai-setup || python -m playwright install --with-deps chromium) \
    && chmod -R a+rX /opt/pw-browsers

COPY backend/ ./backend/
COPY companion/ ./companion/
COPY scripts/ ./scripts/
COPY pricing.json ./pricing.json
COPY --from=frontend /fe/dist ./frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5643
VOLUME /data

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=5 \
    CMD curl -fsS http://localhost:5643/api/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "promptforge.main:app", \
     "--host", "0.0.0.0", "--port", "5643", "--app-dir", "/app/backend"]
