"""Phase S1 — Film Studio data model + asset services: additive migration,
immutable (copy-on-write) versions, restore/duplicate/compare/use-as-current,
references (upload/import/primary/dedupe) with traversal-proof storage,
canonical visual context, delete guards, explicit version propagation, and
project/scene/shot structure through the API."""
from __future__ import annotations

import io
import sqlite3

import pytest
from PIL import Image

from promptforge import config as cfg_mod
from promptforge import db as db_mod
from promptforge.film import assets as asset_svc
from promptforge.film import attributes, context as ctx_mod
from promptforge.film import projects as proj_svc
from promptforge.film import storage
from promptforge.film.models import FilmAssetVersion, FilmShotAsset
from tests.conftest import seed_post


def _png(w=64, h=48, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- migration -
def test_film_tables_are_added_to_a_legacy_db(tmp_path, app_env):
    db_mod.dispose_db()
    cfg = cfg_mod.Config(data_dir=tmp_path / "legacy")
    cfg_mod.set_config(cfg)
    cfg.ensure_dirs()
    con = sqlite3.connect(cfg.db_path)
    con.execute("""CREATE TABLE posts (
        id INTEGER PRIMARY KEY, platform VARCHAR(50), platform_post_id VARCHAR(200),
        prompt TEXT, media_type VARCHAR(10), params JSON, scraped_at DATETIME,
        favorite BOOLEAN, media_path TEXT)""")
    con.execute("INSERT INTO posts VALUES (3, 'civitai', 'legacy-3', 'legacy fox', 'image', '{}', "
                "'2025-01-01 00:00:00', 0, 'media/civitai/old.webp')")
    con.commit()
    con.close()
    engine = db_mod.init_db()
    tables = {r[0] for r in sqlite3.connect(cfg.db_path).execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"film_projects", "film_scenes", "film_shots", "film_assets", "film_asset_versions",
            "film_asset_refs", "film_shot_assets", "film_takes", "film_events", "film_gates",
            "film_clips", "film_jobs"} <= tables
    assert db_mod.migrate_schema(engine) == []
    with db_mod.session_scope() as s:
        from promptforge.models import Post
        assert s.get(Post, 3).prompt == "legacy fox"
        a = asset_svc.create_asset(s, "prop", "Lantern")
        assert a.current_version_id
    assert (cfg.film_dir / "assets").is_dir()


# --------------------------------------------------------- versions (CoW) ---
def test_versions_are_copy_on_write_and_never_rewrite_used_ones(app_env):
    with db_mod.session_scope() as s:
        jack = asset_svc.create_asset(s, "character", "Jack",
                                      data={"eyes": "green", "hair": "black", "age": "34"})
        v1 = asset_svc.current_version(s, jack)
        assert v1.number == 1 and v1.locks == ["face", "hair", "body"]  # schema defaults
        assert v1.frozen is False

        # unfrozen ⇒ edits land in place
        v, created = asset_svc.edit_version(s, jack, {"hair": "brown"})
        assert created is False and v.id == v1.id and v.data["hair"] == "brown"

        # a shot pins v1 → frozen
        p = proj_svc.create_project(s, "Test")
        sc = proj_svc.create_scene(s, p, "Warehouse")
        sh = proj_svc.create_shot(s, sc, "Jack enters")
        pin = proj_svc.pin_asset(s, sh, jack)
        assert pin.version_id == v1.id and v1.frozen is True

        # editing a frozen version creates v2; v1 untouched; the shot keeps v1
        v2, created = asset_svc.edit_version(s, jack, {"hair": "grey"}, locks=["face", "body"])
        assert created is True and v2.number == 2 and v2.data["hair"] == "grey"
        assert v2.locks == ["face", "body"] and v2.provenance["from_version_id"] == v1.id
        s.refresh(v1)
        assert v1.data["hair"] == "brown" and v1.locks == ["face", "hair", "body"]
        assert jack.current_version_id == v2.id
        assert s.get(FilmShotAsset, pin.id).version_id == v1.id
        assert asset_svc.version_usage(s, v1.id)["shots"] == [sh.id]

        # restore v1 → new v3 (history intact), current = v3
        v3 = asset_svc.restore_version(s, jack, v1.id)
        assert v3.number == 3 and v3.data["hair"] == "brown" and jack.current_version_id == v3.id
        assert v3.provenance == {"source": "restore", "from_version_id": v1.id, "actor": "user"}
        # duplicate v2 → v4 but current stays v3
        v4 = asset_svc.duplicate_version(s, jack, v2.id)
        assert v4.number == 4 and v4.data["hair"] == "grey" and jack.current_version_id == v3.id
        assert v4.label == "copy of v2"
        # use as current
        asset_svc.use_as_current(s, jack, v4.id)
        assert jack.current_version_id == v4.id
        # compare
        cmp = asset_svc.compare_versions(s, v1.id, v2.id)
        assert cmp["changed"] == {"hair": {"a": "brown", "b": "grey"}}
        assert cmp["locks"]["unlocked_in_b"] == ["hair"] and cmp["identical"] is False
        assert asset_svc.compare_versions(s, v2.id, v4.id)["identical"] is True
        assert [v.number for v in asset_svc.versions_of(s, jack.id)] == [1, 2, 3, 4]
        # every superseded version is frozen; explicit "save as new version" works too
        assert all(v.frozen for v in asset_svc.versions_of(s, jack.id)[:3])
        v5, created = asset_svc.edit_version(s, jack, {"age": "35"}, force_new=True, label="older")
        assert created and v5.number == 5 and v5.label == "older" and v5.data["hair"] == "grey"
        # removing an unknown/empty value drops it; unknown keys are kept
        v6, _ = asset_svc.edit_version(s, jack, {"age": None, "scar_story": "fell off a bike"})
        assert "age" not in v6.data and v6.data["scar_story"] == "fell off a bike"


# ------------------------------------------------------- canonical context --
def test_canonical_context_separates_locked_from_variable(app_env):
    with db_mod.session_scope() as s:
        loc = asset_svc.create_asset(
            s, "location", "Warehouse",
            data={"architecture": "brick industrial hall", "layout": "open floor, mezzanine",
                  "lighting": "sodium practicals", "weather": "rain", "zones": ["loading bay", "office"]},
            continuity_rules=["mezzanine stairs stay on the left"],
            negative_constraints=["no modern LED panels"])
        ctx = asset_svc.context_for(s, loc)
        assert ctx["type"] == "location" and ctx["version"] == 1
        assert set(ctx["locked_groups"]) == {"architecture", "layout", "materials", "furniture"}
        locked_fields = {a["field"] for a in ctx["locked_attributes"]}
        assert locked_fields == {"architecture", "layout", "zones"}
        variable_fields = {a["field"] for a in ctx["variable_attributes"]}
        assert variable_fields == {"lighting", "weather"}
        assert ctx["identity_anchors"][0] == "Warehouse"
        assert any("brick industrial hall" in a for a in ctx["identity_anchors"])
        assert ctx["continuity_rules"] == ["mezzanine stairs stay on the left"]
        prose = ctx_mod.describe(ctx)
        assert prose.startswith("Warehouse (location v1)")
        assert "LOCKED — architecture: brick industrial hall" in prose
        assert "Never: no modern LED panels" in prose
        # the same version always yields the same prose
        assert prose == ctx_mod.describe(asset_svc.context_for(s, loc))
        # schema drives the editors
        assert attributes.default_locks("character") == ["face", "hair", "body"]
        assert "portrait" in attributes.ref_kinds("character")
        assert attributes.valid_locks("character", ["face", "bogus", "face"]) == ["face"]


# ------------------------------------------------------------- references --
def test_reference_upload_import_primary_and_traversal_protection(client, app_env):
    a = client.post("/api/film/assets", json={"type": "character", "name": "Sarah",
                                              "tags": ["Lead", "lead"]}).json()
    assert a["tags"] == ["lead"] and a["current_version"]["locks"] == ["face", "hair", "body"]
    aid = a["id"]

    up = client.post(f"/api/film/assets/{aid}/refs", files={"file": ("p.png", _png(), "image/png")},
                     data={"kind": "portrait", "label": "hero portrait"})
    assert up.status_code == 200, up.text
    ref = up.json()["ref"]
    assert ref["kind"] == "portrait" and ref["width"] == 64 and ref["height"] == 48
    assert ref["url"].startswith("/film-media/assets/") and ref["thumb_url"].endswith(".webp")
    # original preserved byte-for-byte; served by both routes
    assert client.get(ref["url"]).content == _png()
    assert client.get(f"/api/film/refs/{ref['id']}/file").content == _png()
    assert client.get(f"/api/film/refs/{ref['id']}/file?thumb=true").status_code == 200
    # first reference becomes the version's primary automatically
    detail = client.get(f"/api/film/assets/{aid}").json()
    assert detail["current_version"]["primary_ref_id"] == ref["id"]
    assert detail["thumb_url"] == ref["thumb_url"]
    # identical bytes are deduped, not written twice
    again = client.post(f"/api/film/assets/{aid}/refs", files={"file": ("p2.png", _png(), "image/png")},
                        data={"kind": "front"}).json()
    assert again["deduped"] is True and again["ref"]["id"] == ref["id"]
    # garbage is refused; wrong type is refused
    assert client.post(f"/api/film/assets/{aid}/refs",
                       files={"file": ("x.png", b"not an image", "image/png")}).status_code == 422
    assert client.post(f"/api/film/assets/{aid}/refs",
                       files={"file": ("x.gif", _png(), "image/gif")}).status_code == 422

    # import from the Gallery keeps attribution
    media = app_env.data_dir / "media" / "civitai" / "x.webp"
    media.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (10, 200, 10)).save(media, "WEBP")
    pid = seed_post(prompt="portrait of a woman, 85mm", author="artist", source_url="https://civitai.com/p/1")
    imp = client.post(f"/api/film/assets/{aid}/refs/import",
                      json={"post_id": pid, "kind": "three_quarter", "primary": True}).json()
    assert imp["ref"]["source"] == f"post:{pid}" and imp["ref"]["source_post_id"] == pid
    assert imp["ref"]["provenance"]["author"] == "artist"
    assert imp["ref"]["provenance"]["source_url"] == "https://civitai.com/p/1"
    detail = client.get(f"/api/film/assets/{aid}").json()
    assert detail["current_version"]["primary_ref_id"] == imp["ref"]["id"]
    assert detail["ref_count"] == 2
    assert client.post(f"/api/film/assets/{aid}/refs/import", json={"post_id": 999}).status_code == 422

    # primary switch + delete
    assert client.post(f"/api/film/refs/{ref['id']}/primary").json()["primary_ref_id"] == ref["id"]
    assert client.delete(f"/api/film/refs/{ref['id']}").json() == {"deleted": ref["id"]}
    assert client.get(f"/api/film/refs/{ref['id']}/file").status_code == 404
    assert client.get(ref["url"]).status_code == 404
    detail = client.get(f"/api/film/assets/{aid}").json()
    assert detail["current_version"]["primary_ref_id"] == imp["ref"]["id"]  # falls back to remaining ref

    # traversal: nothing outside DATA_DIR/film is ever resolvable or served
    for bad in ("film/../promptforge.db", "/etc/passwd", "media/civitai/x.webp", "film",
                "film/assets/1/refs/../../../promptforge.db", "film\\assets\\1\\x.png", ""):
        with pytest.raises(storage.UnsafePath):
            storage.resolve(bad)
    with pytest.raises(storage.UnsafePath):
        storage.asset_rel(1, "refs", "../x.png")
    with pytest.raises(storage.UnsafePath):
        storage.asset_rel(1, "../refs", "x.png")
    assert storage.url_for("film/../promptforge.db") is None
    # the /film-media mount itself refuses to leave DATA_DIR/film (clients
    # normalise dot segments, so exercise Starlette's lookup directly too)
    from starlette.staticfiles import StaticFiles
    sf = StaticFiles(directory=app_env.film_dir)
    for rel in ("../promptforge.db", "assets/../../promptforge.db", "/etc/passwd"):
        assert sf.lookup_path(rel)[1] is None
    for url in ("/film-media/../promptforge.db", "/film-media/assets/../../promptforge.db",
                "/film-media/%2e%2e/promptforge.db"):
        r = client.get(url)
        assert r.status_code in (200, 400, 404)
        assert not r.content.startswith(b"SQLite format 3")


