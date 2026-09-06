"""Phase X2 tests: handle normalization, cursor advance, only-new ingestion,
failure isolation, auto-tag/auto-collection with family scoping, due logic,
API CRUD."""
import io
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from PIL import Image

from promptforge import db as db_mod, monitoring, settings_store
from promptforge.models import Collection, CollectionPost, MonitoredAccount, Post
from promptforge.scrapers.base import ScrapedPost


def test_normalize_handle():
    n = monitoring.normalize_handle
    assert n("@AuroraForge") == "auroraforge"
    assert n("auroraforge") == "auroraforge"
    assert n("https://x.com/AuroraForge") == "auroraforge"
    assert n("https://twitter.com/AuroraForge/status/123") == "auroraforge"
    assert n("x.com/@motionmuse?ref=abc") == "motionmuse"
    assert n("not a handle!!") is None
    assert n("https://x.com/i/lists/99") is None
    assert n("this-handle-is-way-too-long-for-x") is None
    assert n("") is None


def test_parse_bulk():
    valid, rejected = monitoring.parse_bulk(
        "@one, two\nhttps://x.com/Three;  @one  no!handle")
    assert valid == ["one", "two", "three"]      # deduped, normalized
    assert rejected == ["no!handle"]             # invalid tokens reported


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (256, 384), (60, 90, 150)).save(buf, "PNG")
    return buf.getvalue()


class FakeXAdapter:
    """Stands in for XAdapter in monitoring tests."""

    def __init__(self):
        self.timelines: dict[str, list[ScrapedPost]] = {}
        self.calls: list[tuple[str, int | None]] = []
        self.fail_handles: set[str] = set()
        self.configured = True

    def is_configured(self, s):
        return self.configured

    def make_client(self, s):
        payload = png_bytes()
        return httpx.Client(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=payload)))

    def fetch_account(self, s, client, handle, since_id=None, media_only=True):
        self.calls.append((handle, since_id))
        if handle in self.fail_handles:
            raise RuntimeError("timeline exploded")
        posts = self.timelines.get(handle, [])
        if since_id:
            posts = [p for p in posts
                     if int(str(p.platform_post_id).split("-")[0]) > since_id]
        return posts


def x_post(tweet_id: int, handle: str, family="flux", **kw) -> ScrapedPost:
    defaults = dict(
        platform="x", platform_post_id=str(tweet_id),
        media_url=f"https://pbs.twimg.com/media/{tweet_id}.jpg?name=orig",
        media_type="image", prompt=f"prompt {tweet_id}",
        model_name="Flux" if family == "flux" else family,
        params={"prompt_confidence": "high"},
        author=f"@{handle}",
        source_url=f"https://x.com/{handle}/status/{tweet_id}")
    defaults.update(kw)
    return ScrapedPost(**defaults)


@pytest.fixture()
def fake_adapter(app_env, monkeypatch):
    fake = FakeXAdapter()
    monkeypatch.setattr(monitoring, "get_adapter",
                        lambda name: fake if name == "x" else None)
    # the API's session check uses the real adapter → give it a session file
    (app_env.sessions_dir / "x.json").write_text('{"cookies": []}')
    return fake


def add_account(client, handle="auroraforge", **patch):
    r = client.post("/api/monitoring/accounts", json={"text": f"@{handle}"})
    account = r.json()["created"][0]
    if patch:
        account = client.patch(f"/api/monitoring/accounts/{account['id']}",
                               json=patch).json()
    return account


def test_cursor_advance_and_only_new(client, fake_adapter):
    account = add_account(client)
    fake_adapter.timelines["auroraforge"] = [
        x_post(1002, "auroraforge"), x_post(1001, "auroraforge")]
    stats = monitoring.run_account(account["id"], manual=True)
    assert stats.new == 2
    with db_mod.session_scope() as s:
        a = s.get(MonitoredAccount, account["id"])
        assert a.last_post_id == "1002"
        assert a.status == "ok" and a.last_new == 2
    # next poll: only newer than cursor comes through
    fake_adapter.timelines["auroraforge"] = [
        x_post(1005, "auroraforge"), x_post(1002, "auroraforge"),
        x_post(1001, "auroraforge")]
    stats = monitoring.run_account(account["id"], manual=True)
    assert stats.new == 1
    assert fake_adapter.calls[-1] == ("auroraforge", 1002)
    with db_mod.session_scope() as s:
        assert s.get(MonitoredAccount, account["id"]).last_post_id == "1005"
        assert s.query(Post).count() == 3


