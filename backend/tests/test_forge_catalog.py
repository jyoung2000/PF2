"""Model Intelligence Registry (spec §2): seed lifecycle, additive merge,
parameter validation, registry merge with pricing offers."""
import json

from promptforge.forge import catalog


def test_seed_copied_to_data_dir_and_all_families_normalized(app_env):
    fams = catalog.load_families()
    assert catalog.catalog_path().exists()          # D16 lifecycle
    assert len(fams) >= 15
    for entry in fams.values():                     # §2 schema always complete
        for field in ("modality", "supports", "prompt", "licensing",
                      "strengths", "fallback_families", "last_verified"):
            assert field in entry
        assert set(catalog.SUPPORT_FLAGS) <= set(entry["supports"])


def test_user_copy_wins_and_merges_additively(app_env):
    catalog.install_catalog()
    path = catalog.catalog_path()
    doc = json.loads(path.read_text())
    # user edits one field and deletes another family entirely
    doc["families"]["kling"]["max_duration_s"] = 99
    del doc["families"]["kling"]["strengths"]
    path.write_text(json.dumps(doc))
    fams = catalog.load_families()
    assert fams["kling"]["max_duration_s"] == 99            # user value wins
    assert fams["kling"]["strengths"]                       # seed fills the gap
    # save_family persists and keeps unknown keys out
    catalog.save_family("kling", {"quality_prior": 0.99, "hacked": True})
    fams = catalog.load_families()
    assert fams["kling"]["quality_prior"] == 0.99
    assert "hacked" not in fams["kling"]


def test_validate_params_aspect_duration_references(app_env):
    v = catalog.validate_params("kling", {"aspect_ratio": "4:5", "duration_s": 30})
    assert not v["ok"]
    by_param = {x["param"]: x for x in v["violations"]}
    assert by_param["aspect_ratio"]["nearest"] in ("1:1", "9:16", "16:9")
    assert v["params"]["duration_s"] == 10                  # clamped to the cap

    # references against a family that doesn't declare them
    v = catalog.validate_params("sd3", {"_inputs": {"references": ["a.png"]}})
    assert not v["ok"] and v["violations"][0]["param"] == "references"

    # negative prompt on a family without support → warning, not violation
    v = catalog.validate_params("flux", {"negative_prompt": "blurry"})
    assert v["ok"] and any("negative" in w for w in v["warnings"])

    # unknown family never fails hard
    v = catalog.validate_params("mystery", {"aspect_ratio": "77:1"})
    assert v["ok"] and v["warnings"]


def test_registry_endpoint_merges_offers_and_connection(client):
    r = client.get("/api/forge/models").json()
    fams = {m["family"]: m for m in r["models"]}
    assert fams["flux"]["offers"], "pricing offers merged in"
    assert fams["flux"]["generatable"] is False             # nothing connected
    assert any(p["name"] == "fal" for p in r["providers"])
    assert any(p["kind"] == "local" and p["free"] for p in r["providers"])
    # per-family fetch + validate endpoint
    one = client.get("/api/forge/models/kling").json()
    assert one["modality"] == "video" and one["max_duration_s"]
    v = client.post("/api/forge/models/kling/validate",
                    json={"params": {"duration_s": 30}}).json()
    assert v["violations"]
    # user edit through the API wins afterwards
    client.put("/api/forge/models/kling", json={"latency_class": "fast"})
    assert client.get("/api/forge/models/kling").json()["latency_class"] == "fast"
    assert client.get("/api/forge/models/nope").status_code == 404