# --------------------------------------------- delete guard + propagation --
def test_delete_guard_and_explicit_version_propagation(app_env):
    with db_mod.session_scope() as s:
        jack = asset_svc.create_asset(s, "character", "Jack", data={"hair": "black"})
        v1 = asset_svc.current_version(s, jack)
        p = proj_svc.create_project(s, "Film")
        sc1 = proj_svc.create_scene(s, p, "Scene 1", defaults={"assets": [{"asset_id": jack.id}]})
        sc2 = proj_svc.create_scene(s, p, "Scene 2", defaults={"assets": [{"asset_id": jack.id}]})
        assert sc1.defaults["assets"][0]["version_id"] == v1.id and v1.frozen  # scene default pins exactly
        a = proj_svc.create_shot(s, sc1, "A")
        b = proj_svc.create_shot(s, sc1, "B")
        c = proj_svc.create_shot(s, sc2, "C")
        d = proj_svc.create_shot(s, sc2, "D")
        eff = lambda sh, sc: {e["asset_id"]: (e["version_id"], e["source"]) for e in proj_svc.effective_assets(s, sh, sc)}
        assert eff(a, sc1)[jack.id] == (v1.id, "scene")

        with pytest.raises(asset_svc.AssetInUse):
            asset_svc.delete_asset(s, jack)

        v2, created = asset_svc.edit_version(s, jack, {"hair": "grey"})
        assert created and v2.number == 2
        # nothing moved yet: the current asset changed, shots did not
        assert eff(b, sc1)[jack.id] == (v1.id, "scene")

        # future from B: A keeps v1 (explicit pin), B/C/D move to v2 via scene defaults
        r = asset_svc.propagate_version(s, jack, v2.id, "future", from_shot_id=b.id)
        assert set(r["updated_scenes"]) == {sc1.id, sc2.id}
        assert eff(a, sc1)[jack.id] == (v1.id, "shot")
        assert eff(b, sc1)[jack.id] == (v2.id, "scene")
        assert eff(c, sc2)[jack.id] == (v2.id, "scene")
        assert eff(d, sc2)[jack.id] == (v2.id, "scene")

        # selected: only C goes back to v1
        r = asset_svc.propagate_version(s, jack, v1.id, "selected", shot_ids=[c.id])
        assert r["updated_shots"] == [c.id]
        assert eff(c, sc2)[jack.id] == (v1.id, "shot") and eff(d, sc2)[jack.id] == (v2.id, "scene")

        # project: everything (pins + defaults) on v2
        r = asset_svc.propagate_version(s, jack, v2.id, "project", project_id=p.id)
        assert set(r["updated_shots"]) == {a.id, c.id}
        for sh, sc in ((a, sc1), (b, sc1), (c, sc2), (d, sc2)):
            assert eff(sh, sc)[jack.id][0] == v2.id
        usage = asset_svc.asset_usage(s, jack.id)
        assert usage["project_ids"] == [p.id] and {x["shot_id"] for x in usage["shots"]} == {a.id, c.id}

        # force delete unpins everywhere and removes scene references
        asset_svc.delete_asset(s, jack, force=True)
        s.refresh(sc1)
        assert sc1.defaults["assets"] == []
        assert s.execute(__import__("sqlalchemy").select(FilmShotAsset)).first() is None
        assert s.execute(__import__("sqlalchemy").select(FilmAssetVersion)).first() is None


