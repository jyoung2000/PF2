"""Tool layer (spec §7, §11, §12.5): typed validation, capability gating,
job status, opt-in one-step fallback."""
import httpx
import pytest

from promptforge import db as db_mod, settings_store
from promptforge.forge import tools
from promptforge.generation import queue as gen_queue
from promptforge.generation import router as gen_router
from promptforge.generation.base import ProviderError

from test_film_generation import FakeProvider, _connect, png


@pytest.fixture()
def fake_provider(app_env, monkeypatch):
    _connect(["fal", "wavespeed"])
    fake = FakeProvider()
    monkeypatch.setattr(gen_router, "get_provider", lambda name: fake)
    real_client = httpx.Client                      # the patch below is global to httpx

    def client_factory(**kw):
        kw["transport"] = httpx.MockTransport(
            lambda req: httpx.Response(200, content=png(512, 288)))
        return real_client(**kw)
    monkeypatch.setattr("promptforge.generation.queue.httpx.Client", client_factory)
    return fake


def test_tools_report_honest_availability(client):
    r = client.get("/api/forge/tools").json()["tools"]
    by = {t["name"]: t for t in r}
    assert by["generate_image"]["supported"] is False           # nothing connected
    assert "connect" in by["generate_image"]["reason"].lower()
    assert by["generate_speech"]["supported"] is False
    assert "text-to-speech" in by["generate_speech"]["reason"]
    assert "MuAPI" in by["generate_speech"]["reason"]      # says what to connect
    assert by["edit_image"]["input_schema"]["required"] == {"prompt": "str", "image": "str"}
    _connect(["fal"])
    r = client.get("/api/forge/tools").json()["tools"]
    by = {t["name"]: t for t in r}
    assert by["generate_image"]["supported"] and "flux" in by["generate_image"]["families"]
    assert by["image_to_video"]["supported"]
    assert by["generate_3d"]["supported"] is False               # still honest


def test_invoke_validates_args_and_capability(client):
    r = client.post("/api/forge/tools/generate_image", json={})
    assert r.status_code == 409 and "'prompt' is required" in r.json()["detail"]["message"]
    r = client.post("/api/forge/tools/nope", json={"prompt": "x"})
    assert r.status_code == 409 and "unknown tool" in r.json()["detail"]["message"]
    r = client.post("/api/forge/tools/generate_speech", json={"prompt": "hello"})
    assert r.status_code == 409
    d = r.json()["detail"]
    # the error names what to connect, matching the availability report
    assert "text-to-speech" in d["message"] and "MuAPI" in d["message"]
    assert d["next_action"]


def test_invoke_runs_through_queue_with_job_status(client, fake_provider):
    r = client.post("/api/forge/tools/generate_image",
                    json={"prompt": "a lighthouse at dusk", "family": "flux"}).json()
    assert r["status"] == "queued" and r["family"] == "flux" and r["estimate"] is not None
    gen_queue.process_generation(r["job_id"])
    j = client.get(f"/api/forge/jobs/{r['job_id']}").json()
    assert j["status"] == "succeeded" and j["output_post_id"]
    assert j["tool"] == "generate_image"
    assert fake_provider.submits[0]["kind"] == "image"


def test_edit_image_maps_inputs(client, fake_provider, tmp_path):
    src = tmp_path / "in.png"
    src.write_bytes(png(64, 64))
    r = client.post("/api/forge/tools/edit_image",
                    json={"prompt": "make it night", "image": str(src),
                          "family": "flux", "strength": 0.4}).json()
    gen_queue.process_generation(r["job_id"])
    sub = fake_provider.submits[-1]
    assert sub["params"]["_inputs"]["image"] == str(src)
    assert sub["params"]["_inputs"]["strength"] == 0.4
    assert sub["params"]["_input_map"]                     # provider field names attached
    assert sub["model_id"] != ""                           # the mode's model id, not blank


def test_failed_job_reports_structured_error_no_silent_fallback(client, fake_provider):
    fake_provider.fail_next = True
    r = client.post("/api/forge/tools/generate_image",
                    json={"prompt": "x", "family": "flux", "provider": "fal"}).json()
    assert r["provider"] == "fal"                       # explicit choice honored (§12.1)
    gen_queue.process_generation(r["job_id"])
    j = client.get(f"/api/forge/jobs/{r['job_id']}").json()
    assert j["status"] == "failed"
    err = j["error"]
    assert err["provider"] == "fal" and err["recoverable"] and err["fallback_options"]
    # fallback did NOT happen — it is opt-in
    with db_mod.session_scope() as s:
        from promptforge.models import Generation
        assert s.query(Generation).count() == 1


def test_opt_in_fallback_creates_visible_linked_job(client, fake_provider):
    fake_provider.fail_next = True
    r = client.post("/api/forge/tools/generate_image",
                    json={"prompt": "x", "family": "flux", "allow_fallback": True}).json()
    gen_queue.process_generation(r["job_id"])
    with db_mod.session_scope() as s:
        from promptforge.models import Generation
        rows = s.query(Generation).order_by(Generation.id).all()
        assert len(rows) == 2
        first, second = rows
        assert first.status == "failed" and first.error       # original stays visible
        assert second.params["_fallback_of"] == first.id
        assert second.provider != first.provider              # a different offer
        second_id = second.id
    gen_queue.process_generation(second_id)
    j = client.get(f"/api/forge/jobs/{second_id}").json()
    assert j["status"] == "succeeded" and j["fallback_of"] == r["job_id"]
    # one step only: a failing fallback never chains a third job
    with db_mod.session_scope() as s:
        assert tools.attempt_fallback(second_id) is None


def test_usage_report_tracks_costs_failures_and_fallbacks(client, fake_provider):
    fake_provider.fail_next = True
    r = client.post("/api/forge/tools/generate_image",
                    json={"prompt": "x", "family": "flux", "allow_fallback": True}).json()
    gen_queue.process_generation(r["job_id"])          # fails → fallback queued
    with db_mod.session_scope() as s:
        from promptforge.models import Generation
        second = s.query(Generation).order_by(Generation.id.desc()).first().id
    gen_queue.process_generation(second)
    u = client.get("/api/forge/usage").json()
    assert u["totals"]["generations"] == 2
    assert u["totals"]["failed"] == 1 and u["totals"]["succeeded"] == 1
    assert u["totals"]["fallbacks"] == 1
    assert any(m["failed"] == 1 for m in u["models"])
    assert u["recent"][0]["fallback_of"] == r["job_id"]
