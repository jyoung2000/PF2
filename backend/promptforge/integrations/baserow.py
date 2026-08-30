"""Baserow integration (4.1): token check → table discovery/creation → field
schema → media upload (compressed file, D31) → row push. Every failure mode
maps to a specific, actionable message — never a generic error."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from .. import settings_store
from ..config import get_config
from ..logbus import bus
from ..models import Post

TABLE_NAME = "PromptForge"

# field name -> baserow field type + extra kwargs
FIELD_SCHEMA: list[tuple[str, str, dict]] = [
    ("prompt", "long_text", {}),
    ("negative_prompt", "long_text", {}),
    ("model", "text", {}),
    ("model_family", "text", {}),
    ("platform", "text", {}),
    ("media_type", "text", {}),
    ("author", "text", {}),
    ("source_url", "url", {}),
    ("media", "file", {}),
    ("tags", "multiple_select", {"select_options": []}),
    ("nsfw", "boolean", {}),
    ("favorite", "boolean", {}),
    ("posted_at", "date", {"date_format": "ISO", "date_include_time": True}),
    ("params_json", "long_text", {}),
]


class BaserowError(Exception):
    def __init__(self, message: str, step: str = "unknown"):
        super().__init__(message)
        self.step = step


class BaserowClient:
    def __init__(self, url: str, token: str, timeout: int = 30,
                 transport: httpx.BaseTransport | None = None):
        self.base = (url or "https://api.baserow.io").rstrip("/")
        self.token = token
        kw: dict = {"timeout": timeout,
                    "headers": {"Authorization": f"Token {token}"}}
        if transport is not None:
            kw["transport"] = transport
        self.http = httpx.Client(**kw)

    def close(self) -> None:
        self.http.close()

    # -- low-level ----------------------------------------------------------
    def _req(self, method: str, path: str, step: str, **kw) -> httpx.Response:
        try:
            resp = self.http.request(method, f"{self.base}{path}", **kw)
        except httpx.HTTPError as e:
            raise BaserowError(
                f"Can't reach Baserow at {self.base} ({type(e).__name__}) — "
                f"check the URL and that the server is up.", step) from e
        if resp.status_code == 401:
            raise BaserowError(
                "Token rejected (401) — regenerate it in Baserow → Settings → "
                "API tokens (database tokens, not account passwords).", step)
        if resp.status_code == 403:
            raise BaserowError(
                "Token valid but lacks permission (403) — open the token in "
                "Baserow → Settings → API tokens and enable create/read/update "
                "rights for this database.", step)
        return resp

    # -- steps ---------------------------------------------------------------
    def check_token(self) -> None:
        if not self.token:
            raise BaserowError("No token configured — paste a database token first.",
                               "token")
        resp = self._req("GET", "/api/database/tokens/check/", "token")
        if resp.status_code >= 400:
            raise BaserowError(
                f"Token check failed (HTTP {resp.status_code}) — is this a "
                f"Baserow database token?", "token")

    def list_tables(self) -> list[dict]:
        resp = self._req("GET", "/api/database/tables/all-tables/", "tables")
        if resp.status_code >= 400:
            raise BaserowError(
                f"Couldn't list tables (HTTP {resp.status_code}).", "tables")
        return resp.json()

    def find_or_create_table(self, table_id: str | int | None = None) -> dict:
        tables = self.list_tables()
        if table_id:
            for t in tables:
                if str(t["id"]) == str(table_id):
                    return t
            raise BaserowError(
                f"Table id {table_id} isn't visible to this token — pick one of: "
                + (", ".join(f"{t['name']} (#{t['id']})" for t in tables) or "none"),
                "table")
        for t in tables:
            if t.get("name") == TABLE_NAME:
                return t
        # auto-create in the first visible database
        if not tables:
            raise BaserowError(
                "This token can't see any tables. Create an empty table named "
                f"“{TABLE_NAME}” in your database, grant the token access, and "
                "test again — or paste its Table ID.", "table")
        database_id = tables[0].get("database_id")
        resp = self._req("POST", f"/api/database/tables/database/{database_id}/",
                         "table", json={"name": TABLE_NAME})
        if resp.status_code >= 400:
            raise BaserowError(
                f"Couldn't create the “{TABLE_NAME}” table (HTTP "
                f"{resp.status_code}) — create it manually in Baserow and "
                "re-test, or paste its Table ID.", "table")
        return resp.json()

    def list_fields(self, table_id: int) -> list[dict]:
        resp = self._req("GET", f"/api/database/fields/table/{table_id}/", "fields")
        if resp.status_code >= 400:
            raise BaserowError(
                f"Couldn't read table fields (HTTP {resp.status_code}).", "fields")
        return resp.json()

    def ensure_fields(self, table_id: int) -> dict[str, dict]:
        existing = {f["name"]: f for f in self.list_fields(table_id)}
        for name, ftype, extra in FIELD_SCHEMA:
            if name in existing:
                continue
            resp = self._req("POST", f"/api/database/fields/table/{table_id}/",
                             "fields", json={"name": name, "type": ftype, **extra})
            if resp.status_code >= 400:
                raise BaserowError(
                    f"Couldn't create field “{name}” (HTTP {resp.status_code}: "
                    f"{resp.text[:120]}).", "fields")
            existing[name] = resp.json()
        return existing

    def ensure_tag_options(self, table_id: int, tags: list[str]) -> None:
        if not tags:
            return
        fields = {f["name"]: f for f in self.list_fields(table_id)}
        tag_field = fields.get("tags")
        if not tag_field or tag_field.get("type") != "multiple_select":
            return
        options = tag_field.get("select_options") or []
        known = {o["value"] for o in options}
        missing = [t for t in tags if t not in known]
        if not missing:
            return
        new_options = [{"id": o["id"], "value": o["value"], "color": o.get("color", "blue")}
                       for o in options]
        new_options += [{"value": t, "color": "blue"} for t in missing]
        resp = self._req("PATCH", f"/api/database/fields/{tag_field['id']}/",
                         "fields", json={"select_options": new_options})
        if resp.status_code >= 400:
            bus.warn("baserow", f"couldn't add tag options: HTTP {resp.status_code}")

    def upload_file(self, path: Path) -> dict:
        try:
            with open(path, "rb") as fh:
                resp = self._req(
                    "POST", "/api/user-files/upload-file/", "upload",
                    files={"file": (path.name, fh)})
        except OSError as e:
            raise BaserowError(f"Media file missing on disk: {e}", "upload") from e
        if resp.status_code >= 400:
            raise BaserowError(
                f"Media upload failed (HTTP {resp.status_code}) — the token "
                "may lack file-upload rights on this instance.", "upload")
        return resp.json()

    def create_row(self, table_id: int, row: dict) -> dict:
        resp = self._req("POST",
                         f"/api/database/rows/table/{table_id}/?user_field_names=true",
                         "row", json=row)
        if resp.status_code >= 400:
            raise BaserowError(
                f"Row create failed (HTTP {resp.status_code}: {resp.text[:160]}).",
                "row")
        return resp.json()

    def delete_row(self, table_id: int, row_id: int) -> None:
        self._req("DELETE", f"/api/database/rows/table/{table_id}/{row_id}/", "row")

    # -- high-level ----------------------------------------------------------
    def test_connection(self, table_id: str | int | None = None) -> dict:
        self.check_token()
        table = self.find_or_create_table(table_id)
        self.ensure_fields(table["id"])
        row = self.create_row(table["id"], {"prompt": "PromptForge connection test",
                                            "platform": "test"})
        self.delete_row(table["id"], row["id"])
        return {"ok": True, "table_id": table["id"], "table_name": table["name"],
                "summary": f"Connected · table “{table['name']}” (#{table['id']}) ready"}

    def push_post(self, post: Post, table_id: int, tag_names: list[str]) -> dict:
        cfg = get_config()
        self.ensure_tag_options(table_id, tag_names)
        row: dict = {
            "prompt": post.prompt or "",
            "negative_prompt": post.negative_prompt or "",
            "model": post.model_name or "",
            "model_family": post.model_family or "",
            "platform": post.platform,
            "media_type": post.media_type,
            "author": post.author or "",
            "source_url": post.source_url or "",
            "tags": tag_names,
            "nsfw": post.nsfw,
            "favorite": post.favorite,
            "params_json": json.dumps(
                {k: v for k, v in (post.params or {}).items()
                 if not k.startswith("_")}, default=str),
        }
        if post.posted_at:
            row["posted_at"] = post.posted_at.isoformat()
        if post.media_path:
            media_file = cfg.data_dir / post.media_path
            if media_file.exists():
                uploaded = self.upload_file(media_file)  # compressed file (D31)
                row["media"] = [{"name": uploaded["name"]}]
        return self.create_row(table_id, row)


def client_from_settings(s: Session,
                         transport: httpx.BaseTransport | None = None) -> BaserowClient:
    return BaserowClient(
        settings_store.get(s, "baserow_url"),
        settings_store.get(s, "baserow_token"),
        transport=transport)


def is_configured(s: Session) -> bool:
    return bool(settings_store.get(s, "baserow_token"))


def push_post_id(post_id: int, force: bool = False) -> dict:
    """Push one post (manual action or auto-sync). Returns result dict."""
    from ..db import session_scope
    with session_scope() as s:
        post = s.get(Post, post_id)
        if post is None:
            raise BaserowError("Post not found", "row")
        if post.synced_to_baserow and not force:
            return {"ok": True, "skipped": "already synced"}
        if not is_configured(s):
            raise BaserowError(
                "Baserow isn't configured — add your token in Settings → "
                "Integrations first.", "token")
        tag_names = [t.name for t in post.tags]
        client = client_from_settings(s)
        table_id = settings_store.get(s, "baserow_table_id")
    try:
        if not table_id:
            table = client.find_or_create_table(None)
            client.ensure_fields(table["id"])
            table_id = table["id"]
            with session_scope() as s2:
                settings_store.put(s2, "baserow_table_id", str(table_id))
        result = client.push_post(post, int(table_id), tag_names)
        with session_scope() as s2:
            p2 = s2.get(Post, post_id)
            if p2 is not None:
                p2.synced_to_baserow = True
        bus.info("baserow", f"post {post_id} pushed to table {table_id}")
        return {"ok": True, "row_id": result.get("id")}
    finally:
        client.close()
