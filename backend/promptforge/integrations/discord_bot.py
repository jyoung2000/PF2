"""Discord bot (4.4): gateway client for slash commands (/latest /random
/search) + REST-based posting used by manual actions, rules auto-post and
digests. The gateway runs as a background asyncio task only when a token is
configured; REST posting works even when the gateway is down."""
from __future__ import annotations

import asyncio
import random

from sqlalchemy import func, select

from .. import fts, settings_store
from ..config import get_config
from ..db import session_scope
from ..logbus import bus
from ..models import Post
from . import discord_rest

MAX_ATTACH_BYTES = 8 * 1024 * 1024
EMBED_COLOR = 0xFF6A3D


# ---------------------------------------------------------------- embeds ----
def build_embed(post: Post) -> dict:
    prompt = (post.prompt or "").strip()
    if len(prompt) > 1900:
        prompt = prompt[:1897] + "…"
    desc = prompt or "*no prompt captured*"
    if post.source_url:
        desc += f"\n\n[source]({post.source_url})"
    embed = {
        "title": (post.model_name or post.model_family or post.platform)[:250],
        "description": desc,
        "color": EMBED_COLOR,
        "footer": {"text": f"PromptForge · {post.platform}"
                           + (f" · by {post.author}" if post.author else "")},
    }
    return embed


def attachment_for(post: Post) -> tuple[str, bytes] | None:
    """Compressed media if it fits Discord's limit, else the thumbnail."""
    cfg = get_config()
    for rel in (post.media_path, post.thumb_path):
        if not rel:
            continue
        f = cfg.data_dir / rel
        if f.exists() and f.stat().st_size <= MAX_ATTACH_BYTES:
            return f.name, f.read_bytes()
    return None


def _post_payload(post: Post) -> tuple[dict, tuple[str, bytes] | None]:
    embed = build_embed(post)
    attach = attachment_for(post)
    if attach:
        name = attach[0]
        key = "video" if post.media_type == "video" else "image"
        if key == "image":
            embed["image"] = {"url": f"attachment://{name}"}
    return {"embeds": [embed]}, attach


# ------------------------------------------------------------ REST posting --
def post_by_id(post_id: int, channel_id: str | None = None) -> dict:
    with session_scope() as s:
        token = settings_store.get(s, "discord_bot_token")
        channel = channel_id or settings_store.get(s, "discord_channel_id")
        if not token:
            raise discord_rest.DiscordError(
                "Discord isn't configured — add a bot token in Settings first.",
                "token")
        if not channel:
            raise discord_rest.DiscordError(
                "No channel selected — pick one in Settings → Discord.",
                "channel")
        post = s.get(Post, post_id)
        if post is None:
            raise discord_rest.DiscordError("Post not found", "row")
        payload, attach = _post_payload(post)
    if attach:
        result = discord_rest.send_file_message(token, str(channel), payload,
                                                attach[0], attach[1])
    else:
        result = discord_rest.send_message(token, str(channel), payload)
    with session_scope() as s:
        p = s.get(Post, post_id)
        if p is not None:
            p.posted_to_discord = True
    bus.info("discord", f"posted post {post_id} to channel {channel}")
    return {"ok": True, "message_id": result.get("id")}


def post_digest(post_ids: list[int], channel_id: str) -> None:
    with session_scope() as s:
        token = settings_store.get(s, "discord_bot_token")
        posts = [s.get(Post, pid) for pid in post_ids]
        posts = [p for p in posts if p is not None]
        if not token or not posts:
            return
        embeds = [build_embed(p) for p in posts[:10]]
        header = {"title": f"PromptForge digest — {len(posts)} fresh finds",
                  "color": EMBED_COLOR}
        ids = [p.id for p in posts]
    try:
        discord_rest.send_message(token, channel_id,
                                  {"embeds": [header] + embeds[:9]})
        with session_scope() as s:
            for pid in ids:
                p = s.get(Post, pid)
                if p is not None:
                    p.posted_to_discord = True
        bus.info("discord", f"digest posted ({len(ids)} posts)")
    except discord_rest.DiscordError as e:
        bus.error("discord", f"digest failed: {e}")


# ------------------------------------------------------ slash command data --
def latest_payloads(n: int = 3) -> list[tuple[dict, tuple[str, bytes] | None]]:
    with session_scope() as s:
        posts = s.execute(select(Post).order_by(Post.id.desc())
                          .limit(max(1, min(n, 5)))).scalars().all()
        return [_post_payload(p) for p in posts]


