"""ReferenceService (spec §7): reference images per asset. The original
upload is stored byte-for-byte under DATA_DIR/film/assets/{id}/refs, a WebP
thumbnail is a separate derivative, gallery imports copy the library file
and keep full provenance. Never destroys an original."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_config
from ..models import Post
from ..pipeline import media
from . import attributes, events, storage
from .models import FilmAsset, FilmAssetRef, FilmAssetVersion

MAX_REF_BYTES = 50 * 1024 * 1024
_CT_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp"}


class RefError(ValueError):
    pass


def refs_for_asset(s: Session, asset_id: int) -> list[FilmAssetRef]:
    return list(s.execute(select(FilmAssetRef).where(FilmAssetRef.asset_id == asset_id)
                          .order_by(FilmAssetRef.id.asc())).scalars())


def _target_version(s: Session, asset: FilmAsset, version_id: int | None) -> FilmAssetVersion | None:
    if version_id is None:
        return s.get(FilmAssetVersion, asset.current_version_id) if asset.current_version_id else None
    v = s.get(FilmAssetVersion, version_id)
    if v is None or v.asset_id != asset.id:
        raise RefError("version not found")
    return v


def add_reference(s: Session, asset: FilmAsset, data: bytes, content_type: str | None,
                  filename: str | None, kind: str = "custom", label: str | None = None,
                  version_id: int | None = None, source: str = "upload",
                  source_post_id: int | None = None, provenance: dict | None = None,
                  make_primary: bool = False, actor: str = "user") -> tuple[FilmAssetRef, bool]:
    """Store one reference. Returns (ref, deduped) — an identical file already
    attached to this asset is reused rather than written twice."""
    if not data:
        raise RefError("empty file")
    if len(data) > MAX_REF_BYTES:
        raise RefError("reference too large (50MB max)")
    ext = storage.ext_for(content_type, filename, storage.IMAGE_TYPES)
    if ext is None:
        raise RefError("reference must be PNG, JPEG or WebP")
    if kind not in attributes.ref_kinds(asset.type):
        kind = "custom"
    sha = storage.sha256_bytes(data)
    version = _target_version(s, asset, version_id)
    existing = s.execute(select(FilmAssetRef).where(FilmAssetRef.asset_id == asset.id,
                                                    FilmAssetRef.sha256 == sha)).scalar_one_or_none()
    if existing is not None:
        if make_primary and version is not None:
            version.primary_ref_id = existing.id
            s.flush()
        return existing, True
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except Exception:
        raise RefError("file is not a valid image")

    name = storage.new_name(ext)
    rel = storage.asset_rel(asset.id, "refs", name)
    full = storage.write(rel, data)
    thumb_rel: str | None = storage.asset_rel(asset.id, "thumbs", Path(name).stem + ".webp")
    try:
        media.make_image_thumb(full, storage.resolve(thumb_rel))
    except Exception:
        thumb_rel = None
    ref = FilmAssetRef(asset_id=asset.id, version_id=version_id, kind=kind,
                       label=(label or None), path=rel, thumb_path=thumb_rel,
                       width=width, height=height, sha256=sha, source=source,
                       source_post_id=source_post_id, provenance=provenance or {"origin": source})
    s.add(ref)
    s.flush()
    if version is not None and (make_primary or not version.primary_ref_id):
        version.primary_ref_id = ref.id
    s.flush()
    events.log(s, asset.project_id, f"{asset.name}: added {kind} reference", kind="edit",
               actor=actor, entity=("asset", asset.id),
               data={"ref_id": ref.id, "source": source, "version_id": version_id})
    return ref, False


def import_from_post(s: Session, asset: FilmAsset, post_id: int, kind: str = "custom",
                     label: str | None = None, version_id: int | None = None,
                     make_primary: bool = False, actor: str = "user") -> tuple[FilmAssetRef, bool]:
    """Copy a Gallery post's stored media (or a video's poster frame) into the
    asset's references with full attribution."""
    post = s.get(Post, post_id)
    if post is None:
        raise RefError("post not found")
    rel = post.media_path if post.media_type == "image" else post.thumb_path
    if not rel:
        raise RefError("post has no stored media")
    src = get_config().data_dir / rel
    if not src.is_file():
        raise RefError("post media is missing on disk")
    ext = src.suffix.lower()
    ct = _CT_BY_EXT.get(ext)
    if ct is None:
        raise RefError(f"unsupported media type {ext}")
    prov = {"origin": "gallery", "post_id": post.id, "platform": post.platform,
            "author": post.author, "source_url": post.source_url,
            "prompt": (post.prompt or "")[:500] or None, "model_family": post.model_family,
            "poster_frame": post.media_type != "image"}
    return add_reference(s, asset, src.read_bytes(), ct, src.name, kind=kind,
                         label=label or (f"from {post.platform}" if post.platform else None),
                         version_id=version_id, source=f"post:{post.id}", source_post_id=post.id,
                         provenance=prov, make_primary=make_primary, actor=actor)


def set_primary(s: Session, asset: FilmAsset, ref: FilmAssetRef,
                version_id: int | None = None) -> FilmAssetVersion:
    version = _target_version(s, asset, version_id)
    if version is None:
        raise RefError("asset has no versions")
    if ref.asset_id != asset.id:
        raise RefError("reference belongs to another asset")
    version.primary_ref_id = ref.id
    s.flush()
    return version


def update_reference(s: Session, ref: FilmAssetRef, kind: str | None = None,
                     label: str | None = None) -> FilmAssetRef:
    if kind is not None:
        asset = s.get(FilmAsset, ref.asset_id)
        ref.kind = kind if asset and kind in attributes.ref_kinds(asset.type) else "custom"
    if label is not None:
        ref.label = label.strip()[:200] or None
    s.flush()
    return ref


def remove_reference(s: Session, ref: FilmAssetRef, actor: str = "user") -> None:
    asset = s.get(FilmAsset, ref.asset_id)
    for v in s.execute(select(FilmAssetVersion).where(FilmAssetVersion.primary_ref_id == ref.id)).scalars():
        v.primary_ref_id = None
    storage.remove(ref.path)
    storage.remove(ref.thumb_path)
    rid, aid = ref.id, ref.asset_id
    s.delete(ref)
    s.flush()
    if asset is not None:
        events.log(s, asset.project_id, f"{asset.name}: removed a reference", kind="edit",
                   actor=actor, entity=("asset", aid), data={"ref_id": rid})
