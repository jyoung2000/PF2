"""Tier 2 adapters (5.x): parser tests on fixture JSON + browser_base
machinery with crawl4ai fully mocked."""
import json
import time
from pathlib import Path

from promptforge import db as db_mod
from promptforge.scrapers.midjourney import MidjourneyAdapter
from promptforge.scrapers.pixai import PixAIAdapter
from promptforge.scrapers.seaart import SeaArtAdapter
from promptforge.scrapers.tensorart import TensorArtAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def captured(name, url):
    return [{"url": url, "json": load(name)}]


def test_midjourney_parse():
    posts = MidjourneyAdapter().parse_captured(
        captured("midjourney_jobs.json",
                 "https://www.midjourney.com/api/explore?tab=recent"))
    assert len(posts) == 3
    p = posts[0]
    assert p.platform == "midjourney"
    assert p.prompt == ("hyperreal studio portrait of a falconer in brass "
                        "armor, overcast rim light")
    assert p.model_name == "Midjourney v7"
    assert p.model_version == "7"
    assert p.params["aspect_ratio"] == "2:3"
    assert p.params["stylize"] == "250"
    assert p.params["style_reference"] == "918811223"
    assert p.author == "atlas_frames"
    assert "cdn.midjourney.com" in p.media_url
    niji = posts[1]
    assert niji.model_name == "Niji 6"
    video = posts[2]
    assert video.media_type == "video"
    assert video.media_url.endswith(".mp4")


def test_tensorart_parse():
    posts = TensorArtAdapter().parse_captured(
        captured("tensorart_posts.json",
                 "https://api.tensor.art/community-web/v1/post/list"))
    assert len(posts) == 2  # broken item skipped
    p = posts[0]
    assert p.prompt.startswith("chrome oni mask")
    assert p.negative_prompt == "lowres, extra fingers"
    assert p.model_name == "Illustrious XL v1.0"
    assert p.params["loras"] == ["NeonRim v2"]
    assert p.params["sampler"] == "Euler a"
    assert p.params["seed"] == 44821
    assert p.params["size"] == "832x1216"
    assert p.author == "voidbloom"
    assert p.source_url.endswith("/posts/882299110044")
    vid = posts[1]
    assert vid.media_type == "video"
    assert vid.model_name == "Wan 2.2 T2V"
    assert vid.author == "papercut"
    assert vid.posted_at is not None  # ms epoch handled


def test_seaart_parse():
    posts = SeaArtAdapter().parse_captured(
        captured("seaart_list.json",
                 "https://www.seaart.ai/api/v1/artwork/list"))
    assert len(posts) == 2
    p = posts[0]
    assert p.prompt.startswith("bioluminescent")
    assert p.model_name == "SDXL DreamShaper"
    assert p.params["sampler"] == "DPM++ 2M"
    assert p.author == "driftline"
    vid = posts[1]
    assert vid.media_type == "video"
    assert vid.model_name == "kling-1.6"


def test_pixai_parse():
    posts = PixAIAdapter().parse_captured(
        captured("pixai_graphql.json", "https://api.pixai.art/graphql"))
    assert len(posts) == 2
    p = posts[0]
    assert p.prompt.startswith("1girl, glasshouse")
    assert p.negative_prompt == "worst quality, watermark"
    assert p.model_name == "Moonbeam v3"
    assert p.params["steps"] == 25
    assert p.media_url.endswith("1893-full.png")  # PUBLIC variant chosen
    assert p.params["size"] == "768x1280"


def test_wants_response_filters():
    mj = MidjourneyAdapter()
    assert mj.wants_response("https://www.midjourney.com/api/explore?page=1")
    assert not mj.wants_response("https://www.midjourney.com/_next/static/x.js")
    ta = TensorArtAdapter()
    assert ta.wants_response("https://api.tensor.art/community-web/v1/post/list")
    assert not ta.wants_response("https://tensor.art/assets/app.css")
    px = PixAIAdapter()
    assert px.wants_response("https://api.pixai.art/graphql")


def test_registry_has_all_six(app_env):
    from promptforge.scrapers import all_adapters
    names = set(all_adapters())
    assert {"civitai", "lexica", "midjourney", "tensorart", "seaart",
            "pixai"} <= names


def test_session_status_and_needs_setup(app_env):
    mj = MidjourneyAdapter()
    with db_mod.session_scope() as s:
        assert mj.session_status(s) == "missing"
        assert mj.is_configured(s) is False
        assert "capture_login.py" in mj.needs_setup_reason(s)
        assert mj.health(s)["status"] == "needs_setup"
        # drop a session file → valid
        mj.storage_state_path().write_text(json.dumps({"cookies": [
            {"name": "session", "value": "abc", "domain": ".midjourney.com",
             "path": "/"}]}))
        assert mj.session_status(s) == "valid"
        assert mj.is_configured(s) is True
        # client picks up the cookie (D47)
        client = mj.make_client(s)
        jar = list(client.cookies.jar)
        assert any(c.name == "session" and c.value == "abc" for c in jar)
        client.close()


def test_fetch_recent_backoff_and_expiry(app_env, monkeypatch):
    mj = MidjourneyAdapter()
    with db_mod.session_scope() as s:
        mj.storage_state_path().write_text(json.dumps({"cookies": []}))
        client = mj.make_client(s)
        # 429 → backoff recorded, empty result
        monkeypatch.setattr(mj, "_run_crawl", lambda storage_state: ([], 429))
        assert mj.fetch_recent(s, client, 10) == []
        st = mj.get_state(s)
        assert st.state["backoff_until"] > time.time()
        # while in backoff, crawl isn't attempted
        monkeypatch.setattr(mj, "_run_crawl",
                            lambda storage_state: (_ for _ in ()).throw(AssertionError))
        assert mj.fetch_recent(s, client, 10) == []
        # clear backoff, 403 → session marked expired
        st.state = {}
        s.flush()
        monkeypatch.setattr(mj, "_run_crawl", lambda storage_state: ([], 403))
        assert mj.fetch_recent(s, client, 10) == []
        assert mj.get_state(s).state["session_expired"] is True
        assert mj.session_status(s) == "expired"
        assert mj.health(s)["status"] == "error"
        # a successful crawl with posts clears the expiry flag
        fixture = [{"url": "https://www.midjourney.com/api/explore",
                    "json": load("midjourney_jobs.json")}]
        monkeypatch.setattr(mj, "_run_crawl", lambda storage_state: (fixture, 200))
        posts = mj.fetch_recent(s, client, 2)
        assert len(posts) == 2  # limit respected
        assert mj.session_status(s) == "valid"
        client.close()


def test_scrapers_api_lists_tier2(client):
    r = client.get("/api/scrapers")
    by_name = {s["name"]: s for s in r.json()["scrapers"]}
    assert by_name["midjourney"]["status"] == "needs_setup"
    assert by_name["midjourney"]["session_status"] == "missing"
    assert by_name["seaart"]["experimental"] is True
    assert by_name["tensorart"]["status"] in ("ok", "experimental")
    # run-now on an unconfigured adapter → 409 with guidance, not a crash
    resp = client.post("/api/scrapers/midjourney/run")
    assert resp.status_code == 409
    assert "capture_login" in resp.json()["detail"]
