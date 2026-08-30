"""Knowledge engine tests (6.x): foundation, stats, files+cap, engine with
mocked LLM, budget, techniques, style profiles, packs."""
import json

import pytest

from promptforge import db as db_mod, settings_store
from promptforge.knowledge import engine, files, packs, stats, techniques
from promptforge.llm import client as llm_client
from promptforge.models import Collection, CollectionPost, Post
from tests.conftest import seed_post


@pytest.fixture()
def mock_llm(app_env):
    llm_client.mock_instance.responses = []
    llm_client.mock_instance.calls = []
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "mock")
    yield llm_client.mock_instance
    llm_client.mock_instance.responses = []


def test_foundation_installs_and_under_cap(app_env):
    files.install_foundation()
    path = files.foundation_path()
    assert path.exists()
    assert path.stat().st_size < files.SIZE_CAP
    fm, body = files.read_md(path)
    assert fm["kind"] == "foundation"
    for topic in ("Shot types", "Camera movements", "Lighting",
                  "Negative prompting", "Sound & audio"):
        assert topic in body


def test_deterministic_stats_exact(app_env):
    data = stats.update_family_stats(
        "flux", "cinematic portrait, golden hour rim light, 85mm",
        {"steps": 30, "sampler": "Euler a"}, "image", 1)
    data = stats.update_family_stats(
        "flux", "golden hour meadow, watercolor style",
        {"steps": 30}, "image", 2)
    data = stats.update_family_stats("flux", None, {}, "video", 3)
    assert data["count"] == 3
    assert data["media"] == {"image": 2, "video": 1}
    assert data["terms"]["golden hour rim light"] == 1
    assert data["params"]["steps"]["30"] == 2
    assert data["params"]["sampler"]["Euler a"] == 1
    # categorization
    assert "golden hour meadow" in data["categories"]["lighting"]
    rendered = stats.render_stats_section(data)
    assert "Posts seen: 3 (2 images, 1 videos)" in rendered
    assert "Common steps: 30" in rendered


def test_model_file_created_on_first_sighting(app_env):
    engine.register_hooks()
    try:
        pid = seed_post(model_family="flux", prompt="dolly zoom on a chapel, slow motion")
        from promptforge.pipeline import hooks
        hooks.run_post_ingested(pid)
        path = files.model_file_path("flux")
        assert path.exists()
        _fm, body = files.read_md(path)
        assert "Posts seen: 1" in body
        # deterministic technique tagging happened (video terms in prompt)
        with db_mod.session_scope() as s:
            post = s.get(Post, pid)
            assert "dolly-zoom" in post.technique_tags
            assert "slow-motion" in post.technique_tags
    finally:
        from promptforge.pipeline import hooks
        hooks.clear()


def test_size_cap_enforced(app_env):
    body = "# X\n\n## Learned notes\n" + "\n".join(
        f"- note number {i} " + "x" * 200 for i in range(200))
    path = files.model_file_path("capped")
    files.write_md(path, {"kind": "model"}, body)
    assert path.stat().st_size <= files.SIZE_CAP + 200  # frontmatter margin
    _fm, out = files.read_md(path)
    assert "note number 199" in out       # newest survived
    assert "note number 0 " not in out    # oldest trimmed


def test_replace_section_and_notes():
    body = "# T\n\n## Profile\nold\n\n## Learned notes\n- first\n"
    body = files.replace_section(body, "Profile", "new profile")
    assert files.get_section(body, "Profile") == "new profile"
    body = files.append_learned_note(body, "second note")
    assert "- second note" in body
    # near-duplicate rejected
    body2 = files.append_learned_note(body, "second note!")
    assert body2.count("second note") == 1
    # new section created when missing
    body3 = files.replace_section(body, "Brand new", "content")
    assert files.get_section(body3, "Brand new") == "content"


def test_techniques_detection():
    tags = techniques.detect_techniques(
        "FPV drone dive through a canyon, whip pan to a timelapse sky, macro shot")
    assert {"fpv", "whip-pan", "timelapse", "macro"} <= set(tags)
    assert techniques.detect_techniques("a quiet portrait") == []
    assert techniques.detect_techniques(None) == []
    assert "panorama" not in " ".join(
        techniques.detect_techniques("panorama view"))  # no substring false hit


def test_analyze_family_with_mock_llm(mock_llm):
    p1 = seed_post(model_family="flux", prompt="neon alley, cinematic")
    p2 = seed_post(model_family="flux", prompt="dolly-in on a shrine",
                   media_type="video")
    mock_llm.responses = [json.dumps({
        "profile": "Natural-language prompts, 30-60 words ideal.",
        "guidance": "- keep camera clauses early\n- avoid negatives",
        "reference_images": "Style refs at low weight work best.",
        "failure_patterns": "- garbles signage text",
        "notes": ["Lead with the subject, end with the grade."],
        "exemplar_ids": [p1, 99999],
        "video_techniques": {str(p2): ["dolly", "not-a-real-slug"]},
    })]
    analyzed = engine.analyze_family("flux")
    assert analyzed == 2
    _fm, body = files.read_md(files.model_file_path("flux"))
    assert "Natural-language prompts" in files.get_section(body, "Profile")
    assert "keep camera clauses early" in body
    assert "Style refs at low weight" in body
    assert "garbles signage" in body
    assert "Lead with the subject" in body
    ex = files.get_section(body, "Exemplars")
    assert str(p1) in ex and "99999" not in ex  # only batch ids accepted
    with db_mod.session_scope() as s:
        assert s.get(Post, p2).technique_tags == ["dolly"]  # slug whitelist
    # usage counter incremented
    with db_mod.session_scope() as s:
        assert llm_client.get_usage(s)["calls"] == 1
    # watermark advanced: second run analyzes nothing
    assert engine.analyze_family("flux") == 0
    assert len(mock_llm.calls) == 1