# ------------------------------------------------------- structure via API --
def test_project_scene_shot_api_and_outfits(client, app_env):
    p = client.post("/api/film/projects", json={"title": "Rainy City",
                                                "settings": {"default_scene_gap_s": 1.0,
                                                             "budget": {"mode": "cap", "cap_usd": 20}}}).json()
    assert p["settings"]["default_scene_gap_s"] == 1.0
    assert p["settings"]["budget"] == {"mode": "cap", "threshold_usd": 5.0, "cap_usd": 20}
    assert p["settings"]["continuity_mode"] == "balanced" and p["scenes"] == []
    pid = p["id"]
    assert client.post("/api/film/projects", json={"title": "  "}).status_code == 422

    s1 = client.post(f"/api/film/projects/{pid}/scenes", json={"title": "Street", "intent": "hook"}).json()
    s2 = client.post(f"/api/film/projects/{pid}/scenes", json={"title": "Warehouse", "gap_after_s": 2.0}).json()
    assert (s1["position"], s2["position"]) == (0, 1) and s2["gap_after_s"] == 2.0
    # explicit null resets the scene gap to "inherit"
    s2 = client.patch(f"/api/film/scenes/{s2['id']}", json={"gap_after_s": None}).json()
    assert s2["gap_after_s"] is None
    s2 = client.patch(f"/api/film/scenes/{s2['id']}", json={"transition": "dissolve"}).json()
    assert s2["transition"] == {"kind": "dissolve", "duration_s": 0.5}

    a1 = client.post(f"/api/film/scenes/{s1['id']}/shots", json={"title": "wide", "duration_s": 6}).json()
    a2 = client.post(f"/api/film/scenes/{s1['id']}/shots", json={"title": "close", "duration_s": 2.5,
                                                                 "media_strategy": "stock",
                                                                 "overrides": {"camera": {"shot_size": "close_up"},
                                                                               "bogus": 1},
                                                                 "locks": ["camera"]}).json()
    assert a1["label"] == "1.1" and a2["label"] == "1.2" and a2["media_strategy"] == "stock"
    assert a2["overrides"] == {"camera": {"shot_size": "close_up"}} and a2["locks"] == ["camera"]
    re = client.post(f"/api/film/scenes/{s1['id']}/shots/reorder", json={"ids": [a2["id"], a1["id"]]}).json()
    assert [x["id"] for x in re["shots"]] == [a2["id"], a1["id"]]
    dup = client.post(f"/api/film/shots/{a1['id']}/duplicate").json()
    assert dup["title"] == "wide (copy)" and dup["position"] == 2 and dup["duration_s"] == 6
    mv = client.post(f"/api/film/shots/{dup['id']}/move", json={"scene_id": s2["id"]}).json()
    assert mv["scene_id"] == s2["id"] and mv["label"] == "2.1"

    # character with an outfit child; pin exact versions to a shot
    jack = client.post("/api/film/assets", json={"type": "character", "name": "Jack",
                                                 "data": {"eyes": "green"}}).json()
    coat = client.post("/api/film/assets", json={"type": "outfit", "name": "Rain coat",
                                                 "owner_asset_id": jack["id"],
                                                 "data": {"is_default": True, "colors": "olive"}}).json()
    assert coat["owner_asset_id"] == jack["id"]
    jack_full = client.get(f"/api/film/assets/{jack['id']}").json()
    assert [o["name"] for o in jack_full["outfits"]] == ["Rain coat"]
    listing = client.get("/api/film/assets?type=character").json()["assets"]
    assert [x["name"] for x in listing] == ["Jack"]          # outfits are children, not top level
    assert client.get("/api/film/assets?type=outfit").json()["assets"] == []
    assert [x["name"] for x in client.get(f"/api/film/assets?owner_asset_id={jack['id']}").json()["assets"]] == ["Rain coat"]
    assert client.post("/api/film/assets", json={"type": "prop", "name": "Key",
                                                 "owner_asset_id": jack["id"]}).status_code == 422

    pinned = client.post(f"/api/film/shots/{a1['id']}/assets", json={"asset_id": jack["id"]}).json()
    entry = next(e for e in pinned["assets"] if e["asset_id"] == jack["id"])
    assert entry["version_id"] == jack["current_version_id"] and entry["source"] == "shot"
    assert entry["is_current"] is True
    # editing Jack now creates v2 and the shot keeps v1
    edit = client.post(f"/api/film/assets/{jack['id']}/versions", json={"changes": {"eyes": "blue"}}).json()
    assert edit["created"] is True and edit["version"]["number"] == 2
    shot = client.get(f"/api/film/shots/{a1['id']}").json()
    entry = next(e for e in shot["assets"] if e["asset_id"] == jack["id"])
    assert entry["version"] == 1 and entry["is_current"] is False
    versions = client.get(f"/api/film/assets/{jack['id']}/versions").json()
    assert versions["versions"][0]["usage"]["shots"] == [a1["id"]] and versions["versions"][0]["frozen"]
    assert client.get(f"/api/film/assets/{jack['id']}/compare?a={versions['versions'][0]['id']}"
                      f"&b={versions['versions'][1]['id']}").json()["changed"] == {"eyes": {"a": "green", "b": "blue"}}
    # delete guard through the API
    assert client.delete(f"/api/film/assets/{jack['id']}").status_code == 409
    assert client.delete(f"/api/film/shots/{a1['id']}/assets/{jack['id']}").json()["removed"] is True
    assert client.delete(f"/api/film/assets/{jack['id']}").status_code == 200
    assert client.get(f"/api/film/assets/{coat['id']}").status_code == 404   # child gone with the parent

    # version actions via the API
    loc = client.post("/api/film/assets", json={"type": "location", "name": "Docks",
                                                "data": {"weather": "rain"}}).json()
    v1 = loc["current_version_id"]
    e = client.post(f"/api/film/assets/{loc['id']}/versions",
                    json={"changes": {"weather": "fog"}, "new_version": True, "label": "foggy"}).json()
    assert e["created"] and e["version"]["label"] == "foggy"
    r = client.post(f"/api/film/assets/{loc['id']}/versions/{v1}/restore").json()
    assert r["version"]["number"] == 3 and r["version"]["data"]["weather"] == "rain"
    d = client.post(f"/api/film/assets/{loc['id']}/versions/{e['version']['id']}/duplicate").json()
    assert d["version"]["number"] == 4 and d["asset"]["current_version_id"] == r["version"]["id"]
    u = client.post(f"/api/film/assets/{loc['id']}/versions/{d['version']['id']}/use").json()
    assert u["asset"]["current_version_id"] == d["version"]["id"]
    assert client.post(f"/api/film/assets/{loc['id']}/versions/{v1}/explode").status_code == 404
    ctx = client.get(f"/api/film/assets/{loc['id']}/context").json()
    assert ctx["context"]["version"] == 4 and "Docks" in ctx["prose"]

    # metadata patch + approval logs a gate event; events are readable per project
    client.patch(f"/api/film/assets/{loc['id']}", json={"favorite": True, "approved": True,
                                                        "project_id": pid})
    ev = client.get(f"/api/film/projects/{pid}/events").json()["events"]
    assert any(x["kind"] == "gate" and "Approved" in x["title"] for x in ev)
    assert any("created" in x["title"] for x in ev)

    # project deep dict + delete cascades
    deep = client.get(f"/api/film/projects/{pid}").json()
    assert deep["scene_count"] == 2 and deep["shot_count"] == 3
    assert [sc["title"] for sc in deep["scenes"]] == ["Street", "Warehouse"]
    assert client.delete(f"/api/film/projects/{pid}").json() == {"deleted": pid}
    assert client.get(f"/api/film/shots/{a1['id']}").status_code == 404
    assert client.get("/api/film/projects").json()["projects"] == []


def test_schema_endpoint(client):
    sch = client.get("/api/film/schema").json()
    assert sch["asset_types"] == ["character", "location", "prop", "vehicle", "outfit", "style"]
    assert sch["schemas"]["character"]["lock_groups"][0]["key"] == "face"
    assert "ai_video" in sch["media_strategies"] and sch["default_settings"]["default_scene_gap_s"] == 0.5
