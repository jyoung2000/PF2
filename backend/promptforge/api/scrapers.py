"""Scrapers API: adapter cards for the dashboard + run-now + enable/interval
+ login-session install/remove for browser sites (X5)."""
from __future__ import annotations

import json
import threading

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..logbus import bus
from ..scrapers import all_adapters, get_adapter

router = APIRouter(prefix="/api/scrapers", tags=["scrapers"])

MAX_SESSION_BYTES = 2 * 1024 * 1024


def _adapter_info(adapter, s: Session) -> dict:
    st = adapter.get_state(s)
    health = adapter.health(s)
    next_run = None
    try:
        from .. import scheduler
        next_run = scheduler.next_run_time(adapter.name)
    except Exception:
        pass
    session_status = None
    if getattr(adapter, "requires_auth", False) and hasattr(adapter, "session_status"):
        session_status = adapter.session_status(s)
    return {
        "name": adapter.name,
        "label": adapter.label,
        "session_status": session_status,
        "tier": adapter.tier,
        "experimental": adapter.experimental,
        "requires_auth": adapter.requires_auth,
        "status": health["status"],
        "status_detail": health["detail"],
        "enabled": st.enabled,
        "interval_minutes": st.interval_minutes,
        "min_interval_minutes": adapter.min_interval_minutes,
        "last_run_at": st.last_run_at.isoformat() if st.last_run_at else None,
        "last_status": st.last_status,
        "last_error": st.last_error,
        "last_found": st.last_found,
        "last_new": st.last_new,
        "next_run_at": next_run,
        "running": st.last_status == "running",
    }


@router.get("")
def list_scrapers(db: Session = Depends(get_db)):
    return {"scrapers": [_adapter_info(a, db) for a in all_adapters().values()]}


@router.post("/{name}/run")
def run_now(name: str, db: Session = Depends(get_db)):
    adapter = get_adapter(name)
    if adapter is None:
        raise HTTPException(404, f"No adapter named '{name}'")
    if not adapter.is_configured(db):
        raise HTTPException(
            409, adapter.needs_setup_reason(db) or "Adapter needs setup first")
    try:
        from .. import scheduler
        started = scheduler.trigger_run(name)
    except ImportError:
        started = None
    if started is None:
        t = threading.Thread(target=_run_direct, args=(name,), daemon=True)
        t.start()
        started = True
    if not started:
        raise HTTPException(409, "A scrape run is already in progress — try again shortly")
    bus.info(f"scraper.{name}", "manual run requested")
    return {"started": True}


def _run_direct(name: str) -> None:
    from ..scrapers.runner import run_scraper
    run_scraper(name, manual=True)


def _browser_adapter_or_404(name: str):
    adapter = get_adapter(name)
    if adapter is None or not hasattr(adapter, "storage_state_path"):
        raise HTTPException(404, f"'{name}' is not a browser-login site")
    return adapter


@router.post("/{name}/session")
async def upload_session(name: str, file: UploadFile, db: Session = Depends(get_db)):
    """Install a Playwright storage_state JSON (exported by capture_login.py
    or the in-app connect flow on another box) as this site's login session."""
    adapter = _browser_adapter_or_404(name)
    raw = await file.read()
    if len(raw) > MAX_SESSION_BYTES:
        raise HTTPException(422, "That file is too large to be a session export.")
    try:
        state = json.loads(raw)
        assert isinstance(state, dict) and isinstance(state.get("cookies"), list)
    except (ValueError, AssertionError):
        raise HTTPException(
            422, "That doesn't look like a Playwright storage_state export — "
                 "expected JSON with a top-level \"cookies\" list.")
    from ..scrapers.connect import save_storage_state_sync
    save_storage_state_sync(name, state)
    db.expire_all()
    bus.info(f"scraper.{name}", "login session installed via upload")
    return _adapter_info(adapter, db)


@router.delete("/{name}/session")
def delete_session(name: str, db: Session = Depends(get_db)):
    """Disconnect: forget the stored login session (posts are untouched)."""
    adapter = _browser_adapter_or_404(name)
    path = adapter.storage_state_path()
    if path.is_file():
        path.unlink()
    st = adapter.get_state(db)
    state = dict(st.state or {})
    if state.pop("session_expired", None) is not None:
        st.state = state
        db.flush()
    bus.info(f"scraper.{name}", "login session removed")
    return _adapter_info(adapter, db)


class ScraperPatch(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None


@router.patch("/{name}")
def patch_scraper(name: str, body: ScraperPatch, db: Session = Depends(get_db)):
    adapter = get_adapter(name)
    if adapter is None:
        raise HTTPException(404, f"No adapter named '{name}'")
    st = adapter.get_state(db)
    if body.enabled is not None:
        st.enabled = body.enabled
    if body.interval_minutes is not None:
        st.interval_minutes = max(adapter.min_interval_minutes, body.interval_minutes)
    db.flush()
    try:
        from .. import scheduler
        scheduler.reschedule(name)
    except Exception:
        pass
    return _adapter_info(adapter, db)
