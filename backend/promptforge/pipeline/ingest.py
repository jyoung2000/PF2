"""Core pipeline: adapter → normalize → dedupe → download media → extract
embedded metadata (BEFORE compression) → compress → store → learn/auto-push
hooks. Per-post failures are logged and skipped; a run never crashes the app."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from .. import fts, settings_store
from ..aliases import normalize_model
from ..config import get_config
from ..db import session_scope
from ..intel import dedupe, provenance, scoring
from ..intel import queue as intel_queue
from ..logbus import bus
from ..models import Creator, EngagementSnapshot, Post
from ..scrapers.base import ScrapedPost
from . import hooks, media, metadata

# assertion source → the coarse model_source vocabulary the UI/search use
_MODEL_SOURCE_LABEL = {"observed": "explicit", "extracted": "explicit",
                       "user": "explicit", "metadata": "metadata",
                       "inferred": "inferred", "ai": "ai"}


@dataclass
class IngestStats:
    found: int = 0
    new: int = 0
    duplicates: int = 0
    skipped: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)
    new_ids: list[int] = field(default_factory=list)
    filtered: int = 0                 # dropped by the Candidate Score gate (no download)
    filter_reasons: dict = field(default_factory=dict)
    near_dups: int = 0


def _is_duplicate(platform: str, platform_post_id: str) -> bool:
    with session_scope() as s:
        row = s.execute(
            select(Post.id).where(Post.platform == platform,
                                  Post.platform_post_id == platform_post_id)
        ).first()
        return row is not None


def _final_ext(media_type: str) -> str:
    return ".mp4" if media_type == "video" else ".webp"


def _sniff_media_type(head: bytes, fallback: str) -> str:
    if len(head) >= 8 and head[4:8] == b"ftyp":          # mp4/mov family
        return "video"
    if head.startswith(b"\x1a\x45\xdf\xa3"):             # webm/matroska
        return "video"
    if head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8")):
        return "image"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image"
    return fallback or "image"


def _build_envelope(sp: ScrapedPost, embedded: dict, params: dict) -> tuple[dict, dict]:
    """Observed layer + provenance assertions (D62/D66). What the source showed
    is recorded as-is; embedded metadata is a separate high-trust source;
    regex extraction from freeform text ranks below both."""
    observed = dict(sp.observed or {})
    ident = observed.setdefault("identity", {})
    ident.update({"platform": sp.platform, "platform_post_id": sp.platform_post_id,
                  "source_url": sp.source_url, "media_type": sp.media_type,
                  "posted_at": sp.posted_at.isoformat() if sp.posted_at else None})
    if "engagement" not in observed and isinstance(params.get("engagement"), dict):
        observed["engagement"] = dict(params["engagement"])
    if "author" not in observed and sp.author:
        observed["author"] = {"handle": str(sp.author).lstrip("@")}
    text = observed.setdefault("text", {})
    if params.get("hashtags") and "hashtags" not in text:
        text["hashtags"] = list(params["hashtags"])
    observed.setdefault("media", {}).setdefault("source_url", sp.media_url)

    assertions: dict = {}
    if sp.prompt:
        conf_flag = params.get("prompt_confidence")
        if conf_flag:
            src_name, conf = "extracted", (0.5 if conf_flag == "low" else 0.9)
            evidence = f"{sp.platform}: mined from post text ({conf_flag} confidence)"
        else:
            src_name, conf, evidence = "observed", 0.96, f"{sp.platform}: structured prompt field"
        provenance.assert_field(assertions, "prompt", sp.prompt, src_name, conf, evidence)
    if embedded.get("prompt"):
        provenance.assert_field(assertions, "prompt", embedded["prompt"], "metadata", 0.95,
                                "embedded generation metadata (PNG/EXIF)")
    if sp.negative_prompt:
        provenance.assert_field(assertions, "negative_prompt", sp.negative_prompt, "observed", 0.96,
                                f"{sp.platform}: structured field")
    if embedded.get("negative_prompt"):
        provenance.assert_field(assertions, "negative_prompt", embedded["negative_prompt"],
                                "metadata", 0.95, "embedded generation metadata")
    if sp.model_name:
        if params.get("model_inferred"):
            src_name, conf, evidence = "inferred", 0.5, "inferred, not stated"
        elif params.get("model_stated") is not None:
            src_name, conf, evidence = "extracted", 0.85, f"{sp.platform}: model named in post text"
        else:
            src_name, conf, evidence = "observed", 0.96, f"{sp.platform}: structured model field"
        provenance.assert_field(assertions, "model", sp.model_name, src_name, conf, evidence)
    emb_params = embedded.get("params") or {}
    if emb_params.get("model"):
        provenance.assert_field(assertions, "model", emb_params["model"], "metadata", 0.95,
                                "embedded generation metadata")
    return observed, assertions


def _upsert_creator(s, sp: ScrapedPost, observed: dict) -> int | None:
    author = observed.get("author") or {}
    handle = str(author.get("handle") or sp.author or "").lstrip("@").strip().lower()[:100]
    if not handle:
        return None
    now = datetime.now(timezone.utc)
    creator = s.execute(select(Creator).where(
        Creator.platform == sp.platform, Creator.handle == handle)).scalars().first()
    if creator is None:
        creator = Creator(platform=sp.platform, handle=handle, first_seen=now, stats={})
        s.add(creator)
    for src_key, col in (("display_name", "display_name"), ("profile_url", "profile_url"),
                         ("avatar", "avatar_url"), ("id", "author_id"), ("bio", "bio")):
        if author.get(src_key):
            setattr(creator, col, str(author[src_key])[:2000])
    for key in ("followers", "following"):
        if isinstance(author.get(key), (int, float)):
            setattr(creator, key, int(author[key]))
    if author.get("verified") is not None:
        creator.verified = bool(author["verified"])
    creator.last_seen = now
    creator.updated_at = now
    s.flush()
    return creator.id


def _post_store_intel(s, post: Post, sp: ScrapedPost, observed: dict, cand: dict | None) -> int:
    """After the row exists: dedupe links, Inspiration Score, creator,
    engagement snapshot, queue jobs. Returns near-duplicate count."""
    weights = settings_store.get(s, "intel_weights") or {}
    dist = int(settings_store.get(s, "intel_near_dup_distance") or 6)
    near = dedupe.near_duplicates(s, post.phash, exclude_id=post.id, max_distance=dist)
    for pid, d in near:
        dedupe.link_posts(s, post.id, pid, "near", round(1 - d / 64, 3))
    for pid in dedupe.exact_duplicates(s, post.content_hash, exclude_id=post.id):
        dedupe.link_posts(s, post.id, pid, "exact", 1.0)

    iscore, ibreak = scoring.inspiration_score(post, weights, near_dups=len(near))
    post.inspiration_score = iscore
    analysis = dict(post.analysis or {})
    analysis["inspiration"] = ibreak
    if cand:
        analysis["candidate"] = cand.get("breakdown", {})
    analysis["near_dup_ids"] = [pid for pid, _ in near]
    post.analysis = analysis

    post.creator_id = _upsert_creator(s, sp, observed)
    eng = observed.get("engagement") or {}
    if any(isinstance(eng.get(k), (int, float)) for k in
           ("likes", "comments", "replies", "reposts", "quotes", "shares", "bookmarks", "views")):
        s.add(EngagementSnapshot(
            post_id=post.id, likes=eng.get("likes"),
            comments=eng.get("comments", eng.get("replies")), reposts=eng.get("reposts"),
            quotes=eng.get("quotes"), shares=eng.get("shares"), bookmarks=eng.get("bookmarks"),
            views=eng.get("views"), impressions=eng.get("impressions")))

    enrich_at = float(settings_store.get(s, "intel_enrich_threshold") or 60)
    analyze_at = float(settings_store.get(s, "intel_analysis_threshold") or 70)
    if post.candidate_score is not None and post.candidate_score >= enrich_at:
        intel_queue.enqueue(s, post.id, "enrich", priority=post.candidate_score)
    if iscore >= analyze_at:
        intel_queue.enqueue(s, post.id, "analysis", priority=iscore)
    s.flush()
    return len(near)


def ingest_one(sp: ScrapedPost, client: httpx.Client,
               origin: str = "scraped") -> int | None:
    """Download, compress, store one post. Returns new post id or None
    (duplicate/skipped). Raises on hard failure (caller counts it)."""
    cfg = get_config()
    if _is_duplicate(sp.platform, sp.platform_post_id):
        return None

    uid = uuid.uuid4().hex
    platform_dir = cfg.media_dir / sp.platform
    tmp_path = platform_dir / f".tmp-{uid}"
    platform_dir.mkdir(parents=True, exist_ok=True)

    try:
        media.download(sp.media_url, tmp_path, client)
        content_hash = dedupe.sha256_file(tmp_path)

        # correct media type from actual content (magic bytes > URL ext > adapter claim)
        with tmp_path.open("rb") as fh:
            head = fh.read(16)
        media_type = _sniff_media_type(
            head, media.guess_media_type(sp.media_url) or sp.media_type)

        # embedded metadata BEFORE compression (images only)
        embedded: dict = {}
        if media_type == "image":
            embedded = metadata.extract_metadata(tmp_path)

        params = dict(embedded.get("params") or {})
        params.update(sp.params or {})  # site-provided structured params win
        cand = params.pop("_candidate", None)
        params.pop("_near_dups", None)

        observed, assertions = _build_envelope(sp, embedded, params)
        prompt = provenance.canonical(assertions, "prompt") or sp.prompt or embedded.get("prompt")
        negative = (provenance.canonical(assertions, "negative_prompt")
                    or sp.negative_prompt or embedded.get("negative_prompt"))
        model_name = provenance.canonical(assertions, "model") or sp.model_name or params.get("model")
        model_source = _MODEL_SOURCE_LABEL.get(provenance.source_of(assertions, "model") or "")
        prompt_source = provenance.source_of(assertions, "prompt")
        eng_total = scoring.engagement_total(observed.get("engagement"))

        with session_scope() as s:
            quality = settings_store.get(s, "image_quality")
            max_dim = settings_store.get(s, "image_max_dim")
            crf = settings_store.get(s, "video_crf")
            max_h = settings_store.get(s, "video_max_height")
            keep_originals = settings_store.get(s, "keep_originals")
            user_rules = settings_store.get(s, "model_aliases") or {}

        final_rel = Path("media") / sp.platform / f"{uid}{_final_ext(media_type)}"
        thumb_rel = Path("media") / sp.platform / "thumbs" / f"{uid}.webp"
        final_abs = cfg.data_dir / final_rel
        thumb_abs = cfg.data_dir / thumb_rel

        if media_type == "video":
            res = media.compress_video(tmp_path, final_abs, crf=crf, max_height=max_h)
            media.make_video_thumb(final_abs, thumb_abs)
        else:
            res = media.compress_image(tmp_path, final_abs, quality=quality, max_dim=max_dim)
            media.make_image_thumb(tmp_path, thumb_abs)  # thumb from original (best quality)
        phash = dedupe.dhash(tmp_path if media_type == "image" else thumb_abs)

        if keep_originals:
            orig_dir = platform_dir / "originals"
            orig_dir.mkdir(parents=True, exist_ok=True)
            src_ext = Path(sp.media_url.split("?")[0]).suffix or ".bin"
            tmp_path.rename(orig_dir / f"{uid}{src_ext}")
        else:
            tmp_path.unlink(missing_ok=True)

        params["_original_bytes"] = res.original_bytes
        params["_stored_bytes"] = res.stored_bytes

        family = normalize_model(model_name, user_rules)

        with session_scope() as s:
            post = Post(
                platform=sp.platform,
                platform_post_id=sp.platform_post_id,
                prompt=prompt,
                negative_prompt=negative,
                model_name=model_name,
                model_family=family,
                model_version=sp.model_version,
                params=params,
                media_type=media_type,
                media_url=sp.media_url,
                media_path=str(final_rel),
                thumb_path=str(thumb_rel),
                media_width=res.width or None,
                media_height=res.height or None,
                duration_s=res.duration_s,
                author=sp.author,
                source_url=sp.source_url,
                posted_at=sp.posted_at,
                nsfw=sp.nsfw,
                origin=origin,
                observed=observed,
                assertions=assertions,
                analysis={},
                candidate_score=(cand or {}).get("score"),
                content_hash=content_hash,
                phash=phash,
                engagement_total=eng_total,
                has_workflow=bool(params.get("workflow")),
                prompt_source=prompt_source,
                model_source=model_source,
                pipeline_state="stored",
                discovered_at=datetime.now(timezone.utc),
            )
            s.add(post)
            s.flush()
            fts.index_post(s, post.id, post.prompt, post.model_name, [])
            post_id = post.id
            sp.params["_near_dups"] = _post_store_intel(s, post, sp, observed, cand)

        hooks.run_post_ingested(post_id)
        return post_id
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _recent_prompt_hashes(s, n: int = 2000) -> set[int]:
    rows = s.execute(select(Post.prompt).where(Post.prompt.is_not(None))
                     .order_by(Post.id.desc()).limit(n))
    return {hash(p.strip().lower()) for (p,) in rows if p}


def ingest_batch(source: str, posts: list[ScrapedPost],
                 client: httpx.Client, gate: bool = True) -> IngestStats:
    """Discovery → Candidate Score gate (no download for weak candidates) →
    dedupe → download → metadata → compress → store → intel/queue."""
    stats = IngestStats(found=len(posts))
    with session_scope() as s:
        min_score = float(settings_store.get(s, "intel_min_candidate_score") or 0)
        weights = settings_store.get(s, "intel_weights") or {}
        recent = _recent_prompt_hashes(s) if gate else set()
    for sp in posts:
        try:
            if not sp.media_url:
                stats.skipped += 1
                continue
            if gate:
                score, breakdown = scoring.candidate_score(
                    sp, weights, recent_prompt_hashes=recent)
                sp.params["_candidate"] = {"score": score, "breakdown": breakdown}
                if score < min_score:
                    stats.filtered += 1
                    weakest = min(breakdown, key=lambda k: breakdown[k]["value"])
                    stats.filter_reasons[weakest] = stats.filter_reasons.get(weakest, 0) + 1
                    continue
            result = ingest_one(sp, client)
            if result is None:
                stats.duplicates += 1
            else:
                stats.new += 1
                stats.new_ids.append(result)
                stats.near_dups += int(sp.params.get("_near_dups") or 0)
        except Exception as e:
            stats.errors += 1
            msg = f"{sp.platform}:{sp.platform_post_id}: {type(e).__name__}: {e}"
            stats.error_messages.append(msg)
            bus.error(f"scraper.{source}", f"ingest failed — {msg}")
    return stats
