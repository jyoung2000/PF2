"""Phase I4: adapter capabilities, X observed envelope + TweetDetail
comments/thread, Civitai related/author lookups, the enrichment stage
(author-reply prompts become extracted assertions), source efficiency
metrics, sanitized snapshots."""
import gzip
import json
from pathlib import Path

import httpx
from sqlalchemy import select

from promptforge import db as db_mod, settings_store
from promptforge.intel import enrichment
from promptforge.intel import prompt_parser as pp, queue, snapshots, sources
from promptforge.models import Creator, PipelineJob, Post, ScraperState
from promptforge.pipeline.ingest import IngestStats
from promptforge.scrapers import all_adapters, civitai, get_adapter, x as xmod
from tests.conftest import seed_post

FIX = Path(__file__).parent / "fixtures"
DETAIL = json.loads((FIX / "x_tweet_detail.json").read_text())


def detail_responses():
    return [{"url": "https://x.com/i/api/graphql/abc/TweetDetail?x=1", "json": DETAIL}]


# ---------------------------------------------------------- capabilities ---
def test_every_adapter_declares_honest_capabilities():
    caps = {name: set(a.capabilities) for name, a in all_adapters().items()}
    assert caps["civitai"] >= {"api", "author", "related", "metadata"} and "comments" not in caps["civitai"]
    assert caps["x"] >= {"browser_session", "comments", "thread", "author"} and "api" not in caps["x"]
    assert caps["lexica"] == {"api", "search"}
    for name in ("midjourney", "tensorart", "seaart", "pixai"):
        assert "browser_session" in caps[name] and "comments" not in caps[name]
    assert get_adapter("x").has_capability("comments") and not get_adapter("lexica").has_capability("detail")
    assert not hasattr(get_adapter("lexica"), "fetch_comments")


# ------------------------------------------------------------- X parsing ---
def _main_result():
    entries = DETAIL["data"]["threaded_conversation_with_injections_v2"]["instructions"][0]["entries"]
    return entries[0]["content"]["itemContent"]["tweet_results"]["result"]


def test_x_observed_envelope_is_complete():
    (sp,) = xmod.parse_tweet(_main_result())
    o = sp.observed
    assert o["author"]["handle"] == "auroraforge" and o["author"]["followers"] == 12000
    assert o["author"]["verified"] is True and o["author"]["profile_url"] == "https://x.com/auroraforge"
    assert o["engagement"] == {"likes": 900, "reposts": 120, "replies": 4, "quotes": 3,
                               "bookmarks": 77, "views": 45000}
    assert o["text"]["links"] == ["https://example.com/making-of"]
    assert o["text"]["hashtags"] == ["aivideo"] and "Prompt in the replies" in o["text"]["body"]
    assert o["media"]["alt_text"] == "a glass lighthouse at dawn"
    assert o["media"]["width"] == 1280 and len(o["media"]["variants"]) == 2
    assert sp.media_url == "https://video.twimg.com/high.mp4"      # top bitrate
    assert o["relations"]["conversation"] == "1001" and o["relations"]["reply_to"] is None
    assert o["identity"]["tweet_id"] == "1001"


def test_x_parse_detail_splits_thread_and_comments():
    d = xmod.parse_detail(detail_responses(), "1001")
    assert d["main"]["id"] == "1001" and d["main"]["author"] == "@auroraforge"
    assert [t["id"] for t in d["thread"]] == ["2001"]                 # author's own reply
    assert [c["id"] for c in d["comments"]] == ["2002", "2003", "2004"]
    assert d["comments"][0]["likes"] == 3 and d["comments"][2]["reply_to"] == "1001"
    assert xmod.parse_detail(detail_responses(), "1001-1")["main"]["id"] == "1001"  # media suffix ok
    assert xmod.parse_detail([], "1001") == {"main": None, "thread": [], "comments": []}


def test_comment_prioritisation_marks_technical_and_author():
    d = xmod.parse_detail(detail_responses(), "1001")
    ranked = enrichment.prioritize_comments(d["comments"] + d["thread"], "@auroraforge")
    assert ranked[0]["id"] == "2001" and ranked[0]["by_author"] and ranked[0]["technical"]
    assert [c["id"] for c in ranked[1:3]] == ["2004", "2002"]          # technical, by likes
    assert ranked[-1]["id"] == "2003" and not ranked[-1]["technical"]
    assert enrichment.technical("what ControlNet weight?") and not enrichment.technical("wow!")


