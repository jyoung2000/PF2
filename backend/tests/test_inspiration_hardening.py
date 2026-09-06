"""Inspiration 2.0 I16 — hardening: the auth lifecycle, performance at scale,
and the additive migration of everything Inspiration 2.0 added.

None of these need a browser, an AI provider, or the network.
"""
from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

from promptforge import config as cfg_mod
from promptforge import db as db_mod
from promptforge.main import create_app
from promptforge.models import BrowserWorkflow, Creator, CreatorLink, Post, ResearchJob
from promptforge.scrapers import get_adapter
from tests.conftest import seed_post


# ------------------------------------------------------- auth lifecycle -----
def test_session_lifecycle_upload_expire_recover_disconnect(app_env):
    """A browser source's login has four states and PF2 must report each
    truthfully: missing → connected → expired → disconnected. Nothing here
    ever reads or returns the session's contents (§38)."""
    client = TestClient(create_app())
    adapter = get_adapter("x")

    def report() -> dict:
        rows = {s["name"]: s for s in client.get("/api/scrapers").json()["scrapers"]}
        return rows["x"]

    # 1. missing — honest, and never an error
    assert report()["session_status"] == "missing"
    with db_mod.session_scope() as s:
        assert not adapter.is_configured(s)
        assert "connect" in (adapter.needs_setup_reason(s) or "").lower()

    # 2. connected — uploaded through the documented REST route
    state = json.dumps({"cookies": [{"name": "auth_token", "value": "s3cret",
                                     "domain": ".x.com", "path": "/"}], "origins": []})
    r = client.post("/api/scrapers/x/session",
                    files={"file": ("x.json", state, "application/json")})
    assert r.status_code == 200 and "s3cret" not in r.text
    assert report()["session_status"] == "valid"
    with db_mod.session_scope() as s:
        assert adapter.is_configured(s)

    # 3. expired — a 401 from the site flips the flag; the file is NOT deleted,
    #    so the user is told to reconnect rather than silently losing state
    with db_mod.session_scope() as s:
        st = adapter.get_state(s)
        st.state = {**(st.state or {}), "session_expired": True}
    assert report()["session_status"] == "expired"
    assert adapter.storage_state_path().is_file()

    # 4. a fresh upload clears the expired flag
    client.post("/api/scrapers/x/session", files={"file": ("x.json", state, "application/json")})
    assert report()["session_status"] == "valid"

    # 5. disconnect removes the file and keeps the posts
    kept = seed_post(platform="x", platform_post_id="keepme")
    assert client.delete("/api/scrapers/x/session").status_code == 200
    assert not adapter.storage_state_path().exists()
    assert report()["session_status"] == "missing"
    with db_mod.session_scope() as s:
        assert s.get(Post, kept) is not None

    # and the session was never served anywhere along the way
    for path in ("/api/scrapers", "/api/settings", "/api/inspiration/browser"):
        assert "s3cret" not in client.get(path).text


def test_session_upload_rejects_junk_and_oversized_payloads(app_env):
    client = TestClient(create_app())
    assert client.post("/api/scrapers/x/session",
                       files={"file": ("x.json", "not json at all", "application/json")}
                       ).status_code == 422
    assert client.post("/api/scrapers/x/session",
                       files={"file": ("x.json", json.dumps({"nope": 1}), "application/json")}
                       ).status_code == 422
    big = json.dumps({"cookies": [{"name": "x", "value": "y" * 3_000_000}]})
    r = client.post("/api/scrapers/x/session", files={"file": ("x.json", big, "application/json")})
    assert r.status_code == 422 and "too large" in r.text
    # a source with no session concept says so instead of pretending
    assert client.post("/api/scrapers/reddit/session",
                       files={"file": ("r.json", "{}", "application/json")}).status_code == 404


# ------------------------------------------------------------ performance ---
def test_a_thousand_posts_stay_responsive(app_env):
    """§: the library has to work at real size. 1k posts, then the queries the
    Inspiration screens actually issue."""
    from promptforge import fts
    from promptforge.models import Creator as C
    now_platforms = ["x", "reddit", "bluesky", "civitai", "youtube"]
    with db_mod.session_scope() as s:
        creators = []
        for i in range(20):
            c = C(platform=now_platforms[i % 5], handle=f"creator{i}", stats={})
            s.add(c)
            creators.append(c)
        s.flush()
        creator_ids = [c.id for c in creators]
        for i in range(1000):
            p = Post(platform=now_platforms[i % 5], platform_post_id=f"perf-{i}",
                     media_type="video" if i % 3 == 0 else "image",
                     prompt=f"neon alley {i}, volumetric fog, 35mm anamorphic, cinematic",
                     prompt_source="explicit_caption" if i % 2 else "deterministic_inference",
                     model_name="Flux" if i % 2 else "Kling",
                     model_family="flux" if i % 2 else "kling",
                     model_source="explicit", creator_id=creator_ids[i % 20],
                     engagement_total=i * 7, inspiration_score=(i % 100),
                     technique_tags=["orbit"] if i % 4 == 0 else [],
                     media_path=f"media/x/{i}.webp", params={}, assertions={},
                     observed={}, analysis={})
            s.add(p)
            if i % 200 == 0:
                s.flush()
        s.flush()
        for p in s.query(Post).limit(1000):
            fts.index_post(s, p.id, p.prompt, p.model_name, [])

    client = TestClient(create_app())
    budget = {
        "/api/posts?limit=60": 2.0,
        "/api/search?q=neon+alley&limit=60": 2.5,
        "/api/search?q=has:prompt+sort:inspiration&limit=60": 2.5,
        "/api/search?q=prompt_source:explicit+source:reddit&limit=60": 2.5,
        "/api/inspiration/discover?mode=best_prompts&limit=40": 6.0,
        "/api/inspiration/analytics": 6.0,
        "/api/inspiration/analytics/signals?weeks=8": 8.0,
        "/api/inspiration/creators?limit=60": 8.0,
    }
    slow = []
    for path, limit in budget.items():
        started = time.perf_counter()
        r = client.get(path)
        elapsed = time.perf_counter() - started
        assert r.status_code == 200, f"{path} → {r.status_code}"
        if elapsed > limit:
            slow.append(f"{path}: {elapsed:.2f}s (budget {limit}s)")
    assert not slow, "queries too slow at 1k posts:\n" + "\n".join(slow)