def random_payload() -> tuple[dict, tuple[str, bytes] | None] | None:
    with session_scope() as s:
        count = s.execute(select(func.count(Post.id))).scalar_one()
        if not count:
            return None
        offset = random.randrange(count)
        post = s.execute(select(Post).order_by(Post.id).offset(offset)
                         .limit(1)).scalar_one()
        return _post_payload(post)


def search_payloads(query: str, n: int = 3) -> list[tuple[dict, tuple[str, bytes] | None]]:
    with session_scope() as s:
        ids = fts.search_posts(s, query, limit=max(1, min(n, 5)))
        posts = [s.get(Post, i) for i in ids]
        return [_post_payload(p) for p in posts if p is not None]


# ------------------------------------------------------------ gateway bot ---
class BotManager:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._client = None
        self._token: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def sync_from_settings(self) -> None:
        """Start/stop/restart the gateway bot to match current settings."""
        with session_scope() as s:
            token = settings_store.get(s, "discord_bot_token")
        if self._loop is None or self._loop.is_closed():
            return
        if not token:
            if self.running:
                self._loop.call_soon_threadsafe(self._stop_in_loop)
            return
        if self.running and token == self._token:
            return
        self._token = token
        self._loop.call_soon_threadsafe(self._restart_in_loop, token)

    def _stop_in_loop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._client = None
        bus.info("discord", "gateway bot stopped")

    def _restart_in_loop(self, token: str) -> None:
        self._stop_in_loop()
        self._task = asyncio.ensure_future(self._run(token))

    async def _run(self, token: str) -> None:
        try:
            import discord
            from discord import app_commands
        except ImportError:
            bus.error("discord", "discord.py not installed")
            return

        intents = discord.Intents.default()
        client = discord.Client(intents=intents)
        tree = app_commands.CommandTree(client)
        self._client = client

        def to_files(attach: tuple[str, bytes] | None):
            if not attach:
                return []
            import io
            return [discord.File(io.BytesIO(attach[1]), filename=attach[0])]

        @tree.command(name="latest", description="Newest finds from PromptForge")
        @app_commands.describe(n="How many (1–5)")
        async def latest(interaction, n: int = 3):
            await interaction.response.defer()
            payloads = await asyncio.to_thread(latest_payloads, n)
            if not payloads:
                await interaction.followup.send("The library is empty right now.")
                return
            for payload, attach in payloads:
                await interaction.followup.send(
                    embeds=[discord.Embed.from_dict(e) for e in payload["embeds"]],
                    files=to_files(attach))

        @tree.command(name="random", description="A random find from the library")
        async def random_cmd(interaction):
            await interaction.response.defer()
            result = await asyncio.to_thread(random_payload)
            if result is None:
                await interaction.followup.send("The library is empty right now.")
                return
            payload, attach = result
            await interaction.followup.send(
                embeds=[discord.Embed.from_dict(e) for e in payload["embeds"]],
                files=to_files(attach))

        @tree.command(name="search", description="Search prompts in the library")
        @app_commands.describe(text="What to search for")
        async def search_cmd(interaction, text: str):
            await interaction.response.defer()
            payloads = await asyncio.to_thread(search_payloads, text)
            if not payloads:
                await interaction.followup.send(f"No matches for “{text}”.")
                return
            for payload, attach in payloads:
                await interaction.followup.send(
                    embeds=[discord.Embed.from_dict(e) for e in payload["embeds"]],
                    files=to_files(attach))

        @client.event
        async def on_ready():
            try:
                await tree.sync()
                bus.info("discord", f"gateway connected as {client.user} — "
                                    "slash commands synced")
            except Exception as e:
                bus.warn("discord", f"slash command sync failed: {e}")

        try:
            await client.start(token)
        except asyncio.CancelledError:
            await client.close()
            raise
        except Exception as e:
            bus.error("discord", f"gateway bot stopped: {type(e).__name__}: {e}")

    def stop(self) -> None:
        if self._loop is not None and not self._loop.is_closed() and self.running:
            self._loop.call_soon_threadsafe(self._stop_in_loop)


manager = BotManager()


def status(s) -> dict:
    token = settings_store.get(s, "discord_bot_token")
    if not token:
        return {"status": "not_configured"}
    return {"status": "connected" if manager.running else "configured",
            "gateway": manager.running}
