"""Phase I5: creator intelligence, Grok discovery evidence model (claim →
PF2 verification on first poll), Grok Web session via the connect flow,
credential-isolation of the two Grok layers."""
import io
import json
from datetime import datetime, timedelta, timezone

import httpx
from PIL import Image

from promptforge import db as db_mod, monitoring, settings_store
from promptforge.integrations import grok
from promptforge.intel import creators
from promptforge.models import Creator, MonitoredAccount, Post
from promptforge.scrapers.base import ScrapedPost
from tests.conftest import seed_post
from tests.test_connect import install_fake_browser, recv_frame, recv_json


def _creator(handle="motionmuse", platform="x", **kw):
    with db_mod.session_scope() as s:
        c = Creator(platform=platform, handle=handle, followers=kw.get("followers", 8000),
                    display_name="Motion Muse", first_seen=datetime.now(timezone.utc) - timedelta(days=60),
                    last_seen=datetime.now(timezone.utc))
        s.add(c)
        s.flush()
        return c.id


def test_creator_stats_listing_and_api(app_env, client):
    cid = _creator()
    now = datetime.now(timezone.utc)
    for i in range(6):
        seed_post(platform="x", creator_id=cid, prompt=f"orbit shot {i}", model_family="kling",
                  model_source="explicit", media_type="video" if i % 2 else "image",
                  engagement_total=100 * (i + 1), inspiration_score=50 + i * 5,
                  ai_status="definitely_ai" if i < 5 else "uncertain",
                  technique_tags=["orbit"] if i < 4 else ["dolly"],
                  posted_at=now - timedelta(days=7 * (5 - i)),
                  assertions={"prompt": {"value": "x", "source": "extracted", "confidence": 0.9 if i < 3 else 0.5}},
                  analysis={"descriptors": {"style": "Neon noir"},
                            "inspiration": {"metadata_richness": {"value": 0.5}}})
    other = _creator("quietone")
    with db_mod.session_scope() as s:
        st = creators.stats_for(s, s.get(Creator, cid))
        assert st["posts"] == 6 and st["images"] == 3 and st["videos"] == 3
        assert st["avg_engagement"] == 350 and st["median_engagement"] == 350
        assert st["ai_ratio"] == round(5 / 6, 3) and st["prompt_availability"] == 0.5
        assert st["models"] == [{"family": "kling", "count": 6}]
        assert st["techniques"][0] == {"slug": "orbit", "count": 4}
        assert st["styles"] == [{"style": "neon noir", "count": 6}]
        assert st["posts_per_week"] and 1.0 <= st["posts_per_week"] <= 1.3
        assert len(st["engagement_trajectory"]) == 6 and st["trend"] == "rising"
        assert st["top_post_ids"][0] == st["recent_post_ids"][0]      # highest score is the newest
        assert st["metadata_richness"] == 0.5 and st["avg_inspiration"] == 62.5
        # cached until stale; force recomputes
        c = s.get(Creator, cid)
        computed = c.stats["computed_at"]
        assert creators.stats_for(s, c)["computed_at"] == computed
        assert creators.stats_for(s, s.get(Creator, other))["posts"] == 0
        ranked = creators.list_creators(s, sort="engagement")
        assert [r["handle"] for r in ranked] == ["motionmuse", "quietone"]
        assert creators.list_creators(s, q="quiet")[0]["handle"] == "quietone"
        assert creators.find(s, "x", "@MotionMuse").id == cid
    r = client.get("/api/inspiration/creators?sort=posts")
    assert r.status_code == 200 and r.json()["creators"][0]["handle"] == "motionmuse"
    r = client.get(f"/api/inspiration/creators/{cid}")
    body = r.json()
    assert body["stats"]["posts"] == 6 and len(body["top_posts"]) == 6
    assert body["top_posts"][0]["id"] == body["stats"]["top_post_ids"][0]
    assert client.post(f"/api/inspiration/creators/{cid}/refresh").json()["stats"]["posts"] == 6
    assert client.get("/api/inspiration/creators/999").status_code == 404
    # monitored accounts link to their creator intelligence
    with db_mod.session_scope() as s:
        s.add(MonitoredAccount(handle="motionmuse", platform="x"))
    acct = client.get("/api/monitoring").json()["accounts"][0]
    assert acct["creator"]["posts"] == 6 and acct["creator"]["models"] == ["kling"]
    assert acct["creator"]["trend"] == "rising" and acct["evidence"] == {}


