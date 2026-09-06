"""Test Lab + evaluation/refinement (spec §5–§6)."""
import httpx
import pytest

from promptforge.generation import queue as gen_queue
from promptforge.generation import router as gen_router

from test_film_generation import FakeProvider, _connect, png


@pytest.fixture()
def fake_provider(app_env, monkeypatch):
    _connect(["fal"])
    fake = FakeProvider()
    monkeypatch.setattr(gen_router, "get_provider", lambda name: fake)
    real_client = httpx.Client

    def client_factory(**kw):
        # a 16:9-ish output regardless of the request → aspect finding below
        kw["transport"] = httpx.MockTransport(
            lambda req: httpx.Response(200, content=png(512, 288)))
        return real_client(**kw)
    monkeypatch.setattr("promptforge.generation.queue.httpx.Client", client_factory)
    return fake


def test_lab_full_loop(client, fake_provider):
    # experiment from a brief; compile two model-specific variants
    exp = client.post("/api/forge/experiments", json={
        "name": "Violinist noir",
        "brief": "A noir portrait of a violinist under a streetlight, no rain, square"}).json()
    assert exp["intent"]["aspect_ratio"] == "1:1"
    for fam in ("sdxl", "flux"):
        exp = client.post(f"/api/forge/experiments/{exp['id']}/variants",
                          json={"compile_family": fam}).json()
    v_sdxl, v_flux = exp["variants"]
    assert v_sdxl["family"] == "sdxl" and v_flux["family"] == "flux"
    assert v_sdxl["prompt"] != v_flux["prompt"]

    # A/B run both through the queue
    runs = []
    for v in (v_sdxl, v_flux):
        r = client.post(f"/api/forge/variants/{v['id']}/run", json={}).json()
        gen_queue.process_generation(r["generation_id"])
        runs.append(r)
    view = client.get(f"/api/forge/experiments/{exp['id']}").json()
    got = [rr for v in view["variants"] for rr in v["runs"]]
    assert all(r["status"] == "succeeded" for r in got)
    assert all(r["output_post_id"] for r in got)
    assert got[0]["latency_s"] is not None

    # score + keep a winner
    client.post(f"/api/forge/runs/{runs[0]['run_id']}/score",
                json={"score": 4, "notes": "keeps the mood", "winner": True})
    view = client.get(f"/api/forge/experiments/{exp['id']}").json()
    assert view["variants"][0]["winner"] is True
    assert view["variants"][0]["runs"][0]["user_score"] == 4

    # evaluate + refine: 1:1 requested, 512×288 delivered → aspect finding;
    # the refinement lands as a NEW version with a diff, nothing overwritten
    out = client.post(f"/api/forge/runs/{runs[1]['run_id']}/refine", json={}).json()
    kinds = [f["kind"] for f in out["evaluation"]["findings"]]
    assert "aspect_ratio" in kinds
    assert out["evaluation"]["unavailable"], "vision-level checks reported, not guessed"
    view = client.get(f"/api/forge/experiments/{exp['id']}").json()
    versions = [v["version"] for v in view["variants"]]
    assert versions == [1, 2] or len(versions) == 3   # refined variant only if changed
    flux_after = [v for v in view["variants"] if v["id"] == v_flux["id"]][0]
    assert flux_after["prompt"] == v_flux["prompt"], "original never overwritten"


def test_fork_and_rollback_lineage(client, fake_provider):
    exp = client.post("/api/forge/experiments",
                      json={"name": "cabin", "brief": "a cozy cabin"}).json()
    exp = client.post(f"/api/forge/experiments/{exp['id']}/variants",
                      json={"prompt": "a cozy cabin in snow", "family": "flux"}).json()
    v1 = exp["variants"][0]
    exp = client.post(f"/api/forge/variants/{v1['id']}/fork",
                      json={"changes": {"prompt": "a cozy cabin in snow at night"}}).json()
    v2 = exp["variants"][1]
    assert v2["parent_id"] == v1["id"] and v2["origin"] == "fork"
    assert v2["version"] == 2
    # rollback = run the older version again — v1 is intact
    assert exp["variants"][0]["prompt"] == "a cozy cabin in snow"


def test_refinement_moves_avoid_into_negative(client, fake_provider):
    exp = client.post("/api/forge/experiments", json={
        "name": "beach", "brief": "sunny beach, photorealistic, no people"}).json()
    exp = client.post(f"/api/forge/experiments/{exp['id']}/variants",
                      json={"prompt": "sunny beach", "negative": "",
                            "family": "sdxl",
                            "package": {"intent": exp["intent"]}}).json()
    v = exp["variants"][0]
    r = client.post(f"/api/forge/variants/{v['id']}/run", json={}).json()
    gen_queue.process_generation(r["generation_id"])
    out = client.post(f"/api/forge/runs/{r['run_id']}/refine", json={}).json()
    msgs = " ".join(f["message"] for f in out["evaluation"]["findings"])
    assert "photorealistic" in msgs and "people" in msgs
    assert any(c["op"] == "add" for c in out["proposal"]["diff"])
    assert "people" in (out["proposal"]["negative"] or "")
    assert out["new_variant_id"]
