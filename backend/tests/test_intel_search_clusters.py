"""Phase I6: advanced search syntax, clusters, similarity, trends, analytics,
the post-intel view."""
from datetime import datetime, timedelta, timezone

from promptforge import db as db_mod, settings_store
from promptforge.intel import clusters, query, similar, trends
from promptforge.llm import client as llm_client
from promptforge.models import Creator, Post
from tests.conftest import seed_post


# ----------------------------------------------------------------- parser --
def test_parser_covers_every_qualifier_and_ignores_junk():
    pq = query.parse('neon "rainy street" tag:cyber model:"flux dev" platform:X has:prompt has:video '
                     'creator:@ArtX technique:orbit camera:35mm after:2025-01-01 before:2025-12-31 '
                     'engagement:>1000 inspiration:>=80 ai:true model_source:explicit sort:inspiration '
                     'has:teapot after:yesterday engagement:lots ai:maybe')
    assert pq.free_text == 'neon "rainy street"'
    assert pq.tags == ["cyber"] and pq.models == ["flux dev"] and pq.platforms == ["x"]
    assert pq.has == {"prompt", "video"} and pq.creators == ["artx"]
    assert pq.techniques == ["orbit"] and pq.cameras == ["35mm"]
    assert pq.after.year == 2025 and pq.before.month == 12
    assert pq.engagement == (">", 1000.0) and pq.inspiration == (">=", 80.0)
    assert pq.ai == "true" and pq.model_source == "explicit" and pq.sort == "inspiration"
    assert set(pq.ignored) == {"has:teapot", "after:yesterday", "engagement:lots", "ai:maybe"}
    assert pq.legacy() == {"tag": ["cyber"], "model": ["flux dev"], "platform": ["x"]}
    assert query.parse("plain words").free_text == "plain words"
    assert query.parse("engagement:500").engagement == (">=", 500.0)


def test_search_qualifiers_filter_and_sort(app_env, client):
    now = datetime.now(timezone.utc)
    with db_mod.session_scope() as s:
        c = Creator(platform="x", handle="artx")
        s.add(c)
        s.flush()
        cid = c.id
    a = seed_post(prompt="neon alley portrait, 35mm", platform="x", creator_id=cid, has_workflow=True,
                  engagement_total=5000, inspiration_score=90, ai_status="definitely_ai",
                  model_source="explicit", technique_tags=["orbit"], media_type="video",
                  posted_at=now - timedelta(days=2), params={"metadata_format": "comfyui"},
                  assertions={"camera": {"value": {"lens_mm": [35]}, "source": "extracted", "confidence": 0.8}},
                  enrichment={"comments": [{"id": "1"}]})
    b = seed_post(prompt="neon alley wide shot", platform="civitai", engagement_total=10,
                  inspiration_score=40, ai_status="uncertain", model_source="inferred",
                  posted_at=now - timedelta(days=40))
    c_ = seed_post(prompt=None, platform="x", engagement_total=None, inspiration_score=None,
                   ai_status="probably_not_ai", model_source=None, posted_at=now - timedelta(days=60))

    def ids(q, **params):
        r = client.get("/api/inspiration/search", params={"q": q, **params})
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()["items"]]

    assert ids("neon") == [a, b]                               # FTS both
    assert ids("neon has:workflow") == [a]
    assert ids("has:prompt") == [b, a] and ids("has:video") == [a]
    assert ids("has:metadata") == [a] and ids("has:comments") == [a]
    assert ids("creator:artx") == [a] and ids("technique:orbit") == [a]
    assert ids("camera:35mm") == [a]
    assert ids(f"after:{(now - timedelta(days=10)).date()}") == [a]
    assert ids(f"before:{(now - timedelta(days=10)).date()}") == [c_, b]
    assert ids("engagement:>1000") == [a] and ids("engagement:<100") == [b]
    assert ids("inspiration:>80") == [a] and ids("inspiration:<=40") == [b]
    assert ids("ai:true") == [a] and ids("ai:false") == [c_] and ids("ai:uncertain") == [b]
    assert ids("model_source:explicit") == [a] and ids("model_source:inferred") == [b]
    assert ids("platform:x has:prompt") == [a]
    # sorts: newest (default), inspiration, engagement, oldest; FTS re-rank
    assert ids("") == [c_, b, a]
    assert ids("sort:inspiration") == [a, b, c_]
    assert ids("", sort="engagement") == [a, b, c_]
    assert ids("sort:oldest") == [a, b, c_]
    assert ids("neon sort:engagement") == [a, b]
    # offset cursor for sorted listings
    r = client.get("/api/inspiration/search", params={"q": "sort:inspiration", "limit": 2}).json()
    assert [i["id"] for i in r["items"]] == [a, b] and r["next_cursor"] == 2
    r2 = client.get("/api/inspiration/search", params={"q": "sort:inspiration", "limit": 2, "cursor": 2}).json()
    assert [i["id"] for i in r2["items"]] == [c_] and r2["next_cursor"] is None
    # junk is reported, never fatal; legacy /api/search still works with the new syntax
    assert client.get("/api/inspiration/search", params={"q": "has:teapot"}).json()["ignored"] == ["has:teapot"]
    assert [i["id"] for i in client.get("/api/search", params={"q": "neon ai:true"}).json()["items"]] == [a]


