"""Generation worker (8.4, D14): in-process queue thread — submit → poll →
download → ingest (origin=generated) → learning feedback → spend totals.
Provider errors surface with specifics; a failed job is never resubmitted
automatically (no double-charge)."""
from __future__ import annotations

import queue
import threading
import time

import httpx
from sqlalchemy import select

from .. import settings_store
from ..db import session_scope
from ..logbus import bus
from ..models import Collection, CollectionPost, Generation, Template
from ..scrapers.base import ScrapedPost
from . import router

POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 15 * 60

_queue: "queue.Queue[int]" = queue.Queue()
_worker: threading.Thread | None = None
_started = threading.Event()


def enqueue(generation_id: int) -> None:
    _queue.put(generation_id)


def start_worker() -> None:
    global _worker
    import os
    if os.environ.get("PF_DISABLE_GEN_WORKER") == "1":
        return
    if _worker is not None and _worker.is_alive():
        return
    _started.set()
    # crash recovery: re-enqueue jobs that never finished
    try:
        with session_scope() as s:
            for (gid,) in s.execute(select(Generation.id).where(
                    Generation.status.in_(["queued", "running"]))):
                _queue.put(gid)
    except Exception:
        pass
    _worker = threading.Thread(target=_run_loop, daemon=True,
                               name="generation-worker")
    _worker.start()


def _run_loop() -> None:
    while _started.is_set():
        try:
            gid = _queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            process_generation(gid)
        except Exception as e:
            bus.error("generation", f"job {gid} crashed: {type(e).__name__}: {e}")
            _fail(gid, f"internal error: {e}")


def _fail(gid: int, message: str) -> None:
    from ..models import utcnow
    with session_scope() as s:
        g = s.get(Generation, gid)
        if g is not None:
            g.status = "failed"
            g.error = message[:1000]
            g.finished_at = utcnow()
    bus.error("generation", f"#{gid} failed — {message}")
    _notify_film(gid, "failed")


def _notify_film(gid: int, status: str) -> None:
    """Film Studio takes ride this queue (S3): tell them how their
    generation ended. Guarded so the library never depends on film."""
    try:
        with session_scope() as s:
            g = s.get(Generation, gid)
            params = (g.params or {}) if g is not None else {}
            take_id, asset_id = params.get("_film_take_id"), params.get("_film_asset_id")
        if take_id:
            from ..film import takes as film_takes
            film_takes.on_generation(gid, status)
        elif asset_id:
            from ..film import asset_gen
            asset_gen.on_generation(gid, status)
    except Exception as e:  # noqa: BLE001 — never break the worker over a hook
        bus.warn("film", f"take hook for generation {gid} failed: {e}")


def process_generation(gid: int) -> None:
    from ..models import utcnow
    with session_scope() as s:
        g = s.get(Generation, gid)
        if g is None or g.status in ("succeeded", "failed"):
            return
        g.status = "running"
        provider_name = g.provider
        model_id = g.provider_model_id
        prompt = g.prompt or ""
        params = dict(g.params or {})
        family = g.model_family
        provider = router.get_provider(provider_name)
        if provider is None:
            _fail(gid, f"unknown provider '{provider_name}'")
            return
        key = provider.get_key(s)
        if not key:
            _fail(gid, f"{provider_name} key missing — reconnect it in Settings")
            return
    kind = router.kind_of(family) if family else "image"
    negative = params.pop("_negative", None)

    bus.info("generation", f"#{gid} submitting to {provider_name} ({model_id})")
    from .base import ProviderError
    try:
        job_ref = provider.submit(key, model_id, prompt, negative, params, kind)
    except ProviderError as e:
        _fail(gid, str(e))
        return

    bus.info("generation", f"#{gid} {provider_name} job {job_ref} — polling")
    deadline = time.time() + POLL_TIMEOUT_S
    output_url = None
    while time.time() < deadline:
        result = provider.poll(key, model_id, job_ref)
        status = result.get("status")
        if status == "succeeded":
            output_url = result.get("output_url")
            break
        if status == "failed":
            _fail(gid, result.get("error") or "provider reported failure")
            return
        time.sleep(POLL_INTERVAL_S)
    if not output_url:
        _fail(gid, f"timed out after {POLL_TIMEOUT_S//60} min waiting on "
                   f"{provider_name}")
        return

    bus.info("generation", f"#{gid} downloading output")
    sp = ScrapedPost(
        platform="promptforge",
        platform_post_id=f"gen-{gid}",
        media_url=output_url,
        media_type="video" if kind == "video" else "image",
        prompt=prompt,
        negative_prompt=negative,
        model_name=family,
        params={k: v for k, v in params.items() if not k.startswith("_")},
        source_url=None,
        author="you",
    )
    from ..pipeline.ingest import ingest_one
    client = httpx.Client(timeout=300, follow_redirects=True)
    try:
        post_id = ingest_one(sp, client, origin="generated")
    except Exception as e:
        _fail(gid, f"output download/ingest failed: {e}")
        return
    finally:
        client.close()

    with session_scope() as s:
        g = s.get(Generation, gid)
        g.status = "succeeded"
        g.output_post_id = post_id
        g.cost_actual = g.cost_estimate
        g.finished_at = utcnow()
        collection_id = _find_collection(s, g)
        template_name = None
        if g.saved_prompt_id:
            from ..models import SavedPrompt
            sp_row = s.get(SavedPrompt, g.saved_prompt_id)
            if sp_row and sp_row.template_id:
                t = s.get(Template, sp_row.template_id)
                template_name = t.name if t else None
        # spend totals per provider (visible in Settings)
        spend = settings_store.get(s, "gen_spend", None) or {}
        spend[provider_name] = round(
            float(spend.get(provider_name, 0)) + float(g.cost_estimate or 0), 4)
        settings_store.put(s, "gen_spend", spend)
        # optionally add to the source collection
        if collection_id and post_id and settings_store.get(
                s, "auto_add_generated_to_collection"):
            exists = s.execute(select(CollectionPost).where(
                CollectionPost.collection_id == collection_id,
                CollectionPost.post_id == post_id)).first()
            c = s.get(Collection, collection_id)
            if not exists and c is not None:
                s.add(CollectionPost(collection_id=collection_id,
                                     post_id=post_id))
    bus.info("generation", f"#{gid} succeeded → post {post_id}")
    _notify_film(gid, "succeeded")

    # learning feedback loop — every generation is a learning event
    try:
        from ..knowledge import engine as kengine
        kengine.generation_event(post_id, family, prompt, "generated",
                                 collection_id, template_name)
    except Exception as e:
        bus.warn("generation", f"learning feedback failed: {e}")


def _find_collection(s, g: Generation) -> int | None:
    if (g.params or {}).get("_collection_id"):
        return int(g.params["_collection_id"])
    if g.saved_prompt_id:
        from ..models import SavedPrompt
        sp = s.get(SavedPrompt, g.saved_prompt_id)
        if sp is not None:
            return sp.collection_id
    return None
