"""Minimal API tests (1.11): health, posts list/detail/patch/delete, scrapers."""
from tests.conftest import seed_post


def test_health(client, app_env):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["db"] == "ok"
    assert body["ffmpeg"] is True
    assert body["data_dir"] == str(app_env.data_dir)


def test_posts_list_cursor_and_filters(client):
    ids = [seed_post(prompt=f"post {i}", favorite=(i == 3),
                     media_type="video" if i == 4 else "image",
                     nsfw=(i == 5)) for i in range(6)]
    r = client.get("/api/posts?limit=4&nsfw=true")
    body = r.json()
    assert [it["id"] for it in body["items"]] == sorted(ids, reverse=True)[:4]
    assert body["next_cursor"] == body["items"][-1]["id"]
    # NSFW hidden by default
    all_ids = [it["id"] for it in client.get("/api/posts?limit=50").json()["items"]]
    assert ids[5] not in all_ids
    assert ids[5] in [it["id"] for it in
                      client.get("/api/posts?limit=50&nsfw=true").json()["items"]]
    # cursor page 2
    r2 = client.get(f"/api/posts?limit=4&cursor={body['next_cursor']}")
    assert all(it["id"] < body["next_cursor"] for it in r2.json()["items"])
    # filters
    assert [it["id"] for it in
            client.get("/api/posts?favorite=true").json()["items"]] == [ids[3]]
    assert [it["id"] for it in
            client.get("/api/posts?media_type=video").json()["items"]] == [ids[4]]
    assert client.get("/api/posts?model=flux").json()["items"] != []
    assert client.get("/api/posts?model=sdxl").json()["items"] == []
    assert client.get("/api/posts?platform=lexica").json()["items"] == []


def test_post_detail_and_patch(client):
    pid = seed_post(prompt="detailed prompt", negative_prompt="bad hands",
                    params={"seed": 1, "_stored_bytes": 100, "_original_bytes": 400})
    r = client.get(f"/api/posts/{pid}")
    d = r.json()
    assert d["negative_prompt"] == "bad hands"
    assert d["params"] == {"seed": 1}          # underscore params hidden
    assert d["stored_bytes"] == 100
    assert d["media_url"].startswith("/media/")
    r = client.patch(f"/api/posts/{pid}", json={"favorite": True})
    assert r.json()["favorite"] is True
    assert client.get("/api/posts/999999").status_code == 404


def test_post_delete_removes_files(client, app_env):
    media = app_env.data_dir / "media/civitai/del.webp"
    thumb = app_env.data_dir / "media/civitai/thumbs/del.webp"
    media.parent.mkdir(parents=True, exist_ok=True)
    thumb.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"x")
    thumb.write_bytes(b"x")
    pid = seed_post(media_path="media/civitai/del.webp",
                    thumb_path="media/civitai/thumbs/del.webp")
    assert client.delete(f"/api/posts/{pid}").status_code == 200
    assert not media.exists() and not thumb.exists()
    assert client.get(f"/api/posts/{pid}").status_code == 404
    # FTS cleaned
    from promptforge import db as db_mod, fts
    with db_mod.session_scope() as s:
        assert fts.search_posts(s, "red fox") == []


def test_scrapers_list_and_patch(client):
    r = client.get("/api/scrapers")
    scrapers = {s["name"]: s for s in r.json()["scrapers"]}
    assert "civitai" in scrapers and "lexica" in scrapers
    assert scrapers["civitai"]["status"] == "ok"
    assert scrapers["lexica"]["status"] == "ok"  # default terms exist
    r = client.patch("/api/scrapers/civitai",
                     json={"enabled": False, "interval_minutes": 2})
    body = r.json()
    assert body["enabled"] is False
    assert body["interval_minutes"] == 5  # clamped to min 5 (respect caching)
    assert client.patch("/api/scrapers/nope", json={}).status_code == 404


def test_media_static_served(client, app_env):
    f = app_env.data_dir / "media/civitai/thumbs/serve.webp"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"RIFF0000WEBP")
    assert client.get("/media/civitai/thumbs/serve.webp").status_code == 200