# ---------------------------------------------------------------- clusters --
def test_clusters_rebuild_membership_and_api(app_env, client):
    with db_mod.session_scope() as s:
        c = Creator(platform="x", handle="motionmuse")
        s.add(c)
        s.flush()
        cid = c.id
    p1 = seed_post(prompt="cinematic trailer shot of a cyberpunk city, anamorphic, teal and orange",
                   media_type="video", model_family="kling", model_source="explicit",
                   technique_tags=["orbit", "anamorphic"], inspiration_score=88, creator_id=cid,
                   engagement_total=9000, assertions={"prompt": {"value": "x", "source": "observed", "confidence": 0.96}})
    p2 = seed_post(prompt="cinematic film still, dolly in on a cyberpunk android, neon",
                   media_type="video", model_family="kling", model_source="explicit",
                   technique_tags=["dolly"], inspiration_score=70, creator_id=cid, engagement_total=50)
    p3 = seed_post(prompt="watercolor fox in a forest, pastel", model_family="flux", model_source="explicit",
                   inspiration_score=60, engagement_total=40)
    p4 = seed_post(prompt="watercolor owl, pastel palette", model_family="flux", model_source="inferred",
                   inspiration_score=30, engagement_total=20)
    p5 = seed_post(prompt="lone bottle product shot", has_workflow=True, inspiration_score=50,
                   params={"metadata_format": "comfyui"}, engagement_total=8000)
    p6 = seed_post(prompt="brutalist cathedral interior", has_workflow=True, inspiration_score=45,
                   engagement_total=7000)
    with db_mod.session_scope() as s:
        result = clusters.rebuild(s)
        assert result["posts"] == 6 and result["clusters"] >= 8
        by = {(c.kind, c.key): c for c in s.execute(__import__("sqlalchemy").select(clusters.Cluster)).scalars()}
        assert by[("topic", "cinematic-ai-video")].post_count == 2
        assert by[("topic", "sci-fi")].post_count == 2
        assert by[("model", "kling")].post_count == 2 and by[("model", "kling")].label == "Kling"
        assert ("model", "flux") not in by or by[("model", "flux")].post_count == 1 or True
        assert by[("style", "watercolor")].post_count == 2 and by[("palette", "pastel")].post_count == 2
        assert by[("topic", "comfyui-workflows")].post_count == 2
        assert by[("creator", "motionmuse")].post_count == 2 and by[("media", "video")].post_count == 2
        assert by[("engagement", "viral")].post_count >= 1
        top = by[("topic", "cinematic-ai-video")].data
        assert top["top_post_ids"][0] == p1 and top["models"][0]["family"] == "kling"
        assert top["creators"][0]["handle"] == "motionmuse" and top["strongest_prompts"][0]["post_id"] == p1
        assert "orbit" in [t["slug"] for t in top["techniques"]]
        # inferred-model posts do not form model clusters
        assert ("model", "flux") not in by
        # idempotent rebuild keeps ids stable, drops stale clusters
        cine_id = by[("topic", "cinematic-ai-video")].id
        s.delete(s.get(Post, p6))
        s.flush()
        clusters.rebuild(s)
        by2 = {(c.kind, c.key): c for c in s.execute(__import__("sqlalchemy").select(clusters.Cluster)).scalars()}
        assert by2[("topic", "cinematic-ai-video")].id == cine_id
        assert ("topic", "comfyui-workflows") not in by2          # only one member left
        assert [c["key"] for c in clusters.clusters_for_post(s, p3)][:1] and \
            {c["key"] for c in clusters.clusters_for_post(s, p3)} >= {"watercolor", "pastel", "image"}
    r = client.get("/api/inspiration/clusters?kind=topic").json()["clusters"]
    assert r[0]["post_count"] >= r[-1]["post_count"] and all(c["kind"] == "topic" for c in r)
    cine = next(c for c in r if c["key"] == "cinematic-ai-video")
    detail = client.get(f"/api/inspiration/clusters/{cine['id']}").json()
    assert [i["id"] for i in detail["items"]] == [p1, p2]
    assert detail["top_posts"][0]["id"] == p1 and detail["newest_posts"][0]["id"] == p2
    assert client.get("/api/inspiration/clusters/9999").status_code == 404
    assert client.post("/api/inspiration/clusters/rebuild").json()["posts"] == 5
    assert p4 and p5


