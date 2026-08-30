"""Settings API + storage/purge (3.9), scheduler (3.6), WS logs (3.7)."""
import os

from tests.conftest import seed_post


def test_settings_get_put_masked(client):
    r = client.get("/api/settings")
    body = r.json()
    assert body["settings"]["image_quality"] == 82
    assert "civitai_api_key" in body["secret_keys"]
    r = client.put("/api/settings", json={
        "image_quality": 75, "civitai_api_key": "sk-verysecret9876",
        "not_a_real_key": 1})
    body = r.json()
    assert body["settings"]["image_quality"] == 75
    assert body["settings"]["civitai_api_key"] == "••••9876"
    assert "not_a_real_key" not in body["applied"]
    # unchanged sentinel preserves the secret
    client.put("/api/settings", json={"civitai_api_key": "__unchanged__"})
    from promptforge import db as db_mod, settings_store
    with db_mod.session_scope() as s:
        assert settings_store.get(s, "civitai_api_key") == "sk-verysecret9876"


def test_storage_stats_and_purge(client, app_env):
    f = app_env.data_dir / "media/civitai/a.webp"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x" * 1000)
    seed_post(media_path="media/civitai/a.webp",
              params={"_original_bytes": 5000, "_stored_bytes": 1000})
    fav = seed_post(favorite=True)
    stats = client.get("/api/settings/storage").json()
    assert stats["post_count"] == 2
    assert stats["saved_bytes"] == 4000
    assert stats["disk_used_bytes"] >= 1000
    # dry run
    r = client.post("/api/settings/purge", json={"dry_run": True})
    assert r.json() == {"would_delete": 1, "dry_run": True}  # favorite kept
    # real purge
    r = client.post("/api/settings/purge", json={"dry_run": False})
    assert r.json()["deleted"] == 1
    assert not f.exists()
    assert client.get(f"/api/posts/{fav}").status_code == 200


def test_scheduler_jobs_and_reschedule(app_env, monkeypatch):
    monkeypatch.delenv("PF_DISABLE_SCHEDULER", raising=False)
    from promptforge import scheduler
    ran = []
    monkeypatch.setattr("promptforge.scrapers.runner.run_scraper",
                        lambda name, manual=False, **kw: ran.append((name, manual)))
    scheduler.start()
    try:
        assert scheduler.next_run_time("civitai") is not None
        assert scheduler.next_run_time("lexica") is not None
        assert scheduler.trigger_run("civitai") is True
        import time
        deadline = time.time() + 5
        while not ran and time.time() < deadline:
            time.sleep(0.05)
        assert ("civitai", True) in ran
        scheduler.reschedule("civitai")  # no crash
    finally:
        scheduler.shutdown()
    os.environ["PF_DISABLE_SCHEDULER"] = "1"


def test_ws_logs_history_and_live(client):
    from promptforge.logbus import bus
    bus.info("scraper.civitai", "hello from test")
    with client.websocket_connect("/api/ws/logs") as ws:
        first = ws.receive_json()
        assert first["type"] == "history"
        assert any("hello from test" in e["message"] for e in first["events"])
        bus.info("scraper.civitai", "live event")
        second = ws.receive_json()
        assert second["type"] == "event"
        assert second["event"]["message"] == "live event"


def test_run_now_endpoint_direct_thread(client, monkeypatch):
    ran = []
    monkeypatch.setattr("promptforge.scrapers.runner.run_scraper",
                        lambda name, manual=False, **kw: ran.append(name))
    r = client.post("/api/scrapers/civitai/run")
    assert r.status_code == 200 and r.json()["started"] is True
    import time
    deadline = time.time() + 3
    while not ran and time.time() < deadline:
        time.sleep(0.05)
    assert ran == ["civitai"]
