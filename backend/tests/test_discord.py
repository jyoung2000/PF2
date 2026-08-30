"""Discord REST helpers, rules engine, bot payloads (4.3–4.5, 9.6)."""
import time

import httpx
import pytest

from promptforge import db as db_mod, settings_store
from promptforge.integrations import discord_rest, discord_rules
from promptforge.integrations.discord_rules import (DEFAULT_RULES, Throttle,
                                                    post_matches, route_channel)
from promptforge.models import Post
from tests.conftest import seed_post


def discord_server(sent):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        auth = request.headers.get("Authorization", "")
        if auth != "Bot good-token":
            return httpx.Response(401, json={"message": "401: Unauthorized"})
        if path == "/api/v10/users/@me":
            return httpx.Response(200, json={"id": "111", "username": "PromptForgeBot"})
        if path == "/api/v10/oauth2/applications/@me":
            return httpx.Response(200, json={"id": "222"})
        if path == "/api/v10/users/@me/guilds":
            return httpx.Response(200, json=[{"id": "g1", "name": "Art Server"}])
        if path == "/api/v10/guilds/g1/channels":
            return httpx.Response(200, json=[
                {"id": "c1", "name": "general", "type": 0},
                {"id": "c2", "name": "voice", "type": 2},
                {"id": "c3", "name": "flux-finds", "type": 0}])
        if path.endswith("/messages") and request.method == "POST":
            channel = path.split("/")[4]
            if channel == "forbidden":
                return httpx.Response(403, json={"message": "Missing Permissions"})
            sent.append((channel, request.content))
            return httpx.Response(200, json={"id": f"m{len(sent)}"})
        if request.method == "DELETE":
            sent.append(("deleted", path))
            return httpx.Response(204)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_validate_token_and_errors():
    t = discord_server([])
    user = discord_rest.validate_token("good-token", t)
    assert user["username"] == "PromptForgeBot"
    with pytest.raises(discord_rest.DiscordError) as ei:
        discord_rest.validate_token("bad", t)
    assert "Developer Portal" in str(ei.value)
    with pytest.raises(discord_rest.DiscordError):
        discord_rest.validate_token("", t)


def test_channel_listing_and_invite():
    t = discord_server([])
    channels = discord_rest.list_channels("good-token", t)
    assert [c["id"] for c in channels] == ["c1", "c3"]  # text channels only
    url = discord_rest.invite_url("222")
    assert "client_id=222" in url and "applications.commands" in url
    assert str(discord_rest.INVITE_PERMISSIONS) in url


def test_test_connection_flow_and_failures():
    sent = []
    t = discord_server(sent)
    result = discord_rest.test_connection("good-token", "c1", t, delete_after=0.05)
    assert result["ok"] and "PromptForgeBot" in result["summary"]
    assert sent[0][0] == "c1"
    time.sleep(0.3)  # test message deleted after delay
    assert any(s[0] == "deleted" for s in sent)
    # channel permission failure
    with pytest.raises(discord_rest.DiscordError) as ei:
        discord_rest.test_connection("good-token", "forbidden", t)
    assert "Send Messages" in str(ei.value)
    # missing channel
    with pytest.raises(discord_rest.DiscordError) as ei:
        discord_rest.test_connection("good-token", None, t)
    assert ei.value.step == "channel"


def _post(**kw) -> Post:
    defaults = dict(platform="civitai", media_type="image", prompt="a prompt",
                    model_family="flux", nsfw=False, favorite=False)
    defaults.update(kw)
    return Post(platform_post_id="x", **defaults)


def test_rules_modes():
    r = dict(DEFAULT_RULES)
    assert post_matches(r, _post(), []) is False  # manual default
    r["mode"] = "all"
    assert post_matches(r, _post(), []) is True
    r["mode"] = "favorites"
    assert post_matches(r, _post(), []) is False
    assert post_matches(r, _post(favorite=True), []) is True
    r["mode"] = "collections"
    r["collections"] = [7]
    assert post_matches(r, _post(), [3]) is False
    assert post_matches(r, _post(), [7, 3]) is True
    r["mode"] = "families"
    r["families"] = ["flux"]
    assert post_matches(r, _post(model_family="sdxl"), []) is False
    assert post_matches(r, _post(), []) is True
    r["mode"] = "platforms"
    r["platforms"] = ["lexica"]
    assert post_matches(r, _post(), []) is False
    assert post_matches(r, _post(platform="lexica"), []) is True


def test_rules_filters():
    r = dict(DEFAULT_RULES, mode="all")
    assert post_matches(r, _post(nsfw=True), []) is False           # sfw_only
    r2 = dict(r, sfw_only=False)
    assert post_matches(r2, _post(nsfw=True), []) is True
    assert post_matches(r, _post(prompt=None), []) is False         # require_prompt
    r3 = dict(r, require_prompt=False)
    assert post_matches(r3, _post(prompt=None), []) is True
    r4 = dict(r, media="videos")
    assert post_matches(r4, _post(), []) is False
    assert post_matches(r4, _post(media_type="video"), []) is True
    r5 = dict(r, media="images")
    assert post_matches(r5, _post(media_type="video"), []) is False