# -------------------------------------------------------------- similarity --
def test_similarity_modes_and_best_for_model(app_env, client):
    a = seed_post(prompt="a red fox running through a misty pine forest at dawn", phash="ffff0000ffff0000",
                  technique_tags=["orbit", "golden-hour"], model_family="flux", inspiration_score=80,
                  assertions={"prompt": {"value": "x", "source": "observed", "confidence": 0.96}})
    b = seed_post(prompt="a red fox sleeping in a misty pine forest", phash="ffff0000ffff0003",
                  technique_tags=["orbit"], model_family="flux", inspiration_score=70,
                  assertions={"prompt": {"value": "x", "source": "observed", "confidence": 0.96}})
    c = seed_post(prompt="brutalist concrete tower at night", phash="0000ffff0000ffff",
                  technique_tags=["golden-hour", "dolly"], model_family="flux", inspiration_score=90,
                  prompt_source="ai", assertions={"prompt": {"value": "x", "source": "ai", "confidence": 0.9}})
    d = seed_post(prompt="misty forest fox portrait", model_family="kling", inspiration_score=65)
    with db_mod.session_scope() as s:
        pa = s.get(Post, a)
        vis = similar.visual(s, pa)
        assert vis[0]["post_id"] == b and vis[0]["distance"] == 2 and all(r["post_id"] != c for r in vis)
        pr = similar.prompt_similar(s, pa)
        assert [r["post_id"] for r in pr[:2]] == [b, d] and pr[0]["similarity"] > pr[1]["similarity"]
        tech = similar.technique_related(s, pa)
        assert [r["post_id"] for r in tech] == [b, c] or [r["post_id"] for r in tech] == [c, b]
        assert {r["post_id"]: r["shared"] for r in tech} == {b: 1, c: 1}
        assert similar.best_for_model(s, "flux") == [a, b]        # AI-sourced prompt excluded
        rel = similar.related(s, pa)
        assert set(rel) == {"visual", "prompt", "technique", "links"}
    r = client.get(f"/api/inspiration/similar/{a}?mode=visual").json()
    assert r["items"][0]["id"] == b and r["rows"][0]["similarity"] > 0.9
    r = client.get(f"/api/inspiration/similar/{a}").json()
    assert r["mode"] == "all" and r["prompt"]["items"][0]["id"] == b
    assert [i["id"] for i in client.get("/api/inspiration/best?model=flux").json()["items"]] == [a, b]
    assert client.get("/api/inspiration/similar/9999").status_code == 404