# ------------------------------------------------------------ enrichment ---
def test_enrich_x_post_pulls_prompt_from_authors_reply(app_env, monkeypatch):
    app_env.sessions_dir.mkdir(parents=True, exist_ok=True)
    (app_env.sessions_dir / "x.json").write_text('{"cookies": []}')
    monkeypatch.setattr(xmod.XAdapter, "_run_crawl", lambda self, storage_state=None: (detail_responses(), 200))
    with db_mod.session_scope() as s:
        settings_store.put(s, "intel_analysis_threshold", 10)
        settings_store.put(s, "intel_snapshots", True)
    pid = seed_post(platform="x", platform_post_id="1001", prompt=None, model_name=None,
                    model_family=None, author="@auroraforge", media_type="video",
                    observed={"author": {"handle": "auroraforge"}}, assertions={})
    assert enrichment.enrich_post(pid, {}) == "complete"
    with db_mod.session_scope() as s:
        p = s.get(Post, pid)
        assert p.pipeline_state == "enriched"
        assert p.enrichment["comment_count"] == 3 and [t["id"] for t in p.enrichment["thread"]] == ["2001"]
        assert p.prompt.startswith("cinematic slow orbit of a glass lighthouse")
        assert p.assertions["prompt"]["source"] == "extracted" and "author's reply" in p.assertions["prompt"]["evidence"]
        # I11: the column carries the LADDER value; the coarse rank stays derivable
        assert p.prompt_source == "explicit_thread"
        assert pp.coarse_source(p.prompt_source) == "extracted"
        assert [f["ref"] for f in p.params["prompt_fragments"] if f["author_is_creator"]] == ["2001"]
        assert p.model_name == "Kling" and p.model_family == "kling" and p.model_source == "explicit"
        assert p.inspiration_score is not None
        # a "Runway" guess from a random commenter never becomes a model assertion
        assert p.assertions["model"]["value"] == "Kling"
        job = s.execute(select(PipelineJob).where(PipelineJob.post_id == pid,
                                                  PipelineJob.stage == "analysis")).scalar_one()
        assert job.state == "queued"
    # detail capture was snapshotted (sanitized) because the setting is on
    listed = snapshots.list_snapshots("x")
    assert listed and listed[0]["file"].endswith("-tweet_detail.json.gz")
    # explicit prompt on the post is never overwritten by the reply
    pid2 = seed_post(platform="x", platform_post_id="1001-1", prompt="ORIGINAL PROMPT", author="@auroraforge",
                     assertions={"prompt": {"value": "ORIGINAL PROMPT", "source": "observed", "confidence": 0.96}})
    xmod.XAdapter._detail_cache = {}
    assert enrichment.enrich_post(pid2, {}) == "complete"
    with db_mod.session_scope() as s:
        assert s.get(Post, pid2).prompt == "ORIGINAL PROMPT"


def test_enrich_skips_without_capability_or_session(app_env):
    lex = seed_post(platform="lexica")
    assert enrichment.enrich_post(lex, {}) == "skipped"
    xp = seed_post(platform="x", platform_post_id="5", author="@a")
    assert enrichment.enrich_post(xp, {}) == "skipped"          # no login session → nothing fetched
    assert enrichment.enrich_post(999999, {}) == "skipped"
    queue.ensure_handlers()
    assert "enrich" in queue.handlers()


def _civitai_transport(state):
    def handler(request: httpx.Request) -> httpx.Response:
        state.append(str(request.url))
        if request.url.path.endswith("/creators"):
            return httpx.Response(200, json={"items": [
                {"username": "ArtX", "modelCount": 12, "link": "https://civitai.com/user/ArtX",
                 "image": "https://img/x.png"}]})
        if request.url.params.get("postId") == "77":
            return httpx.Response(200, json={"items": [
                {"id": 501, "url": "https://img/501.png", "postId": 77, "username": "ArtX",
                 "meta": {"prompt": "sibling one"}, "stats": {"likeCount": 5}},
                {"id": 502, "url": "https://img/502.png", "postId": 77, "username": "ArtX", "meta": None},
                {"id": 503, "url": "https://img/503.png", "postId": 77, "username": "ArtX",
                 "meta": {"prompt": "sibling three"}},
            ]})
        return httpx.Response(200, json={"items": []})
    return httpx.MockTransport(handler)


def test_civitai_related_author_and_enrichment(app_env, monkeypatch):
    calls = []
    monkeypatch.setattr(civitai.CivitaiAdapter, "make_client",
                        lambda self, s, transport=None: httpx.Client(transport=_civitai_transport(calls)))
    item = {"id": 501, "url": "https://img/501.png", "postId": 77, "username": "ArtX", "userId": 9,
            "width": 1024, "height": 1536, "nsfwLevel": "None", "baseModel": "Flux.1 D",
            "stats": {"likeCount": 40, "commentCount": 2, "heartCount": 3},
            "meta": {"prompt": "sibling one", "seed": 1}}
    sp = civitai.parse_item(item)
    assert sp.observed["engagement"] == {"likes": 40, "comments": 2, "hearts": 3}
    assert sp.observed["author"]["handle"] == "ArtX" and sp.params["_civitai_post_id"] == 77
    pid = seed_post(platform="civitai", platform_post_id="501", author="ArtX",
                    params={"_civitai_post_id": 77}, observed=sp.observed)
    seed_post(platform="civitai", platform_post_id="503")     # already in the library
    assert enrichment.enrich_post(pid, {}) == "complete"
    with db_mod.session_scope() as s:
        p = s.get(Post, pid)
        rel = {r["platform_post_id"]: r["known"] for r in p.enrichment["related"]}
        assert rel == {"502": False, "503": True}                 # self excluded, known flagged
        assert p.enrichment["author"]["model_count"] == 12
        assert p.observed["author"]["profile_url"] == "https://civitai.com/user/ArtX"
        creator = s.get(Creator, p.creator_id)
        assert creator.handle == "artx" and creator.avatar_url == "https://img/x.png"
    assert any("postId=77" in c for c in calls) and any("/creators" in c for c in calls)


