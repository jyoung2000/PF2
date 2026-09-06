"""Monitoring API (X2.4): follow-list CRUD, bulk add, run-now, pause/resume."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import monitoring, settings_store
from ..db import get_db
from ..models import Collection, MonitoredAccount, Post

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


def _account_dict(a: MonitoredAccount, db: Session) -> dict:
    total_posts = db.execute(select(func.count(Post.id)).where(
        Post.platform == a.platform,
        func.lower(Post.author) == f"@{a.handle}")).scalar_one()
    collection = db.get(Collection, a.auto_collection_id) if a.auto_collection_id else None
    return {
        "id": a.id,
        "handle": a.handle,
        "display_name": a.display_name,
        "platform": a.platform,
        "added_by": a.added_by,
        "notes": a.notes,
        "active": a.active,
        "last_checked": a.last_checked.isoformat() if a.last_checked else None,
        "last_post_id": a.last_post_id,
        "check_interval": a.check_interval,
        "media_only": a.media_only,
        "auto_tag": a.auto_tag,
        "auto_collection_id": a.auto_collection_id,
        "auto_collection_name": collection.name if collection else None,
        "status": a.status,
        "last_error": a.last_error,
        "last_new": a.last_new,
        "total_posts": total_posts,
        "profile_url": _profile_url(a),
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "evidence": a.evidence or {},
        "creator": _creator_summary(db, a),
    }


def _profile_url(a: MonitoredAccount) -> str | None:
    from ..intel import handles as handle_rules
    return handle_rules.profile_url(a.handle, a.platform or "x")


def _creator_summary(db: Session, a: MonitoredAccount) -> dict | None:
    from ..intel import creators
    c = creators.find(db, a.platform, a.handle)
    if c is None:
        return None
    st = creators.stats_for(db, c)
    return {"id": c.id, "followers": c.followers, "posts": st.get("posts"),
            "avg_engagement": st.get("avg_engagement"), "ai_ratio": st.get("ai_ratio"),
            "prompt_availability": st.get("prompt_availability"),
            "models": [m["family"] for m in st.get("models", [])[:3]],
            "trend": st.get("trend"), "avg_inspiration": st.get("avg_inspiration")}


@router.get("")
def list_accounts(db: Session = Depends(get_db)):
    rows = db.execute(select(MonitoredAccount)
                      .order_by(MonitoredAccount.created_at.desc())).scalars().all()
    from ..intel import handles as handle_rules
    from ..scrapers import all_adapters, get_adapter
    adapter = get_adapter("x")
    session_ok = bool(adapter and adapter.is_configured(db))
    platforms = []
    for name, ad in all_adapters().items():
        can_author = (hasattr(ad, "fetch_account") or hasattr(ad, "fetch_author")
                      or "author" in (getattr(ad, "capabilities", None) or frozenset()))
        if not can_author:
            continue
        platforms.append({
            "name": name, "label": ad.label, "tier": ad.tier,
            "configured": bool(ad.is_configured(db)),
            "needs_setup": ad.needs_setup_reason(db) if hasattr(ad, "needs_setup_reason") else None,
            "experimental": bool(getattr(ad, "experimental", False)),
            "profile_example": handle_rules.profile_url("creator", name)})
    return {
        "accounts": [_account_dict(a, db) for a in rows],
        "x_session_ok": session_ok,          # legacy field, kept for the old UI
        "platforms": platforms,
        "defaults": {
            "interval": settings_store.get(db, "monitor_default_interval"),
            "auto_tag": settings_store.get(db, "monitor_default_tag"),
        },
    }


class BulkAddBody(BaseModel):
    evidence: dict | None = None      # discovery claim (review-before-add, I5/I10)
    text: str
    added_by: str = "manual"
    notes: str | None = None
    platform: str = "x"               # I10: creators live on any source


@router.post("/accounts")
def add_accounts(body: BulkAddBody, db: Session = Depends(get_db)):
    from ..intel import handles as handle_rules
    from ..scrapers import get_adapter as _get_adapter
    platform = (body.platform or "x").lower()
    if _get_adapter(platform) is None:
        raise HTTPException(422, f"Unknown platform '{platform}'.")
    # a pasted profile URL may name its own platform — trust the URL
    detected = {handle_rules.detect_platform(tok)
                for tok in (body.text or "").split() if tok.strip()} - {None}
    if len(detected) == 1:
        platform = detected.pop()
    handles, rejected = monitoring.parse_bulk(body.text, platform)
    if not handles and not rejected:
        raise HTTPException(422, "Paste at least one @handle or profile URL.")
    default_interval = int(settings_store.get(db, "monitor_default_interval") or 60)
    default_tag = (settings_store.get(db, "monitor_default_tag") or "").strip() or None
    created, existing = [], []
    for handle in handles:
        dup = db.execute(select(MonitoredAccount).where(
            MonitoredAccount.platform == platform,
            MonitoredAccount.handle == handle)).scalar_one_or_none()
        if dup is not None:
            existing.append(handle)
            continue
        added_by = body.added_by if body.added_by in ("manual", "grok", "search") else "manual"
        account = MonitoredAccount(
            handle=handle, platform=platform, added_by=added_by,
            notes=body.notes, check_interval=default_interval,
            # a discovery claim (Grok OR PF2's own source search) is evidence
            # only until a real poll verifies it (D71/I10)
            evidence=({**(body.evidence or {}), "source": added_by,
                       "verified": added_by == "search" and bool(body.evidence)}
                      if added_by != "manual" else {}),
            auto_tag=default_tag)
        db.add(account)
        db.flush()
        created.append(_account_dict(account, db))
    return {"created": created, "already_monitored": existing,
            "rejected": rejected, "platform": platform}


class AccountPatch(BaseModel):
    active: bool | None = None
    check_interval: int | None = None
    media_only: bool | None = None
    auto_tag: str | None = None
    auto_collection_id: int | None = None
    notes: str | None = None
    display_name: str | None = None


@router.patch("/accounts/{account_id}")
def patch_account(account_id: int, body: AccountPatch,
                  db: Session = Depends(get_db)):
    a = db.get(MonitoredAccount, account_id)
    if a is None:
        raise HTTPException(404, "Account not found")
    if body.active is not None:
        a.active = body.active
    if body.check_interval is not None:
        a.check_interval = max(5, body.check_interval)
    if body.media_only is not None:
        a.media_only = body.media_only
    if body.auto_tag is not None:
        a.auto_tag = body.auto_tag.strip() or None
    if body.auto_collection_id is not None:
        a.auto_collection_id = body.auto_collection_id or None
    if body.notes is not None:
        a.notes = body.notes
    if body.display_name is not None:
        a.display_name = body.display_name
    db.flush()
    return _account_dict(a, db)


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    a = db.get(MonitoredAccount, account_id)
    if a is None:
        raise HTTPException(404, "Account not found")
    db.delete(a)  # collected posts stay in the library
    db.flush()
    return {"deleted": account_id}


@router.post("/accounts/{account_id}/run")
def run_now(account_id: int, db: Session = Depends(get_db)):
    a = db.get(MonitoredAccount, account_id)
    if a is None:
        raise HTTPException(404, "Account not found")
    from ..scrapers import get_adapter
    adapter = get_adapter("x")
    if not (adapter and adapter.is_configured(db)):
        raise HTTPException(409, "X login session missing — capture it first "
                                 "(Settings → X.com source).")
    monitoring.run_account_async(account_id)
    return {"started": True}


@router.post("/pause-all")
def pause_all():
    return {"updated": monitoring.set_all_active(False), "active": False}


@router.post("/resume-all")
def resume_all():
    return {"updated": monitoring.set_all_active(True), "active": True}