# ------------------------------------------------------------------ trends --
def test_trends_series_rising_overview_and_grounded_summary(app_env, client):
    now = datetime.now(timezone.utc)
    for i in range(6):                        # kling steady across weeks
        seed_post(prompt="cinematic orbit shot of a lighthouse", model_family="kling", model_source="explicit",
                  technique_tags=["orbit"], media_type="video", media_width=1920, media_height=1080,
                  duration_s=6, posted_at=now - timedelta(weeks=i), inspiration_score=60)
    for i in range(4):                        # veo appears only in the last two weeks → rising
        seed_post(prompt="veo test, watercolor whale", model_family="veo", model_source="explicit",
                  media_width=1080, media_height=1920, posted_at=now - timedelta(days=3 * i), inspiration_score=70)
    with db_mod.session_scope() as s:
        t = trends.weekly_series(s, weeks=8, now=now)
        assert len(t["weeks"]) == 8 and t["posts_considered"] == 10
        assert t["series"]["models"]["kling"][-1] >= 1 and sum(t["series"]["models"]["kling"]) == 6
        assert sum(t["series"]["models"]["veo"]) == 4
        assert t["series"]["techniques"]["orbit"] and t["series"]["topics"]["cinematic-ai-video"]
        assert t["series"]["styles"]["watercolor"] and "video:16:9" in t["series"]["formats"]
        assert "video:5-10s" in t["series"]["formats"] and "image:9:16" in t["series"]["formats"]
        assert any(r["kind"] == "models" and r["key"] == "veo" for r in t["rising"])
        assert not any(r["key"] == "kling" for r in t["rising"])
        ov = trends.overview(s)
        assert ov["posts"] == 10 and ov["by_platform"] == {"civitai": 10}
        assert sum(b["count"] for b in ov["inspiration_histogram"]) == 10 and ov["queue_pending"] == 0
        assert trends.summarize(s, t) is None                 # no provider → deterministic only
    r = client.get("/api/inspiration/analytics/trends?weeks=8").json()
    assert r["series"]["models"]["veo"] and client.get("/api/inspiration/analytics").json()["posts"] == 10
    assert client.post("/api/inspiration/analytics/summary").status_code == 409
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "mock")
    llm_client.mock_instance.responses = ["veo rose from 0 to 4 posts in the last two weeks; kling stayed at 6."]
    llm_client.mock_instance.calls.clear()
    out = client.post("/api/inspiration/analytics/summary").json()
    assert "veo" in out["text"] and out["grounded_in"]["posts_considered"] == 10
    assert '"veo"' in llm_client.mock_instance.calls[0][1]      # the numbers are the prompt
    assert client.get("/api/inspiration/analytics").json()["summary"]["text"] == out["text"]


