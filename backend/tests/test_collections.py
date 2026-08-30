"""Collections API tests (3.1, 3.2, 3.4): CRUD, model-family scoping,
covers/counts, model collections, models meta."""
from tests.conftest import seed_post


def make_collection(client, name="Neon Boards"):
    r = client.post("/api/collections", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def test_collection_crud(client):
    c = make_collection(client)
    assert c["name"] == "Neon Boards" and c["count"] == 0
    assert c["model_family"] is None
    # duplicate name rejected
    assert client.post("/api/collections", json={"name": "neon boards"}).status_code == 409
    # rename + description
    r = client.patch(f"/api/collections/{c['id']}",
                     json={"name": "Neon", "description": "d"})
    assert r.json()["name"] == "Neon"
    # delete keeps posts
    pid = seed_post()
    client.post(f"/api/collections/{c['id']}/posts/{pid}")
    assert client.delete(f"/api/collections/{c['id']}").status_code == 200
    assert client.get(f"/api/posts/{pid}").status_code == 200
    assert client.get(f"/api/collections/{c['id']}").status_code == 404


def test_family_scoping(client):
    c = make_collection(client)
    flux1 = seed_post(model_family="flux", model_name="flux.1-dev")
    flux2 = seed_post(model_family="flux", model_name="Flux Pro")
    sdxl = seed_post(model_family="sdxl", model_name="SDXL")

    # first save adopts family
    r = client.post(f"/api/collections/{c['id']}/posts/{flux1}")
    assert r.status_code == 200
    assert r.json()["collection"]["model_family"] == "flux"
    # same family ok
    assert client.post(f"/api/collections/{c['id']}/posts/{flux2}").status_code == 200
    # cross family blocked with the exact guidance message
    r = client.post(f"/api/collections/{c['id']}/posts/{sdxl}")
    assert r.status_code == 409
    assert "Flux posts" in r.json()["detail"]
    assert "Allow mixed models" in r.json()["detail"]
    # enabling mixed models lifts the restriction
    client.patch(f"/api/collections/{c['id']}", json={"allow_mixed_models": True})
    assert client.post(f"/api/collections/{c['id']}/posts/{sdxl}").status_code == 200
    # counts + covers
    summary = client.get(f"/api/collections/{c['id']}").json()
    assert summary["count"] == 3
    assert len(summary["cover_urls"]) == 3


def test_unsave_and_cover_fallback(client):
    c = make_collection(client)
    p1 = seed_post(model_family="flux")
    p2 = seed_post(model_family="flux")
    client.post(f"/api/collections/{c['id']}/posts/{p1}")
    client.post(f"/api/collections/{c['id']}/posts/{p2}")
    # cover is first saved post; removing it falls back
    assert client.get(f"/api/collections/{c['id']}").json()["count"] == 2
    client.delete(f"/api/collections/{c['id']}/posts/{p1}")
    s = client.get(f"/api/collections/{c['id']}").json()
    assert s["count"] == 1
    # duplicate save is idempotent
    client.post(f"/api/collections/{c['id']}/posts/{p2}")
    assert client.get(f"/api/collections/{c['id']}").json()["count"] == 1


def test_model_collections_from_alias_map(client):
    seed_post(model_family="flux", model_name="flux.1-dev")
    seed_post(model_family="flux", model_name="FLUX.1 [dev]")
    seed_post(model_family="sdxl", model_name="SDXL 1.0", media_type="video")
    r = client.get("/api/collections")
    mc = {m["family"]: m for m in r.json()["model_collections"]}
    assert mc["flux"]["count"] == 2
    assert mc["flux"]["label"] == "Flux"
    assert "flux.1-dev" in mc["flux"]["versions"]
    assert mc["sdxl"]["video_count"] == 1


def test_models_meta(client):
    seed_post(model_family="flux", model_name="flux.1-dev")
    seed_post(model_family="flux", model_name="flux.1-schnell")
    r = client.get("/api/models/meta")
    models = {m["family"]: m for m in r.json()["models"]}
    assert models["flux"]["post_count"] == 2
    assert models["flux"]["is_new"] is True  # just seeded
    assert models["flux"]["first_seen"] is not None
    assert set(models["flux"]["versions"]) == {"flux.1-dev", "flux.1-schnell"}


def test_alias_rules_renormalize(client):
    seed_post(model_family="majicmix-realistic", model_name="majicMIX realistic")
    r = client.put("/api/models/aliases",
                   json={"user_rules": {"majicmix": "sd15"}})
    assert r.status_code == 200
    models = {m["family"] for m in client.get("/api/models/meta").json()["models"]}
    assert "sd15" in models and "majicmix-realistic" not in models
