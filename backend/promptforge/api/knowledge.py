"""Knowledge engine API (6.9): technique taxonomy, knowledge file browsing,
learning controls, LLM provider test, .pfpack export/import."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import settings_store
from ..aliases import display_family
from ..db import get_db
from ..knowledge import engine, files, packs, techniques
from ..llm import client as llm_client

router = APIRouter(prefix="/api", tags=["knowledge"])


@router.get("/techniques")
def list_techniques():
    return {"techniques": techniques.all_slugs()}


@router.get("/knowledge")
def overview(db: Session = Depends(get_db)):
    cfg_dir = files.get_config().knowledge_dir
    models = []
    for path in sorted((cfg_dir / "models").glob("*.md")):
        fm, _body = files.read_md(path)
        family = fm.get("family") or path.stem
        models.append({
            "family": family,
            "label": display_family(family),
            "size_bytes": path.stat().st_size,
            "updated": fm.get("updated"),
            "analyzed_at": fm.get("analyzed_at"),
        })
    styles = []
    for path in sorted((cfg_dir / "styles").glob("collection-*.md")):
        fm, _body = files.read_md(path)
        styles.append({
            "collection_id": fm.get("collection_id"),
            "collection": fm.get("collection") or path.stem,
            "size_bytes": path.stat().st_size,
            "updated": fm.get("updated"),
        })
    foundation = files.foundation_path()
    provider = settings_store.get(db, "llm_provider")
    return {
        "foundation": {
            "exists": foundation.exists(),
            "size_bytes": foundation.stat().st_size if foundation.exists() else 0,
        },
        "models": models,
        "styles": styles,
        "llm": {
            "provider": provider,
            "usage": llm_client.get_usage(db),
            "budget": settings_store.get(db, "llm_daily_budget"),
            "budget_applies": provider not in llm_client.FREE_PROVIDERS,
        },
    }


@router.get("/knowledge/foundation")
def get_foundation():
    path = files.foundation_path()
    if not path.exists():
        files.install_foundation()
    return {"markdown": path.read_text(encoding="utf-8")}


@router.get("/knowledge/models/{family}")
def get_model_file(family: str):
    path = files.model_file_path(family)
    if not path.exists():
        raise HTTPException(404, f"No knowledge file for '{family}' yet — it "
                                 "appears after the first post for this family.")
    return {"markdown": path.read_text(encoding="utf-8"),
            "family": family, "label": display_family(family)}


@router.get("/knowledge/styles/{collection_id}")
def get_style_file(collection_id: int):
    path = files.style_file_path(collection_id)
    if not path.exists():
        result = engine.refresh_style_profile(collection_id, use_llm=False)
        if result is None:
            raise HTTPException(404, "Collection not found")
    return {"markdown": path.read_text(encoding="utf-8")}


@router.post("/knowledge/styles/{collection_id}/refresh")
def refresh_style(collection_id: int):
    result = engine.refresh_style_profile(collection_id)
    if result is None:
        raise HTTPException(404, "Collection not found")
    return {"refreshed": True}


@router.post("/knowledge/learn-now")
def learn_now():
    def _run():
        try:
            engine.scheduled_learning_pass()
        except Exception as e:
            from ..logbus import bus
            bus.error("knowledge", f"manual learning pass failed: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}


@router.post("/knowledge/llm/test")
def llm_test(db: Session = Depends(get_db)):
    try:
        client = llm_client.build_client(db)
    except llm_client.LLMNotConfigured as e:
        raise HTTPException(400, str(e))
    result = client.test()
    if not result.get("ok"):
        raise HTTPException(400, result.get("detail", "LLM test failed"))
    return result


@router.get("/knowledge/pack/export")
def export_pack(family: str | None = None, collection_id: int | None = None,
                thumbs: bool = True):
    try:
        fname, data = packs.export_pack(family or None, collection_id,
                                        include_thumbs=thumbs)
    except packs.PackError as e:
        raise HTTPException(400, str(e))
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition":
                             f'attachment; filename="{fname}"'})


@router.post("/knowledge/pack/import")
async def import_pack(file: UploadFile):
    data = await file.read()
    try:
        return packs.import_pack(data)
    except packs.PackError as e:
        raise HTTPException(400, str(e))