def test_routing():
    r = dict(DEFAULT_RULES,
             routes=[{"match": "family", "value": "flux", "channel_id": "c3"},
                     {"match": "collection", "value": 9, "channel_id": "c9"}])
    assert route_channel(r, _post(), [], "cd") == "c3"
    assert route_channel(r, _post(model_family="sdxl"), [9], "cd") == "c9"
    assert route_channel(r, _post(model_family="sdxl"), [], "cd") == "cd"
    assert route_channel(r, _post(model_family="sdxl"), [], None) is None


def test_throttle_sliding_window():
    th = Throttle()
    now = 1000.0
    assert th.allow("c1", 2, now)
    assert th.allow("c1", 2, now + 1)
    assert th.allow("c1", 2, now + 2) is False       # cap hit
    assert th.allow("c2", 2, now + 2) is True        # per-channel
    assert th.allow("c1", 2, now + 3601) is True     # window slides


def test_evaluate_and_digest(app_env, monkeypatch):
    posted = []
    from promptforge.integrations import discord_bot
    monkeypatch.setattr(discord_bot, "post_by_id",
                        lambda pid, ch: posted.append(("one", pid, ch)))
    monkeypatch.setattr(discord_bot, "post_digest",
                        lambda ids, ch: posted.append(("digest", ids, ch)))
    with db_mod.session_scope() as s:
        settings_store.put(s, "discord_bot_token", "good-token")
        settings_store.put(s, "discord_channel_id", "c1")
        settings_store.put(s, "discord_rules",
                           dict(DEFAULT_RULES, mode="all"))
    p1 = seed_post(prompt="hello world")
    discord_rules.evaluate_new_post(p1)
    assert posted == [("one", p1, "c1")]
    # digest mode queues then flushes
    posted.clear()
    with db_mod.session_scope() as s:
        settings_store.put(s, "discord_rules",
                           dict(DEFAULT_RULES, mode="all", delivery="digest",
                                digest_hours=1, digest_count=5))
    p2 = seed_post(prompt="digest me")
    p3 = seed_post(prompt="digest me too")
    discord_rules.evaluate_new_post(p2)
    discord_rules.evaluate_new_post(p3)
    assert posted == []
    monkeypatch.setattr(discord_rules, "_last_digest_at", 0.0)
    discord_rules.digest_tick(force=True)
    assert posted == [("digest", [p2, p3], "c1")]


def test_preview_endpoint(client):
    seed_post(prompt="previewable", model_family="flux")
    seed_post(prompt=None)  # no prompt → filtered out
    with db_mod.session_scope() as s:
        settings_store.put(s, "discord_bot_token", "good-token")
    r = client.put("/api/integrations/discord/rules", json={"mode": "all"})
    assert r.status_code == 200
    preview = r.json()["preview"]
    assert preview["matched"] == 1
    assert preview["would_post"] == 1
    r2 = client.get("/api/integrations/discord/rules")
    assert r2.json()["rules"]["mode"] == "all"


def test_post_payloads_and_push_endpoint(client, app_env, monkeypatch):
    thumb = app_env.data_dir / "media/civitai/thumbs/t.webp"
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.write_bytes(b"RIFFxxxxWEBP")
    pid = seed_post(prompt="p" * 2500, thumb_path="media/civitai/thumbs/t.webp",
                    media_path=None, author="artist")
    from promptforge.integrations import discord_bot
    payloads = discord_bot.latest_payloads(1)
    assert len(payloads) == 1
    payload, attach = payloads[0]
    embed = payload["embeds"][0]
    assert len(embed["description"]) <= 2000          # embed limit respected
    assert "PromptForge · civitai · by artist" in embed["footer"]["text"]
    assert attach[0] == "t.webp"
    # search payloads via FTS
    assert discord_bot.search_payloads("p") is not None
    # push endpoint with mocked transport
    sent = []
    t = discord_server(sent)
    monkeypatch.setattr(discord_rest, "_client",
                        lambda token, transport=None: httpx.Client(
                            headers={"Authorization": f"Bot {token}"}, transport=t))
    with db_mod.session_scope() as s:
        settings_store.put(s, "discord_bot_token", "good-token")
        settings_store.put(s, "discord_channel_id", "c1")
    r = client.post(f"/api/posts/{pid}/push/discord")
    assert r.status_code == 200, r.text
    assert sent and sent[0][0] == "c1"
    detail = client.get(f"/api/posts/{pid}").json()
    assert detail["posted_to_discord"] is True