# --------------------------------------------------------- source metrics --
def test_source_metrics_and_recommendation(app_env, client):
    for i in range(4):
        seed_post(platform="civitai", prompt=f"p{i}", params={"metadata_format": "a1111"},
                  ai_status="definitely_ai", inspiration_score=70)
    seed_post(platform="lexica", prompt=None, ai_status="uncertain", inspiration_score=20)
    with db_mod.session_scope() as s:
        get_adapter("civitai").get_state(s)
        get_adapter("lexica").get_state(s)
        sources.record_run(s, "civitai", IngestStats(found=20, new=8, duplicates=10), 12.0)
        sources.record_run(s, "civitai", IngestStats(found=20, new=6, duplicates=12), 9.0)
        sources.record_run(s, "lexica", IngestStats(found=30, new=1, duplicates=29, errors=0), 3.0)
        civ = sources.source_report(s, "civitai")
        lex = sources.source_report(s, "lexica")
        assert civ["runs"] == 2 and civ["discovered"] == 40 and civ["kept"] == 14
        assert civ["discovery_yield"] == 0.35 and civ["duplicate_rate"] == 0.55
        assert civ["prompt_yield"] == 1.0 and civ["metadata_yield"] == 1.0 and civ["ai_rate"] == 1.0
        assert civ["reliability"] == 1.0 and civ["efficiency"] > lex["efficiency"]
        assert lex["recommendation"].startswith("lower priority")
        assert sources.all_reports(s)[0]["name"] == "civitai"
        assert sources.source_report(s, "seaart")["recommendation"] == "no data yet"
        state = s.get(ScraperState, "civitai").state
        assert len(state["runs"]) == 2 and state["runs"][-1]["duration_s"] == 9.0
    r = client.get("/api/scrapers/civitai/metrics")
    assert r.status_code == 200 and r.json()["kept"] == 14
    assert client.get("/api/scrapers/nope/metrics").status_code == 404
    caps = {s_["name"]: s_["capabilities"] for s_ in client.get("/api/scrapers").json()["scrapers"]}
    assert "comments" in caps["x"] and "api" in caps["civitai"]


# -------------------------------------------------------------- snapshots --
def test_snapshots_sanitize_gate_prune_and_load(app_env):
    payload = {"data": {"user": {"screen_name": "a", "auth_token": "abc", "Cookie": "x=1"},
                        "headers": {"Authorization": "Bearer abc"},
                        "token": "sec", "url": "https://x.com/a/status/1",
                        "opaque": "A" * 40, "n": [{"session_id": 1, "ok": True}]}}
    clean = snapshots.sanitize(payload)
    assert "auth_token" not in clean["data"]["user"] and "Cookie" not in clean["data"]["user"]
    assert "headers" in clean["data"] and "Authorization" not in clean["data"]["headers"]
    assert "token" not in clean["data"] and clean["data"]["opaque"] == "[redacted]"
    assert clean["data"]["url"].startswith("https://") and clean["data"]["n"] == [{"ok": True}]
    assert snapshots.maybe_save("x", "captured", payload) is None          # setting off
    with db_mod.session_scope() as s:
        settings_store.put(s, "intel_snapshots", True)
    path = snapshots.maybe_save("x", "captured", payload, {"start_url": "https://x.com/explore"})
    assert path and path.exists()
    with gzip.open(path, "rt") as fh:
        body = json.load(fh)
    assert body["payload"]["data"]["opaque"] == "[redacted]" and body["meta"]["start_url"]
    assert snapshots.maybe_save("x", "captured", []) is None                # nothing to keep
    for i in range(snapshots.MAX_PER_PLATFORM + 5):
        snapshots.save_snapshot("x", "k", {"i": i})
    assert len(snapshots.list_snapshots("x")) == snapshots.MAX_PER_PLATFORM
    first = snapshots.list_snapshots("x")[0]
    assert snapshots.load_snapshot("x", first["file"])["kind"] == "k"
    assert snapshots.load_snapshot("x", "../" + first["file"]) is None
    assert snapshots.load_snapshot("x", "missing.json.gz") is None
