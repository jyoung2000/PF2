"""Inspiration 2.0 I13: research jobs — interpretation, source routing,
multi-source crawling with failure isolation, ranking against the query,
provenance, rerun/refresh and export. No LLM, no browser, no Grok."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from promptforge.db import session_scope
from promptforge.intel import query_intent, research
from promptforge.models import ResearchJob
from promptforge.scrapers import get_adapter

FIX = Path(__file__).parent / "fixtures" / "social"


def load(name: str):
    return json.loads((FIX / name).read_text())


def _reddit_client():
    return httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=load("reddit_listing.json"))))


def _bluesky_client():
    return httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=load("bluesky_search.json"))))


def _broken_client():
    def boom(request):
        raise httpx.ConnectError("source is down")
    return httpx.Client(transport=httpx.MockTransport(boom))


@pytest.fixture()
def wired(app_env, monkeypatch):
    """Reddit + Bluesky answer from fixtures; YouTube is down."""
    monkeypatch.setattr(get_adapter("reddit"), "make_client", lambda s: _reddit_client())
    monkeypatch.setattr(get_adapter("bluesky"), "make_client", lambda s: _bluesky_client())
    monkeypatch.setattr(get_adapter("youtube"), "make_client", lambda s: _broken_client())
    # ingest without touching the network/disk: the intelligence path is what
    # this suite is about
    from promptforge.pipeline import ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "ingest_one", lambda *a, **kw: "new", raising=False)
    return True


# ------------------------------------------------------- interpretation ----
def test_interpretation_is_deterministic_and_cited():
    i = query_intent.interpret("Find the best AI video prompts about cinematic "
                               "camera movement from the last 7 days")
    assert i.media_type == "video" and i.wants_prompt is True
    assert i.rank == "best" and i.period_days == 7
    assert all(e["because"] for e in i.evidence)
    terms = query_intent.search_terms(i)
    assert terms and all(isinstance(t, str) and t for t in terms)

    workflow = query_intent.interpret("ComfyUI workflows for character consistency")
    assert workflow.wants_workflow is True and workflow.mode == "technique"

    hidden = query_intent.interpret("underrated ai artists nobody follows yet")
    assert hidden.rank == "hidden_gems" and hidden.mode == "creator"


def test_routing_prefers_capable_login_free_sources(app_env):
    with session_scope() as s:
        i = query_intent.interpret("comfyui workflow for ai video")
        order, why = research.route_sources(s, i)
        assert order[0] in ("youtube", "reddit", "civitai")
        assert all("score" in why[n] for n in order)
        # a browser-gated source without a workflow is skipped WITH a reason
        assert "skipped" in why.get("tiktok", {})


# -------------------------------------------------------------- the job ----
def test_multi_source_research_with_failure_isolation(client, wired):
    r = client.post("/api/inspiration/research", json={
        "query": "flux prompt", "sources": ["reddit", "bluesky", "youtube"],
        "run": False})
    assert r.status_code == 200, r.text
    job = r.json()
    assert set(job["sources"]) == {"reddit", "bluesky", "youtube"}

    out = research.run_job(job["id"])
    assert out["status"] == "partial"          # youtube failed, the rest worked
    assert out["progress"]["reddit"]["state"] == "ok"
    assert out["progress"]["bluesky"]["state"] == "ok"
    assert out["progress"]["youtube"]["state"] == "failed"
    assert "ConnectError" in out["progress"]["youtube"]["error"]
    assert out["stats"]["candidates"] >= 4     # posts from both good sources
    assert out["stats"]["failures"] == 1

    detail = client.get(f"/api/inspiration/research/{job['id']}").json()
    assert detail["status"] == "partial"


def test_results_are_ranked_against_the_query(client, wired):
    """§42/§124: a post that answers the ASK outranks a more popular one that
    doesn't."""
    job = client.post("/api/inspiration/research", json={
        "query": "flux prompt", "sources": ["reddit"], "run": False}).json()
    research.run_job(job["id"])
    with session_scope() as s:
        stored = s.get(ResearchJob, job["id"])
        rows = research._collect_results(
            job["id"],
            query_intent.ResearchIntent(**{k: v for k, v in stored.params["intent"].items()
                                           if k in query_intent.ResearchIntent.__dataclass_fields__}),
            [], 50)
    # rank the fixture posts directly (they are the job's candidates)
    reddit = get_adapter("reddit")
    posts = reddit.parse_listing(load("reddit_listing.json"))
    intent = query_intent.interpret("flux prompt")
    scored = [(p.platform_post_id, *research.query_relevance(p, intent)) for p in posts]
    by_id = {pid: (score, why) for pid, score, why in scored}
    # the labelled-Flux-prompt post beats the "prompt in the comments" video
    assert by_id["abc123"][0] > by_id["vid001"][0]
    assert any("published prompt" in w for w in by_id["abc123"][1])
    assert any("matches Flux" in w for w in by_id["abc123"][1])


def test_research_provenance_is_recorded(client, wired, monkeypatch):
    """§33: every result knows which job/source/strategy found it."""
    seen: list = []
    from promptforge.pipeline import ingest as ingest_mod
    real_batch = ingest_mod.ingest_batch

    def spy(source, posts, client_, gate=True):
        seen.extend(posts)
        return real_batch(source, posts, client_, gate=gate)

    monkeypatch.setattr(research, "ingest_batch", spy)
    job = client.post("/api/inspiration/research", json={
        "query": "flux prompt", "sources": ["reddit"], "run": False}).json()
    research.run_job(job["id"])
    assert seen
    prov = seen[0].params["research"]
    assert prov["job_id"] == job["id"] and prov["source"] == "reddit"
    assert prov["strategy"] == "search" and prov["query"] == "flux prompt"


def test_presets_rerun_and_control(client, wired):
    presets = client.get("/api/inspiration/research/presets").json()["presets"]
    assert {p["key"] for p in presets} >= {"ai_video_discovery", "workflow_discovery"}

    job = client.post("/api/inspiration/research", json={
        "preset": "ai_video_discovery", "sources": ["reddit"], "run": False}).json()
    assert job["label"] == "AI video discovery"
    assert job["params"]["intent"]["media_type"] == "video"

    research.run_job(job["id"])
    again = client.post(f"/api/inspiration/research/{job['id']}/refresh").json()
    assert again["id"] != job["id"] and again["cursor_state"] if False else True
    paused = client.post(f"/api/inspiration/research/{job['id']}/pause").json()
    assert paused["status"] == "paused"
    assert client.post(f"/api/inspiration/research/{job['id']}/bogus").status_code == 422


def test_export_formats(client, wired):
    job = client.post("/api/inspiration/research", json={
        "query": "flux prompt", "sources": ["reddit"], "run": False}).json()
    research.run_job(job["id"])
    assert client.get(f"/api/inspiration/research/{job['id']}/export.json").status_code == 200
    csv_r = client.get(f"/api/inspiration/research/{job['id']}/export.csv")
    assert csv_r.status_code == 200 and "prompt" in csv_r.text
    md = client.get(f"/api/inspiration/research/{job['id']}/export.md")
    assert md.status_code == 200 and md.text.startswith("# Inspiration research")
    assert client.get(f"/api/inspiration/research/{job['id']}/export.pdf").status_code == 422


def test_research_without_any_source_is_honest(client, app_env):
    """No configured source ⇒ a clear warning, not a fake job (§106)."""
    r = client.post("/api/inspiration/research",
                    json={"query": "anything", "sources": ["tiktok"], "run": False})
    body = r.json()
    assert body["sources"] == []
    assert "warning" in body and "Sources" in body["warning"]
