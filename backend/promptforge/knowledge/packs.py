""".pfpack export/import (6.8, D33): a zip with manifest + model file and/or
style profile + template (JSON & written text) + optional exemplar thumbnails.
Import merges newer-wins per file, logged to knowledge/import.log."""
from __future__ import annotations

import io
import json
import re as _re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..config import get_config
from ..db import session_scope
from ..logbus import bus
from ..models import Collection, Post, Template
from . import files


class PackError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def export_pack(family: str | None = None, collection_id: int | None = None,
                include_thumbs: bool = True) -> tuple[str, bytes]:
    """→ (filename, zip bytes)."""
    if not family and not collection_id:
        raise PackError("Export needs a model family and/or a collection.")
    cfg = get_config()
    manifest: dict = {"format": "pfpack/1", "exported_at": _now(), "files": {}}
    buf = io.BytesIO()
    exemplar_ids: list[int] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        def add_file(arcname: str, path: Path) -> None:
            zf.write(path, arcname)
            manifest["files"][arcname] = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc).isoformat()

        if family:
            path = files.model_file_path(family)
            if not path.exists():
                raise PackError(f"No knowledge file for family '{family}' yet.")
            manifest["family"] = family
            add_file("model.md", path)
            _fm, body = files.read_md(path)
            exemplar_ids += [int(x) for x in
                             _re.findall(r"\d+", files.get_section(body, "Exemplars"))][:6]
        if collection_id:
            path = files.style_file_path(collection_id)
            if not path.exists():
                from . import engine
                engine.refresh_style_profile(collection_id, use_llm=False)
            if not path.exists():
                raise PackError(f"Collection {collection_id} not found.")
            manifest["collection_id"] = collection_id
            with session_scope() as s:
                c = s.get(Collection, collection_id)
                manifest["collection"] = c.name if c else None
            add_file("style.md", path)
            with session_scope() as s:
                template = s.execute(select(Template).where(
                    Template.collection_id == collection_id)).scalar_one_or_none()
                if template is not None:
                    from . import template_gen
                    zf.writestr("template.json",
                                json.dumps(template_gen.export_json(template),
                                           indent=2))
                    zf.writestr("template.txt", template_gen.export_text(template))
                    manifest["files"]["template.json"] = _now()
                    manifest["files"]["template.txt"] = _now()

        if include_thumbs and exemplar_ids:
            with session_scope() as s:
                for pid in exemplar_ids:
                    post = s.get(Post, pid)
                    if post and post.thumb_path:
                        f = cfg.data_dir / post.thumb_path
                        if f.exists():
                            zf.write(f, f"exemplars/{pid}.webp")
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    name_bits = [family or "", f"collection-{collection_id}" if collection_id else ""]
    fname = "-".join(b for b in name_bits if b) or "knowledge"
    return f"promptforge-{fname}.pfpack", buf.getvalue()


def import_pack(data: bytes) -> dict:
    cfg = get_config()
    log_path = cfg.knowledge_dir / "import.log"
    imported: list[str] = []
    skipped: list[str] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise PackError("Not a valid .pfpack (zip) file.") from e
    try:
        manifest = json.loads(zf.read("manifest.json"))
    except (KeyError, ValueError) as e:
        raise PackError("Pack has no readable manifest.json.") from e
    if manifest.get("format") != "pfpack/1":
        raise PackError(f"Unsupported pack format {manifest.get('format')!r}.")

    def newer_than_local(arcname: str, local: Path) -> bool:
        if not local.exists():
            return True
        remote_ts = manifest.get("files", {}).get(arcname)
        if not remote_ts:
            return True
        try:
            remote_dt = datetime.fromisoformat(remote_ts)
        except ValueError:
            return True
        local_dt = datetime.fromtimestamp(local.stat().st_mtime, tz=timezone.utc)
        return remote_dt > local_dt

    family = manifest.get("family")
    if family and "model.md" in zf.namelist():
        dest = files.model_file_path(family)
        if newer_than_local("model.md", dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read("model.md"))
            imported.append(f"models/{family}.md")
        else:
            skipped.append(f"models/{family}.md (local is newer)")

    collection_id = manifest.get("collection_id")
    target_collection: int | None = None
    if collection_id and "style.md" in zf.namelist():
        # bind to a local collection with the same name, else create one
        name = manifest.get("collection") or f"Imported {collection_id}"
        with session_scope() as s:
            c = s.execute(select(Collection).where(
                Collection.name == name)).scalar_one_or_none()
            if c is None:
                c = Collection(name=name, model_family=family)
                s.add(c)
                s.flush()
            target_collection = c.id
        dest = files.style_file_path(target_collection)
        if newer_than_local("style.md", dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            fm, body = files.read_md_bytes(zf.read("style.md"))
            fm["collection_id"] = target_collection
            files.write_md(dest, fm, body)
            imported.append(f"styles/collection-{target_collection}.md")
        else:
            skipped.append("style.md (local is newer)")
        if "template.json" in zf.namelist():
            from . import template_gen
            try:
                template_gen.import_json(
                    json.loads(zf.read("template.json")), target_collection)
                imported.append("template.json")
            except Exception as e:
                skipped.append(f"template.json ({e})")

    entry = (f"{_now()} imported={imported} skipped={skipped} "
             f"from pack exported_at={manifest.get('exported_at')}\n")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(entry)
    bus.info("knowledge", f"pack import: {len(imported)} file(s), "
                          f"{len(skipped)} skipped")
    return {"imported": imported, "skipped": skipped,
            "collection_id": target_collection, "family": family}
