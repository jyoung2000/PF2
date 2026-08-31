"""PromptForge FastAPI app: API + WebSockets + built frontend + /media files."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db
from .config import get_config
from .logbus import bus

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    cfg.ensure_dirs()
    db.init_db()
    bus.attach_loop(asyncio.get_running_loop())
    _optional_startup(app)
    bus.info("system", f"PromptForge {__version__} up — data dir {cfg.data_dir}")
    yield
    _optional_shutdown(app)


def _optional_startup(app: FastAPI) -> None:
    """Subsystems added in later phases; each guards its own absence."""
    try:
        from .knowledge import files as kfiles
        kfiles.install_foundation()
    except ImportError:
        pass
    try:
        from . import scheduler
        scheduler.start()
    except ImportError:
        pass
    try:
        import asyncio as _asyncio

        from .integrations import discord_bot
        discord_bot.manager.attach_loop(_asyncio.get_running_loop())
        discord_bot.manager.sync_from_settings()
    except ImportError:
        pass
    try:
        from .pipeline import autopush
        autopush.register_hooks()
    except ImportError:
        pass
    try:
        from .knowledge import engine as kengine
        kengine.register_hooks()
    except ImportError:
        pass
    try:
        from .generation import queue as genqueue
        genqueue.start_worker()
    except ImportError:
        pass


def _optional_shutdown(app: FastAPI) -> None:
    try:
        from . import scheduler
        scheduler.shutdown()
    except ImportError:
        pass
    try:
        from .integrations import discord_bot
        discord_bot.manager.stop()
    except ImportError:
        pass


def create_app() -> FastAPI:
    cfg = get_config()
    app = FastAPI(title="PromptForge", version=__version__, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
    )

    @app.get("/api/health")
    def health():
        db_ok = True
        try:
            db.wal_mode()
        except Exception:
            db_ok = False
        return {
            "status": "ok" if db_ok else "degraded",
            "version": __version__,
            "db": "ok" if db_ok else "error",
            "data_dir": str(cfg.data_dir),
            "ffmpeg": cfg.ffmpeg is not None,
        }

    from .api import posts, scrapers
    app.include_router(posts.router)
    app.include_router(scrapers.router)
    for modname in ("search", "collections", "tags", "settings", "integrations",
                    "knowledge", "studio", "generation", "companion",
                    "models_meta", "ws", "monitoring", "grok"):
        try:
            module = __import__(f"promptforge.api.{modname}", fromlist=["router"])
            app.include_router(module.router)
        except ImportError:
            pass  # router lands in a later phase

    cfg.ensure_dirs()
    app.mount("/media", StaticFiles(directory=cfg.media_dir), name="media")

    if FRONTEND_DIST.is_dir():
        assets = FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            candidate = (FRONTEND_DIST / full_path).resolve()
            if (full_path and candidate.is_file()
                    and candidate.is_relative_to(FRONTEND_DIST)):
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