def test_learning_without_llm_still_progresses(app_env):
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "")
    for i in range(3):
        seed_post(model_family="sdxl",
                  prompt=f"isometric cutaway diorama of a bakery {i}")
    analyzed = engine.analyze_family("sdxl")
    assert analyzed == 0  # no LLM
    # but cluster notes recorded + watermark advanced
    _fm, body = files.read_md(files.model_file_path("sdxl"))
    assert "Recurring pattern" in body
    data = stats.load_stats("sdxl")
    assert data["last_analyzed_post_id"] > 0


def test_budget_respected(app_env):
    class Paid(llm_client.LLMClient):
        name = "paid"
        free = False
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_daily_budget", 2)
        settings_store.put(s, "llm_usage", {"date": llm_client._budget_key_today(),
                                            "calls": 2})
        with pytest.raises(llm_client.BudgetExceeded):
            llm_client.check_budget(s, Paid())
        # free providers ignore the budget
        llm_client.check_budget(s, llm_client.MockLLM())


def test_style_profile_and_refresh(mock_llm, client):
    with db_mod.session_scope() as s:
        c = Collection(name="Moody Portraits", model_family="flux")
        s.add(c)
        s.flush()
        cid = c.id
    pids = [seed_post(model_family="flux",
                      prompt=f"moody chiaroscuro portrait {i}, teal and rust palette, 85mm")
            for i in range(3)]
    with db_mod.session_scope() as s:
        for pid in pids:
            s.add(CollectionPost(collection_id=cid, post_id=pid))
    mock_llm.responses = [json.dumps({
        "style_descriptors": "moody, chiaroscuro, intimate",
        "recurring_subjects": "solitary figures",
        "palette_lighting": "teal, rust, single hard key light",
        "camera_language": "85mm close-ups",
        "adaptation": "On SDXL add 'film grain' for the same texture.",
        "reference_guidance": "Use the darkest exemplar as the style ref.",
    })]
    path = engine.refresh_style_profile(cid)
    assert path is not None
    _fm, body = files.read_md(files.style_file_path(cid))
    assert "moody, chiaroscuro, intimate" in body
    assert "single hard key light" in body
    # API serves it
    r = client.get(f"/api/knowledge/styles/{cid}")
    assert "Moody Portraits" in r.json()["markdown"]
    # deterministic-only refresh works with no LLM configured
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "")
    assert engine.refresh_style_profile(cid, use_llm=False) is not None


def test_generation_event_learns(app_env):
    engine.generation_event(None, "flux", "a foggy pier at dawn", "starred",
                            template_name="Moody")
    _fm, body = files.read_md(files.model_file_path("flux"))
    assert "Generation starred" in body
    assert "Moody" in body


def test_pack_round_trip(mock_llm, tmp_path):
    with db_mod.session_scope() as s:
        c = Collection(name="Pack Test", model_family="flux")
        s.add(c)
        s.flush()
        cid = c.id
    pid = seed_post(model_family="flux", prompt="packable prompt")
    with db_mod.session_scope() as s:
        s.add(CollectionPost(collection_id=cid, post_id=pid))
    files.ensure_model_file("flux")
    engine.refresh_style_profile(cid, use_llm=False)
    fname, data = packs.export_pack(family="flux", collection_id=cid)
    assert fname.endswith(".pfpack") and len(data) > 200

    # wipe local knowledge + collection, then import into a fresh state
    files.model_file_path("flux").unlink()
    files.style_file_path(cid).unlink()
    with db_mod.session_scope() as s:
        s.delete(s.get(Collection, cid))
    result = packs.import_pack(data)
    assert "models/flux.md" in result["imported"]
    assert result["collection_id"] is not None
    assert files.model_file_path("flux").exists()
    assert files.style_file_path(result["collection_id"]).exists()
    # import log written
    log = (files.get_config().knowledge_dir / "import.log").read_text()
    assert "imported=" in log
    # corrupt pack → clean error
    with pytest.raises(packs.PackError):
        packs.import_pack(b"not a zip")


def test_knowledge_api(client, mock_llm):
    seed_post(model_family="flux", prompt="x")
    files.ensure_model_file("flux")
    r = client.get("/api/techniques")
    assert "dolly" in r.json()["techniques"]
    r = client.get("/api/knowledge")
    body = r.json()
    assert any(m["family"] == "flux" for m in body["models"])
    assert body["llm"]["provider"] == "mock"
    assert body["llm"]["budget_applies"] is False
    r = client.get("/api/knowledge/models/flux")
    assert "model knowledge" in r.json()["markdown"]
    assert client.get("/api/knowledge/models/nope").status_code == 404
    r = client.get("/api/knowledge/foundation")
    assert "Prompt anatomy" in r.json()["markdown"]
    # llm test endpoint with mock provider
    r = client.post("/api/knowledge/llm/test")
    assert r.status_code == 200 and r.json()["ok"] is True
