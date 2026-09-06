"""Multimodal evaluation (Phase 2): real vision backend, honest unavailable,
malformed evaluator output, audio/3D paths, confidence + evidence."""
import httpx
import pytest

from promptforge import db as db_mod, settings_store
from promptforge.forge import evaluate as ev
from promptforge.forge import vision
from promptforge.generation import queue as gen_queue
from promptforge.generation import router as gen_router
from promptforge.llm import client as llm_client

from test_film_generation import FakeProvider, _connect, png


@pytest.fixture()
def lab_run(app_env, monkeypatch):
    """An experiment with one variant that has produced a real image."""
    _connect(["fal"])
    fake = FakeProvider()
    monkeypatch.setattr(gen_router, "get_provider", lambda name: fake)
    real_client = httpx.Client

    def factory(**kw):
        kw.setdefault("transport", httpx.MockTransport(
            lambda r: httpx.Response(200, content=png(512, 288))))
        return real_client(**kw)
    monkeypatch.setattr("promptforge.generation.queue.httpx.Client", factory)

    def make(client):
        exp = client.post("/api/forge/experiments", json={
            "name": "eval", "brief": 'a red bicycle, square, with the text "RIDE"'}).json()
        exp = client.post(f"/api/forge/experiments/{exp['id']}/variants",
                          json={"compile_family": "flux"}).json()
        v = exp["variants"][0]
        r = client.post(f"/api/forge/variants/{v['id']}/run", json={}).json()
        gen_queue.process_generation(r["generation_id"])
        return r["run_id"]
    return make


def _use_mock_llm(responses):
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "mock")
    llm_client.mock_instance.responses = list(responses)
    llm_client.mock_instance.vision_calls.clear()


def test_evaluation_is_honest_when_no_evaluator(client, lab_run):
    run_id = lab_run(client)
    out = client.post(f"/api/forge/runs/{run_id}/refine", json={}).json()
    ev_out = out["evaluation"]
    assert ev_out["mode"] == "metadata"
    assert ev_out["multimodal"]["available"] is False
    assert "evaluator" in ev_out["multimodal"]["reason"].lower() or \
           "not configured" in ev_out["multimodal"]["reason"].lower()
    assert ev_out["confidence"] == 0.3            # clearly lower-confidence
    assert any("NOT performed" in u for u in ev_out["unavailable"])
    assert ev_out["overall_score"] is None        # never invents a score
    # the deterministic layer still works
    assert "aspect_ratio" in ev_out["checked"]

    e = client.get("/api/forge/evaluators").json()
    assert e["vision_available"] is False and e["reason"]


def test_real_vision_evaluation_scores_with_evidence(client, lab_run):
    run_id = lab_run(client)
    _use_mock_llm(['{"dimensions": {"prompt_adherence": 82, "composition": 70, '
                   '"typography": 40}, "issues": ["the word RIDE is misspelled"], '
                   '"recommendations": ["put the text in quotes"], '
                   '"evidence": ["a red bicycle centred on a plain background"], '
                   '"confidence": 0.8}'])
    out = client.post(f"/api/forge/runs/{run_id}/refine", json={}).json()
    ev_out = out["evaluation"]
    assert ev_out["mode"] == "multimodal"
    mm = ev_out["multimodal"]
    assert mm["available"] and mm["backend"] == "mock"
    assert mm["frames_examined"] == 1
    assert ev_out["dimensions"]["prompt_adherence"] == 82
    assert ev_out["overall_score"] == round((82 + 70 + 40) / 3)
    assert ev_out["confidence"] == 0.8
    assert ev_out["evidence"] and ev_out["recommendations"]
    # the evaluator's issue becomes a finding and reaches the refinement notes
    assert any(f["kind"] == "content" for f in ev_out["findings"])
    assert any("misspelled" in c for c in out["proposal"]["changes"])
    # it genuinely looked at pixels
    assert llm_client.mock_instance.vision_calls[0][2] == 1


def test_malformed_evaluator_output_degrades_honestly(client, lab_run):
    run_id = lab_run(client)
    _use_mock_llm(["I think it looks quite nice, honestly."])
    out = client.post(f"/api/forge/runs/{run_id}/refine", json={}).json()
    mm = out["evaluation"]["multimodal"]
    assert mm["available"] is False and "usable JSON" in mm["reason"]
    assert out["evaluation"]["overall_score"] is None


def test_dimensions_are_clamped_and_filtered(client, lab_run):
    run_id = lab_run(client)
    _use_mock_llm(['{"dimensions": {"prompt_adherence": 150, "composition": -20, '
                   '"made_up_axis": 99}, "confidence": 5}'])
    out = client.post(f"/api/forge/runs/{run_id}/refine", json={}).json()
    dims = out["evaluation"]["dimensions"]
    assert dims == {"prompt_adherence": 100, "composition": 0}
    assert out["evaluation"]["confidence"] == 1.0


def test_3d_structural_evaluation_is_local_and_labelled(app_env, tmp_path):
    good = tmp_path / "m.glb"
    good.write_bytes(b"glTF" + b"\0" * 4096)
    r = ev._evaluate_3d(good)
    assert r["available"] and r["mode"] == "structural" and r["backend"] == "local"
    assert r["dimensions"]["format_validity"] == 100 and not r["issues"]
    bad = tmp_path / "b.glb"
    bad.write_bytes(b"nope")
    r2 = ev._evaluate_3d(bad)
    assert r2["dimensions"]["format_validity"] == 0
    assert any("glTF magic" in i for i in r2["issues"])
    assert r2["confidence"] < 1.0      # structural checks never claim certainty


def test_vision_backends_reported_from_real_configuration(app_env):
    with db_mod.session_scope() as s:
        assert vision.available_backends(s) == []
        settings_store.put(s, "muapi_api_key", "k")
        kinds = {b["kind"] for b in vision.available_backends(s)}
        assert {"vision", "audio", "transcription"} <= kinds
        with pytest.raises(vision.NoEvaluator):
            vision.look(s, "sys", "user", [])          # nothing to look at


def test_video_frame_sampling_uses_ffmpeg(app_env, tmp_path):
    from test_film_generation import mp4
    path = tmp_path / "v.mp4"
    path.write_bytes(mp4(1.5))
    frames = vision.video_frames(path, count=3)
    assert len(frames) == 3 and all(f[:4] == b"\x89PNG" for f in frames)
