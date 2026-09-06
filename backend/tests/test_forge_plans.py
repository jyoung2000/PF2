"""Creative Plans (spec §8): presets, editing, locks, dependency-gated runs,
reference wiring, rerun-failed-only, fork."""
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
        kw["transport"] = httpx.MockTransport(
            lambda req: httpx.Response(200, content=png(512, 288)))
        return real_client(**kw)
    monkeypatch.setattr("promptforge.generation.queue.httpx.Client", client_factory)
    return fake


def test_launch_campaign_plan_editable_and_dependency_gated(client, fake_provider):
    p = client.post("/api/forge/plans", json={
        "brief": "Launch campaign for my new music player app, warm retro aesthetic"}).json()
    assert p["meta"]["preset"] == "launch_campaign"
    purposes = [a["purpose"] for a in p["assets"]]
    assert "Hero image" in purposes and "Short vertical video" in purposes
    hero = p["assets"][0]
    social = p["assets"][1]
    assert social["depends_on"] == [hero["id"]]
    assert social["params"]["aspect_ratio"] == "1:1"
    assert p["estimated_total"] >= 0

    # the plan is editable: change one prompt + model, lock an asset
    p = client.patch(f"/api/forge/plans/{p['id']}/assets/{social['id']}",
                     json={"prompt": "square social crop, bold type",
                           "family": "sdxl", "locked": True}).json()
    edited = [a for a in p["assets"] if a["id"] == social["id"]][0]
    assert edited["family"] == "sdxl" and edited["locked"]

    # dependent asset refuses to run before the hero exists
    r = client.post(f"/api/forge/plans/{p['id']}/assets/{p['assets'][2]['id']}/run", json={})
    assert r.status_code == 409 and "waiting on" in r.json()["detail"]

    # run the plan: hero queues; dependents report blocked; locked skipped
    out = client.post(f"/api/forge/plans/{p['id']}/run", json={}).json()
    assert [q["purpose"] for q in out["queued"]] == ["Hero image"]
    assert any(b["reason"].startswith("waiting on") for b in out["blocked"])
    assert any(sk["locked"] for sk in out["skipped"])
    gen_queue.process_generation(out["queued"][0]["job_id"])

    # second pass: dependents run now, wired to the hero output as reference
    out = client.post(f"/api/forge/plans/{p['id']}/run", json={}).json()
    assert len(out["queued"]) >= 3
    for q in out["queued"]:
        gen_queue.process_generation(q["job_id"])
    sub = fake_provider.submits[-1]
    assert any("_inputs" in s["params"] for s in fake_provider.submits[1:]), \
        "hero output fed into dependents as an input"
    view = client.get(f"/api/forge/plans/{p['id']}").json()
    done = [a for a in view["assets"] if a["status"] == "succeeded"]
    assert len(done) >= 4 and all(a["output_post_id"] for a in done)


def test_rerun_failed_only_and_fork(client, fake_provider):
    p = client.post("/api/forge/plans", json={"brief": "social pack for a bakery"}).json()
    out = client.post(f"/api/forge/plans/{p['id']}/run", json={}).json()
    fake_provider.fail_next = True
    gen_queue.process_generation(out["queued"][0]["job_id"])   # base asset fails
    view = client.get(f"/api/forge/plans/{p['id']}").json()
    assert view["assets"][0]["status"] == "failed" and view["assets"][0]["error"]

    # only_failed reruns just the failed base
    out = client.post(f"/api/forge/plans/{p['id']}/run", json={"only_failed": True}).json()
    assert [q["id"] for q in out["queued"]] == [view["assets"][0]["id"]]
    gen_queue.process_generation(out["queued"][0]["job_id"])

    # fork duplicates assets and remaps sibling links to the clone
    clone = client.post(f"/api/forge/plans/{p['id']}/fork").json()
    assert clone["id"] != p["id"] and len(clone["assets"]) == len(view["assets"])
    ids = {a["id"] for a in clone["assets"]}
    for a in clone["assets"]:
        assert all(d in ids for d in a["depends_on"])
        assert a["status"] == "planned"                        # fresh branch


def test_asset_kind_is_authoritative_over_brief_wording(client, app_env):
    """'music player' must not re-route image assets to audio (spec §8)."""
    p = client.post("/api/forge/plans", json={
        "brief": "Launch campaign for my new music player app, warm retro aesthetic"}).json()
    for a in p["assets"]:
        assert a["family"], f"{a['purpose']} compiled with no model"
        assert a["prompt"], f"{a['purpose']} has no prompt"
    from promptforge.forge import intent
    i = intent.extract("promo for my music player app")
    assert i["modality"] == "image"          # product, not an audio request
    assert intent.extract("a 30 second music jingle")["modality"] == "audio"