def test_grok_discovery_is_evidence_not_authority(client, app_env, monkeypatch):
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_api_key", "xai-good")
    monkeypatch.setattr(grok, "chat", lambda *a, **kw: json.dumps([
        {"handle": "@NewCreator", "display_name": "New", "reason": "daily Veo 3 shorts",
         "evidence": "just posted: 'Veo 3 test, prompt: neon canal'", "detected_models": ["Veo 3", "Kling"],
         "content_type": "video", "engagement_estimate": "high", "confidence": 0.82},
        {"handle": "sketchy", "reason": "?", "detected_models": "Sora", "content_type": "hologram",
         "engagement_estimate": "huge", "confidence": 7}]))
    cands = client.post("/api/grok/discover", json={"interest": "cinematic ai video"}).json()["candidates"]
    a, b = cands
    assert a["handle"] == "newcreator" and a["source"] == "grok" and a["verified"] is False
    assert a["detected_models"] == ["Veo 3", "Kling"] and a["detected_families"] == ["kling", "veo"]
    assert a["content_type"] == "video" and a["engagement_estimate"] == "high" and a["confidence"] == 0.82
    assert a["evidence"].startswith("just posted") and a["sample"] == a["evidence"]
    assert b["detected_models"] == ["Sora"] and b["content_type"] is None
    assert b["engagement_estimate"] is None and b["confidence"] == 1.0
    # Watch → the claim is stored as evidence on the follow row, nothing else
    r = client.post("/api/monitoring/accounts", json={"text": "newcreator", "added_by": "grok",
                                                      "notes": a["reason"], "evidence": a})
    created = r.json()["created"][0]
    assert created["evidence"]["detected_models"] == ["Veo 3", "Kling"]
    assert created["evidence"]["verified"] is False and created["evidence"]["source"] == "grok"
    with db_mod.session_scope() as s:
        assert s.execute(__import__("sqlalchemy").select(Creator)).scalars().all() == []   # no creator invented
        assert s.execute(__import__("sqlalchemy").select(Post)).scalars().all() == []      # no posts invented
    # a manual add never carries evidence
    manual = client.post("/api/monitoring/accounts", json={"text": "plainuser", "evidence": a}).json()
    assert manual["created"][0]["evidence"] == {}


def _png():
    im = Image.new("RGB", (64, 48), (10, 200, 90))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class _FakeX:
    def __init__(self, posts):
        self.posts = posts

    def is_configured(self, s):
        return True

    def make_client(self, s):
        payload = _png()
        return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=payload)))

    def fetch_account(self, s, client, handle, since_id=None, media_only=True):
        return list(self.posts)


def test_first_poll_verifies_claim_and_follows_skip_the_gate(app_env, monkeypatch):
    with db_mod.session_scope() as s:
        settings_store.put(s, "intel_min_candidate_score", 95)   # would filter anything discovered
        acct = MonitoredAccount(handle="newcreator", platform="x", added_by="grok",
                                evidence={"source": "grok", "verified": False, "detected_models": ["Veo 3"]})
        s.add(acct)
        s.flush()
        aid = acct.id
    weak = ScrapedPost(platform="x", platform_post_id="77001", media_url="http://h/a.png",
                       author="@newcreator", posted_at=datetime.now(timezone.utc) - timedelta(days=400))
    monkeypatch.setattr(monitoring, "get_adapter", lambda name: _FakeX([weak]))
    stats = monitoring.run_account(aid, manual=True)
    assert stats.new == 1 and stats.filtered == 0            # followed accounts bypass the gate
    with db_mod.session_scope() as s:
        a = s.get(MonitoredAccount, aid)
        assert a.status == "ok" and a.evidence["verified"] is True
        assert a.evidence["verified_by"] == "first successful poll" and a.evidence["posts_seen"] == 1
        post = s.execute(__import__("sqlalchemy").select(Post)).scalar_one()
        assert post.model_name is None                        # Grok's "Veo 3" never became a fact
    # an empty poll does not verify
    with db_mod.session_scope() as s:
        acct2 = MonitoredAccount(handle="ghost", platform="x", added_by="grok",
                                 evidence={"source": "grok", "verified": False})
        s.add(acct2)
        s.flush()
        aid2 = acct2.id
    monkeypatch.setattr(monitoring, "get_adapter", lambda name: _FakeX([]))
    monitoring.run_account(aid2, manual=True)
    with db_mod.session_scope() as s:
        assert s.get(MonitoredAccount, aid2).evidence["verified"] is False


def test_grok_web_session_is_separate_from_api_key(client, app_env, monkeypatch):
    _page, ctx, closed = install_fake_browser(monkeypatch)
    assert client.get("/api/grok/status").json()["web_session"] == {"connected": False, "saved_at": None}
    with client.websocket_connect("/api/ws/connect/grok") as ws:
        assert recv_json(ws)["state"] == "launching"
        assert recv_json(ws)["state"] == "live"
        assert _page.goto_urls == ["https://grok.com/"]
        recv_frame(ws)
        ctx.cookie_list.append({"name": "sso-rw", "value": "tok", "domain": ".grok.com"})
        assert recv_json(ws, "saved")["final"] is True
    assert closed and (app_env.sessions_dir / "grok.json").is_file()
    st = client.get("/api/grok/status").json()
    assert st["web_session"]["connected"] is True and st["web_session"]["saved_at"]
    assert st["configured"] is False                         # the web session is NOT an API key
    with db_mod.session_scope() as s:
        assert not grok.is_configured(s)
    assert client.delete("/api/grok/session").json()["connected"] is False
    assert not (app_env.sessions_dir / "grok.json").exists()
    # and an API key alone never counts as a web session
    with db_mod.session_scope() as s:
        settings_store.put(s, "grok_api_key", "xai-good")
    st = client.get("/api/grok/status").json()
    assert st["configured"] is True and st["web_session"]["connected"] is False
