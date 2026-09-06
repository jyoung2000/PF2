"""Workflow engine (spec §9, §17): validation, ticked execution through the
queue, approval pause, honest per-node availability, local clipping."""
import httpx
import pytest

from promptforge import db as db_mod
from promptforge.forge import workflows as wf_mod
from promptforge.generation import queue as gen_queue
from promptforge.generation import router as gen_router

from test_film_generation import FakeProvider, _connect, mp4_cuts, png


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


def _pump(client, run_id):
    """Tick, process any queued generations, tick again — like the scheduler
    plus the worker would."""
    from sqlalchemy import select

    from promptforge.models import Generation
    for _ in range(6):
        view = client.get(f"/api/forge/workflow-runs/{run_id}?tick=true").json()
        with db_mod.session_scope() as s:
            pending = [i for (i,) in s.execute(select(Generation.id).where(
                Generation.status == "queued"))]
        for gid in pending:
            gen_queue.process_generation(gid)
        if view["status"] in ("succeeded", "failed", "waiting_approval"):
            return view
    return view


def test_validation_rejects_cycles_unknown_types_and_bad_edges(client):
    bad = {"nodes": [{"id": "a", "type": "prompt", "config": {"text": "x"}},
                     {"id": "b", "type": "warp", "config": {}}],
           "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"},
                     {"from": "a", "to": "ghost"}]}
    r = client.post("/api/forge/workflows", json={"name": "bad", "graph": bad})
    assert r.status_code == 422
    errs = " ".join(r.json()["detail"]["errors"])
    assert "unknown node type" in errs and "cycle" in errs and "missing node" in errs


def test_template_runs_end_to_end_and_serializes(client, fake_provider):
    w = client.post("/api/forge/workflows/from-template/idea_to_image").json()
    avail = {a["id"]: a for a in w["availability"]}
    assert avail["gen"]["supported"]
    run = client.post(f"/api/forge/workflows/{w['id']}/run",
                      json={"inputs": {"idea": "a lighthouse in fog, cinematic"}}).json()
    view = _pump(client, run["id"])
    assert view["status"] == "succeeded"
    ns = view["node_states"]
    assert ns["compile"]["output"]["package"]["family"]
    assert ns["gen"]["output"]["post_id"]
    assert ns["export"]["output"]["exported"]
    # the workflow round-trips as JSON (serialized graph is the storage format)
    stored = client.get(f"/api/forge/workflows/{w['id']}").json()
    assert stored["graph"]["nodes"] and stored["validation"]["ok"]


def test_approval_parks_the_run_until_a_human_approves(client, fake_provider):
    w = client.post("/api/forge/workflows/from-template/image_to_video").json()
    run = client.post(f"/api/forge/workflows/{w['id']}/run",
                      json={"inputs": {"idea": "a paper boat on a puddle"}}).json()
    view = _pump(client, run["id"])
    assert view["status"] == "waiting_approval"
    assert view["node_states"]["ok"]["status"] == "waiting_approval"
    assert "motion" not in view["node_states"] or \
        view["node_states"]["motion"].get("status") is None
    client.post(f"/api/forge/workflow-runs/{run['id']}/approve", json={"node_id": "ok"})
    view = _pump(client, run["id"])
    assert view["status"] == "succeeded", view["node_states"]
    assert view["node_states"]["motion"]["output"]["post_id"]
    submitted = fake_provider.submits[-1]
    assert submitted["params"].get("_inputs", {}).get("image"), \
        "the approved keyframe fed the video node"


def test_shorts_pipeline_honest_transcription_and_local_clipping(client, app_env, tmp_path):
    w = client.post("/api/forge/workflows/from-template/shorts_pipeline").json()
    avail = {a["id"]: a for a in w["availability"]}
    assert avail["stt"]["supported"] is False           # honest before any adapter declares it
    assert avail["clips"]["supported"] is True          # ffmpeg is local
    src = tmp_path / "long.mp4"
    src.write_bytes(mp4_cuts("wf"))
    run = client.post(f"/api/forge/workflows/{w['id']}/run",
                      json={"inputs": {"video": str(src)}}).json()
    view = _pump(client, run["id"])
    # transcription fails honestly; the clip branch still cut real clips
    assert view["status"] == "failed"
    assert "text-to-speech" not in (view["node_states"]["stt"]["error"] or "")
    assert "transcri" in view["node_states"]["stt"]["error"].lower() or \
           "speech" in view["node_states"]["stt"]["error"].lower()
    clips = view["node_states"]["clips"]["output"]["clips"]
    assert clips and all(c.endswith(".mp4") for c in clips)
    from pathlib import Path
    assert all(Path(c).exists() for c in clips)
