"""Auto-push hooks: after ingest, optionally sync to Baserow (auto-sync
toggle) and evaluate Discord posting rules. Registered at app startup."""
from __future__ import annotations

from .. import settings_store
from ..db import session_scope
from ..logbus import bus
from . import hooks


def _baserow_hook(post_id: int) -> None:
    with session_scope() as s:
        if not settings_store.get(s, "baserow_auto_sync"):
            return
        if not settings_store.get(s, "baserow_token"):
            return
    from ..integrations import baserow
    try:
        baserow.push_post_id(post_id)
    except baserow.BaserowError as e:
        bus.error("baserow", f"auto-sync failed for post {post_id}: {e}")


def _discord_hook(post_id: int) -> None:
    from ..integrations import discord_rules
    try:
        discord_rules.evaluate_new_post(post_id)
    except Exception as e:
        bus.error("discord", f"rules evaluation failed for post {post_id}: {e}")


def register_hooks() -> None:
    hooks.register("baserow_autosync", _baserow_hook)
    hooks.register("discord_rules", _discord_hook)
