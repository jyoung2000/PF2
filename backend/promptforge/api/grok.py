"""Grok API (X3): test connection, discover creators, curation run, digest."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from .. import settings_store
from ..config import get_config
from ..db import get_db
from ..integrations import grok

router = APIRouter(prefix="/api/grok", tags=["grok"])


def _http_error(e: grok.GrokError) -> HTTPException:
    status = {"auth": 400, "disabled": 409, "budget": 429,
              "rate": 429}.get(e.step, 502)
    return HTTPException(status, detail={"step": e.step, "message": str(e)})


@router.post("/test")
def test(db: Session = Depends(get_db)):
    try:
        return grok.test_connection(db)
    except grok.GrokError as e:
        raise _http_error(e)


def web_session_status() -> dict:
    """Grok Web = a grok.com browser session captured with the in-app connect
    flow (platform "grok"). Distinct from the xAI API key; it authorises no
    API feature."""
    path = get_config().sessions_dir / "grok.json"
    if not path.is_file():
        return {"connected": False, "saved_at": None}
    saved = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return {"connected": True, "saved_at": saved}


@router.delete("/session")
def disconnect_web_session():
    path = get_config().sessions_dir / "grok.json"
    if path.is_file():
        path.unlink()
    return web_session_status()


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return {
        "configured": grok.is_configured(db),
        "web_session": web_session_status(),
        "usage": grok.get_usage(db),
        "curate_budget": settings_store.get(db, "grok_curate_daily_budget"),
        "features": {
            "discover": bool(settings_store.get(db, "grok_discover_enabled")),
            "curate": bool(settings_store.get(db, "grok_curate_enabled")),
            "digest": bool(settings_store.get(db, "grok_digest_enabled")),
        },
    }


class DiscoverBody(BaseModel):
    interest: str


@router.post("/discover")
def discover(body: DiscoverBody):
    interest = body.interest.strip()
    if not interest:
        raise HTTPException(422, "Describe an interest first — e.g. "
                            "“cinematic AI video creators”.")
    try:
        return {"candidates": grok.discover_creators(interest)}
    except grok.GrokError as e:
        raise _http_error(e)


@router.post("/curate/run")
def curate_run():
    try:
        return {"curated": grok.curate_batch()}
    except grok.GrokError as e:
        raise _http_error(e)


@router.get("/digest")
def get_digest(db: Session = Depends(get_db)):
    return {"digest": settings_store.get(db, "grok_last_digest", None)}


@router.post("/digest/run")
def digest_run():
    def _run():
        grok.digest_tick(force=True)
    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}