def test_failing_account_never_blocks_batch(client, fake_adapter):
    a1 = add_account(client, "brokenacct")
    a2 = add_account(client, "healthyacct")
    fake_adapter.fail_handles.add("brokenacct")
    fake_adapter.timelines["healthyacct"] = [x_post(2001, "healthyacct")]
    ran = monitoring.monitor_tick()
    assert ran == 2
    with db_mod.session_scope() as s:
        broken = s.get(MonitoredAccount, a1["id"])
        healthy = s.get(MonitoredAccount, a2["id"])
        assert broken.status == "error" and "timeline exploded" in broken.last_error
        assert healthy.status == "ok" and healthy.last_new == 1


def test_auto_tag_and_auto_collection_with_scoping(client, fake_adapter):
    with db_mod.session_scope() as s:
        c = Collection(name="X Finds", model_family="flux")
        s.add(c)
        s.flush()
        cid = c.id
    account = add_account(client, "taggedacct",
                          auto_tag="x-gold", auto_collection_id=cid)
    fake_adapter.timelines["taggedacct"] = [
        x_post(3001, "taggedacct", family="flux"),
        x_post(3002, "taggedacct", family="sdxl", model_name="SDXL"),
    ]
    monitoring.run_account(account["id"], manual=True)
    with db_mod.session_scope() as s:
        flux_post = s.execute(select(Post).where(
            Post.platform_post_id == "3001")).scalar_one()
        sdxl_post = s.execute(select(Post).where(
            Post.platform_post_id == "3002")).scalar_one()
        assert [t.name for t in flux_post.tags] == ["x-gold"]
        assert [t.name for t in sdxl_post.tags] == ["x-gold"]
        member_ids = {r[0] for r in s.execute(select(
            CollectionPost.post_id).where(CollectionPost.collection_id == cid))}
        assert flux_post.id in member_ids       # same family → added
        assert sdxl_post.id not in member_ids   # cross-family → skipped
    # tag search works
    r = client.get("/api/search?q=tag:x-gold")
    assert len(r.json()["items"]) == 2


def test_due_logic_respects_interval(client, fake_adapter):
    account = add_account(client)
    now = datetime.now(timezone.utc)
    assert monitoring.due_account_ids(now) == [account["id"]]  # never checked
    with db_mod.session_scope() as s:
        a = s.get(MonitoredAccount, account["id"])
        a.check_interval = 60
        a.last_checked = now - timedelta(minutes=30)
    assert monitoring.due_account_ids(now) == []               # not due yet
    with db_mod.session_scope() as s:
        s.get(MonitoredAccount, account["id"]).last_checked = \
            now - timedelta(minutes=61)
    assert monitoring.due_account_ids(now) == [account["id"]]  # due
    with db_mod.session_scope() as s:
        s.get(MonitoredAccount, account["id"]).active = False
    assert monitoring.due_account_ids(now) == []               # inactive


def test_missing_session_marks_error_not_crash(client, fake_adapter):
    fake_adapter.configured = False
    account = add_account(client)
    assert monitoring.run_account(account["id"], manual=True) is None
    with db_mod.session_scope() as s:
        a = s.get(MonitoredAccount, account["id"])
        # I10: an unconfigured source is "needs_setup", not an error — and the
        # message says what to do (§107)
        assert a.status == "needs_setup"
        assert "connect" in a.last_error.lower() or "capture_login" in a.last_error


def test_api_crud_and_bulk(client, fake_adapter):
    r = client.post("/api/monitoring/accounts", json={
        "text": "@one two https://x.com/Three nope!! @one"})
    body = r.json()
    assert [a["handle"] for a in body["created"]] == ["one", "two", "three"]
    assert body["rejected"] == ["nope!!"]
    # duplicate add reports already_monitored
    r = client.post("/api/monitoring/accounts", json={"text": "@one"})
    assert r.json()["already_monitored"] == ["one"]
    listing = client.get("/api/monitoring").json()
    assert len(listing["accounts"]) == 3
    assert listing["x_session_ok"] is True
    one = next(a for a in listing["accounts"] if a["handle"] == "one")
    # patch
    r = client.patch(f"/api/monitoring/accounts/{one['id']}",
                     json={"check_interval": 2, "auto_tag": " neat "})
    assert r.json()["check_interval"] == 5     # clamped to min
    assert r.json()["auto_tag"] == "neat"
    # pause/resume all
    assert client.post("/api/monitoring/pause-all").json()["updated"] == 3
    assert all(not a["active"] for a in
               client.get("/api/monitoring").json()["accounts"])
    client.post("/api/monitoring/resume-all")
    # delete keeps posts
    fake_adapter.timelines["one"] = [x_post(4001, "one")]
    monitoring.run_account(one["id"], manual=True)
    assert client.delete(f"/api/monitoring/accounts/{one['id']}").status_code == 200
    with db_mod.session_scope() as s:
        assert s.execute(select(Post).where(
            Post.platform_post_id == "4001")).scalar_one() is not None
    # invalid-only input → 422? (all rejected still returns lists)
    r = client.post("/api/monitoring/accounts", json={"text": "   "})
    assert r.status_code == 422