def test_search_returns_a_bounded_page_not_the_whole_library(app_env):
    for i in range(300):
        seed_post(platform="x", platform_post_id=f"page-{i}", prompt=f"fox {i}")
    client = TestClient(create_app())
    body = client.get("/api/posts?limit=60").json()
    assert len(body["items"]) == 60 and body["next_cursor"] is not None
    nxt = client.get(f"/api/posts?limit=60&cursor={body['next_cursor']}").json()
    assert len(nxt["items"]) == 60
    assert {i["id"] for i in body["items"]} & {i["id"] for i in nxt["items"]} == set()


# ------------------------------------------------------------- migration ----
def test_inspiration_2_tables_and_columns_are_added_to_a_legacy_db(tmp_path, app_env):
    """§89: a DB written before Inspiration 2.0 boots, keeps every row, and
    gains the new tables and columns — nothing is dropped or rewritten."""
    db_mod.dispose_db()
    cfg = cfg_mod.Config(data_dir=tmp_path / "pre_i2")
    cfg_mod.set_config(cfg)
    cfg.ensure_dirs()
    con = sqlite3.connect(cfg.db_path)
    # an I7-shaped posts table: the intel envelope exists, the I11 ladder does not
    con.execute("""CREATE TABLE posts (
        id INTEGER PRIMARY KEY, platform VARCHAR(50), platform_post_id VARCHAR(200),
        prompt TEXT, media_type VARCHAR(10), params JSON, scraped_at DATETIME,
        favorite BOOLEAN, media_path TEXT, observed JSON, assertions JSON,
        analysis JSON, inspiration_score FLOAT, creator_id INTEGER)""")
    con.execute("""CREATE TABLE creators (
        id INTEGER PRIMARY KEY, platform VARCHAR(20), handle VARCHAR(100),
        stats JSON, updated_at DATETIME)""")
    con.execute("INSERT INTO creators VALUES (3, 'x', 'mara', '{\"posts\": 4}', "
                "'2025-06-01 00:00:00')")
    con.execute("INSERT INTO posts VALUES (11, 'x', 'old-1', 'a prompt from before', 'image', "
                "'{\"seed\": 7}', '2025-06-01 00:00:00', 1, 'media/x/old.webp', "
                "'{\"author\": {\"handle\": \"mara\"}}', '{}', '{}', 71.5, 3)")
    con.commit()
    con.close()

    engine = db_mod.init_db()
    with db_mod.session_scope() as s:
        post = s.get(Post, 11)
        assert post.prompt == "a prompt from before" and post.favorite is True
        assert post.params == {"seed": 7} and post.inspiration_score == 71.5
        assert post.observed["author"]["handle"] == "mara"     # untouched
        assert post.prompt_source is None                      # new column, no guess
        assert s.get(Creator, 3).stats == {"posts": 4}
        # the new tables exist and accept rows
        s.add(BrowserWorkflow(source="tiktok", task="search", actions=[], version=1))
        s.add(ResearchJob(query="kling prompts", status="queued"))
        c2 = Creator(platform="reddit", handle="mara_makes", stats={})
        s.add(c2)
        s.flush()
        s.add(CreatorLink(creator_a=3, creator_b=c2.id, confidence=0.9,
                          evidence={"kind": "same_media"}))
    assert db_mod.migrate_schema(engine) == []                 # idempotent

    cols = {c[1] for c in sqlite3.connect(cfg.db_path).execute("PRAGMA table_info(posts)")}
    assert {"prompt_source", "content_hash", "phash", "has_workflow"} <= cols
    tables = {r[0] for r in sqlite3.connect(cfg.db_path).execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"browser_workflows", "research_jobs", "creator_links"} <= tables

    # and the app serves that legacy row through the new screens
    client = TestClient(create_app())
    assert client.get("/api/inspiration/posts/11/intel").status_code == 200
    ident = client.get("/api/inspiration/creators/3/identity").json()
    assert ident["platforms"] == ["reddit", "x"] and ident["merged"] is False
