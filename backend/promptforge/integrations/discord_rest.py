"""Discord REST helpers (4.3) — token validation, guild/channel listing,
invite URL, test + real message sending. Pure httpx (no gateway needed), with
a specific error message per failure mode."""
from __future__ import annotations

import threading
import time

import httpx

API = "https://discord.com/api/v10"

# View Channel + Send Messages + Embed Links + Attach Files + Use App Commands
INVITE_PERMISSIONS = 1024 + 2048 + 16384 + 32768 + 2147483648


class DiscordError(Exception):
    def __init__(self, message: str, step: str = "unknown"):
        super().__init__(message)
        self.step = step


def _client(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    kw: dict = {"headers": {"Authorization": f"Bot {token}"}, "timeout": 25}
    if transport is not None:
        kw["transport"] = transport
    return httpx.Client(**kw)


def validate_token(token: str, transport=None) -> dict:
    """Returns the bot user {id, username, ...}. Raises DiscordError on bad token."""
    if not token:
        raise DiscordError("No bot token configured — paste one first.", "token")
    with _client(token, transport) as c:
        try:
            resp = c.get(f"{API}/users/@me")
        except httpx.HTTPError as e:
            raise DiscordError(f"Can't reach Discord ({type(e).__name__}).",
                               "network") from e
    if resp.status_code == 401:
        raise DiscordError(
            "Bad bot token (401) — copy it again from the Discord Developer "
            "Portal → your app → Bot → Reset Token.", "token")
    if resp.status_code >= 400:
        raise DiscordError(f"Token check failed (HTTP {resp.status_code}).", "token")
    return resp.json()


def get_application_id(token: str, transport=None) -> str:
    with _client(token, transport) as c:
        resp = c.get(f"{API}/oauth2/applications/@me")
    if resp.status_code >= 400:
        # fall back to the bot user id (equals application id for bots)
        return str(validate_token(token, transport)["id"])
    return str(resp.json()["id"])


def invite_url(application_id: str) -> str:
    return ("https://discord.com/oauth2/authorize"
            f"?client_id={application_id}"
            f"&scope=bot%20applications.commands"
            f"&permissions={INVITE_PERMISSIONS}")


def list_guilds(token: str, transport=None) -> list[dict]:
    with _client(token, transport) as c:
        resp = c.get(f"{API}/users/@me/guilds")
    if resp.status_code >= 400:
        raise DiscordError(f"Couldn't list servers (HTTP {resp.status_code}).",
                           "guilds")
    guilds = resp.json()
    if not guilds:
        raise DiscordError(
            "The bot isn't in any server yet — use the invite link below, "
            "then test again.", "guilds")
    return guilds


def list_channels(token: str, transport=None) -> list[dict]:
    """Text channels across every guild the bot is in."""
    out: list[dict] = []
    guilds = list_guilds(token, transport)
    with _client(token, transport) as c:
        for g in guilds:
            resp = c.get(f"{API}/guilds/{g['id']}/channels")
            if resp.status_code >= 400:
                continue
            for ch in resp.json():
                if ch.get("type") in (0, 5):  # text / announcement
                    out.append({"id": str(ch["id"]), "name": ch["name"],
                                "guild": g.get("name", "?")})
    return out


def send_message(token: str, channel_id: str, payload: dict, transport=None) -> dict:
    with _client(token, transport) as c:
        resp = c.post(f"{API}/channels/{channel_id}/messages", json=payload)
    if resp.status_code == 403:
        raise DiscordError(
            "The bot can't post in that channel (403) — grant it Send Messages "
            "+ Embed Links there, or re-invite with the generated link.",
            "channel")
    if resp.status_code == 404:
        raise DiscordError(
            "Channel not found (404) — pick a channel from the list or check "
            "the ID.", "channel")
    if resp.status_code >= 400:
        raise DiscordError(
            f"Message send failed (HTTP {resp.status_code}: {resp.text[:120]}).",
            "channel")
    return resp.json()


def send_file_message(token: str, channel_id: str, payload: dict,
                      filename: str, content: bytes, transport=None) -> dict:
    import json as _json
    with _client(token, transport) as c:
        resp = c.post(
            f"{API}/channels/{channel_id}/messages",
            data={"payload_json": _json.dumps(payload)},
            files={"files[0]": (filename, content)})
    if resp.status_code == 403:
        raise DiscordError(
            "The bot can't attach files in that channel (403) — grant Attach "
            "Files permission.", "channel")
    if resp.status_code >= 400:
        raise DiscordError(
            f"Message send failed (HTTP {resp.status_code}: {resp.text[:120]}).",
            "channel")
    return resp.json()


def delete_message(token: str, channel_id: str, message_id: str, transport=None) -> None:
    with _client(token, transport) as c:
        c.delete(f"{API}/channels/{channel_id}/messages/{message_id}")


def test_connection(token: str, channel_id: str | None,
                    transport=None, delete_after: float = 10.0) -> dict:
    """Full check: token → bot user → in a guild → can post to channel.
    Sends one sample embed, deletes it after `delete_after` seconds."""
    user = validate_token(token, transport)
    guilds = list_guilds(token, transport)
    if not channel_id:
        raise DiscordError(
            "Pick a channel (or paste a channel ID) so PromptForge knows where "
            "to post.", "channel")
    msg = send_message(token, str(channel_id), {
        "embeds": [{
            "title": "PromptForge connected ✓",
            "description": "This test message deletes itself in a few seconds.",
            "color": 0xFF6A3D,
        }]}, transport)

    def _cleanup():
        time.sleep(delete_after)
        try:
            delete_message(token, str(channel_id), str(msg["id"]), transport)
        except Exception:
            pass

    threading.Thread(target=_cleanup, daemon=True).start()
    return {"ok": True,
            "bot": user.get("username"),
            "guilds": [g.get("name") for g in guilds],
            "summary": f"Connected as {user.get('username')} · "
                       f"{len(guilds)} server(s) · test message sent"}
