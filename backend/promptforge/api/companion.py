"""Companion API (9.1, 9.4): pairing codes, pair/revoke, status, the
authenticated WebSocket the desktop app connects to, and the source-zip
download served from Settings."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import (APIRouter, Depends, HTTPException, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..companion import pairing
from ..companion.manager import hub
from ..db import get_db, session_scope
from ..models import Companion

router = APIRouter(prefix="/api/companion", tags=["companion"])

COMPANION_SRC = Path(__file__).resolve().parents[3] / "companion"


@router.post("/pairing-code")
def pairing_code():
    return pairing.issue_code()


class PairBody(BaseModel):
    code: str
    name: str = "Desktop"


@router.post("/pair")
def pair(body: PairBody, db: Session = Depends(get_db)):
    try:
        return pairing.pair(db, body.code.strip(), body.name.strip())
    except pairing.PairingError as e:
        raise HTTPException(401, str(e))


@router.get("")
def list_companions(db: Session = Depends(get_db)):
    rows = db.execute(select(Companion).order_by(Companion.id)).scalars().all()
    status = hub.status()
    return {
        "companions": [{
            "id": c.id, "name": c.name,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "last_seen": c.last_seen.isoformat() if c.last_seen else None,
        } for c in rows],
        **status,
    }


@router.delete("/{companion_id}")
def revoke(companion_id: int, db: Session = Depends(get_db)):
    if not pairing.revoke(db, companion_id):
        raise HTTPException(404, "Companion not found")
    hub.kick(companion_id)
    return {"revoked": companion_id}


@router.get("/download")
def download_source():
    """The companion app as a source zip (run with python; see README for the
    Windows .exe build)."""
    if not COMPANION_SRC.is_dir():
        raise HTTPException(404, "Companion source not bundled in this build")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(COMPANION_SRC.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts \
                    and f.suffix not in (".pyc",) \
                    and not any(p in ("build", "dist") for p in f.parts):
                zf.write(f, f"promptforge-companion/{f.relative_to(COMPANION_SRC)}")
    return Response(
        content=buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition":
                 'attachment; filename="promptforge-companion.zip"'})


@router.websocket("/ws")
async def companion_ws(ws: WebSocket):
    token = ws.query_params.get("token", "")
    with session_scope() as s:
        companion = pairing.authenticate(s, token)
        if companion is None:
            await ws.close(code=4001)
            return
        companion_id, name = companion.id, companion.name
    await ws.accept()
    import asyncio
    hub.register(ws, companion_id, name, asyncio.get_running_loop())
    # drain any queued analysis jobs now that the GPU is back
    try:
        import threading

        from ..companion.manager import drain_job_queue
        threading.Thread(target=drain_job_queue, daemon=True).start()
    except Exception:
        pass
    try:
        while True:
            data = await ws.receive_json()
            if isinstance(data, dict):
                hub.handle_message(data)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unregister(ws)
