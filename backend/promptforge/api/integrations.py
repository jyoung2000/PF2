"""Integrations API (4.2, 4.5): status for the header, guided-setup test
endpoints (real end-to-end checks), Discord channel listing + invite URL,
per-post push actions, Discord rules + 24h preview."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import settings_store
from ..db import get_db
from ..integrations import baserow, discord_rest, discord_rules
from ..integrations.discord_bot import manager as discord_manager

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _llm_status(s: Session) -> dict:
    provider = settings_store.get(s, "llm_provider")
    if not provider:
        return {"status": "not_configured"}
    try:
        from ..llm.client import provider_status
        return provider_status(s, provider)
    except ImportError:
        return {"status": "configured", "provider": provider}


@router.get("/status")
def status(db: Session = Depends(get_db)):
    br_token = settings_store.get(db, "baserow_token")
    br = {"status": "not_configured"}
    if br_token:
        tested = settings_store.get(db, "baserow_last_test") or {}
        br = {"status": tested.get("status", "configured"),
              "last_tested": tested.get("at")}
    dc = {"status": "not_configured"}
    if settings_store.get(db, "discord_bot_token"):
        tested = settings_store.get(db, "discord_last_test") or {}
        dc = {"status": tested.get("status", "configured"),
              "last_tested": tested.get("at"),
              "gateway": discord_manager.running}
    out = {"baserow": br, "discord": dc, "llm": _llm_status(db)}
    try:
        from ..companion.manager import hub
        out["companion"] = hub.status()
    except ImportError:
        pass
    return out


def _record_test(db: Session, key: str, ok: bool) -> None:
    # on failure the endpoint raises HTTPException, which rolls the request
    # session back — so drop pending work and commit the result explicitly
    if not ok:
        db.rollback()
    settings_store.put(db, key, {
        "status": "connected" if ok else "error",
        "at": datetime.now(timezone.utc).isoformat()})
    if not ok:
        db.commit()


# ------------------------------------------------------------------ Baserow -
@router.post("/baserow/test")
def baserow_test(db: Session = Depends(get_db)):
    client = baserow.client_from_settings(db)
    table_id = settings_store.get(db, "baserow_table_id") or None
    try:
        result = client.test_connection(table_id)
        settings_store.put(db, "baserow_table_id", str(result["table_id"]))
        _record_test(db, "baserow_last_test", True)
        return result
    except baserow.BaserowError as e:
        _record_test(db, "baserow_last_test", False)
        raise HTTPException(400, detail={"step": e.step, "message": str(e)})
    finally:
        client.close()


@router.get("/baserow/tables")
def baserow_tables(db: Session = Depends(get_db)):
    client = baserow.client_from_settings(db)
    try:
        client.check_token()
        return {"tables": client.list_tables()}
    except baserow.BaserowError as e:
        raise HTTPException(400, detail={"step": e.step, "message": str(e)})
    finally:
        client.close()


# ------------------------------------------------------------------ Discord -
@router.post("/discord/test")
def discord_test(db: Session = Depends(get_db)):
    token = settings_store.get(db, "discord_bot_token")
    channel = settings_store.get(db, "discord_channel_id")
    try:
        result = discord_rest.test_connection(token, channel)
        _record_test(db, "discord_last_test", True)
        discord_manager.sync_from_settings()
        return result
    except discord_rest.DiscordError as e:
        _record_test(db, "discord_last_test", False)
        raise HTTPException(400, detail={"step": e.step, "message": str(e)})


@router.get("/discord/channels")
def discord_channels(db: Session = Depends(get_db)):
    token = settings_store.get(db, "discord_bot_token")
    try:
        discord_rest.validate_token(token)
        return {"channels": discord_rest.list_channels(token)}
    except discord_rest.DiscordError as e:
        raise HTTPException(400, detail={"step": e.step, "message": str(e)})


@router.get("/discord/invite")
def discord_invite(db: Session = Depends(get_db)):
    token = settings_store.get(db, "discord_bot_token")
    try:
        app_id = discord_rest.get_application_id(token)
        return {"invite_url": discord_rest.invite_url(app_id)}
    except discord_rest.DiscordError as e:
        raise HTTPException(400, detail={"step": e.step, "message": str(e)})


@router.get("/discord/rules")
def get_discord_rules(db: Session = Depends(get_db)):
    return {"rules": discord_rules.get_rules(db),
            "preview": discord_rules.preview_last_24h(db)}


@router.put("/discord/rules")
def put_discord_rules(rules: dict = Body(...), db: Session = Depends(get_db)):
    clean = {k: v for k, v in rules.items() if k in discord_rules.DEFAULT_RULES}
    merged = discord_rules.get_rules(db)
    merged.update(clean)
    settings_store.put(db, "discord_rules", merged)
    db.flush()
    return {"rules": merged, "preview": discord_rules.preview_last_24h(db)}