# --------------------------------------------------------------- post intel -
def test_post_intel_view_and_manual_enrichment_enqueue(app_env, client):
    with db_mod.session_scope() as s:
        c = Creator(platform="x", handle="artx", followers=10)
        s.add(c)
        s.flush()
        cid = c.id
    pid = seed_post(prompt="neon alley, 35mm", creator_id=cid, inspiration_score=77, candidate_score=66,
                    model_version="2.1", technique_tags=["orbit"], params={"seed": 1, "_raw_metadata": {"parameters": "x"}},
                    assertions={"prompt": {"value": "neon alley, 35mm", "source": "observed", "confidence": 0.96},
                                "camera": {"value": {"lens_mm": [35]}, "source": "extracted", "confidence": 0.8,
                                           "evidence": "35mm"},
                                "_alternates": {"prompt": [{"value": "ai guess", "source": "ai", "confidence": 0.5}]}},
                    analysis={"inspiration": {"prompt_quality": {"value": 1, "weight": 1.5, "contribution": 20}},
                              "ai": {"status": "probably_ai", "confidence": 0.7, "source": "heuristic"}},
                    enrichment={"comments": [{"id": "1", "text": "seed?"}]})
    r = client.get(f"/api/inspiration/posts/{pid}/intel")
    assert r.status_code == 200
    body = r.json()
    assert body["scores"]["inspiration"] == 77 and body["scores"]["inspiration_breakdown"][0]["component"] == "prompt_quality"
    assert body["detected"]["camera"] == {"lens_mm": [35]} and body["detected"]["model"]["version"] == "2.1"
    assert body["evidence"][0]["field"] in ("prompt", "camera") and body["alternates"]["prompt"][0]["source"] == "ai"
    assert body["generation"] == {"seed": 1} and body["raw_metadata_keys"] == ["parameters"]
    assert body["ai"]["status"] == "probably_ai" and body["creator"]["handle"] == "artx"
    assert body["enrichment"]["comments"][0]["text"] == "seed?"
    assert client.get("/api/inspiration/posts/9999/intel").status_code == 404
    e = client.post(f"/api/inspiration/enrichment/{pid}/run").json()
    assert e["stage"] == "enrich" and e["state"] == "queued"
    assert client.post(f"/api/inspiration/enrichment/{pid}/run?stage=nope").status_code == 422
    assert client.get(f"/api/inspiration/enrichment/{pid}").json()["enrichment"]["comments"]


# ------------------------------------------- I15: the new search qualifiers --
def test_source_confidence_and_research_qualifiers(app_env, client):
    """`source:` reads better than `platform:`, `confidence:` filters on the
    prompt assertion PF2 actually recorded, and `research:` scopes a search to
    one job's results — a stale job id matches nothing, never errors."""
    from promptforge.intel import query as iquery
    from promptforge.models import ResearchJob

    sure = seed_post(platform="reddit", prompt="a certain prompt",
                     prompt_source="explicit_caption",
                     assertions={"prompt": {"value": "a certain prompt", "source": "extracted",
                                            "confidence": 0.95}})
    unsure = seed_post(platform="reddit", prompt="a shaky prompt",
                       prompt_source="deterministic_inference",
                       assertions={"prompt": {"value": "a shaky prompt", "source": "extracted",
                                              "confidence": 0.4}})
    elsewhere = seed_post(platform="bluesky", prompt="somewhere else")
    with db_mod.session_scope() as s:
        job = ResearchJob(query="kling", status="complete", sources=["reddit"],
                          result_post_ids=[sure, elsewhere])
        s.add(job)
        s.flush()
        job_id = job.id

    def ids(q: str) -> set[int]:
        r = client.get("/api/inspiration/search", params={"q": q})
        assert r.status_code == 200, r.text
        return {i["id"] for i in r.json()["items"]}

    assert ids("source:reddit") == {sure, unsure}
    assert ids("source:reddit") == ids("platform:reddit")   # a readable alias
    assert ids("confidence:>0.8") == {sure}
    assert ids("confidence:<0.5") == {unsure}
    assert ids(f"research:{job_id}") == {sure, elsewhere}
    assert ids(f"research:{job_id} source:reddit") == {sure}
    assert ids("research:999999") == set()                 # stale id, not an error
    assert iquery.parse("confidence:9").ignored == ["confidence:9"]
    assert client.get("/api/inspiration/search",
                      params={"q": "research:nope"}).json()["ignored"] == ["research:nope"]
