"""Phase I1: additive migration, layered envelope + provenance, Candidate /
Inspiration scores, sha256 + dHash dedupe links, central pipeline queue."""
import io
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from promptforge import config as cfg_mod, db as db_mod, settings_store
from promptforge.intel import dedupe, provenance, queue, scoring
from promptforge.models import (Creator, EngagementSnapshot, PipelineJob, Post,
                                PostLink)
from promptforge.pipeline import ingest
from promptforge.scrapers.base import ScrapedPost
from tests.conftest import seed_post


# ------------------------------------------------------------------ helpers -
def make_image(seed: int = 1, size=(640, 480)) -> Image.Image:
    im = Image.new("RGB", size, (20 + seed * 30 % 200, 40, 90))
    d = ImageDraw.Draw(im)
    for i in range(6):
        x = (i * 97 + seed * 31) % size[0]
        y = (i * 53 + seed * 17) % size[1]
        d.ellipse([x, y, x + 120, y + 90], fill=(200 - i * 20, 120 + i * 15, 40 + seed))
        d.rectangle([x // 2, y // 3, x // 2 + 60, y // 3 + 200], fill=(30, 200 - seed, 150))
    return im


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def jpeg_bytes(im: Image.Image, q=60) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=q)
    return buf.getvalue()


# ---------------------------------------------------------------- migration -
def test_additive_migration_upgrades_legacy_db(tmp_path, app_env):
    """A v1.0-shaped posts table (no intel columns) is upgraded in place:
    rows, ids and prompts survive; new columns carry model defaults."""
    db_mod.dispose_db()
    cfg = cfg_mod.Config(data_dir=tmp_path / "legacy")
    cfg_mod.set_config(cfg)
    cfg.ensure_dirs()
    con = sqlite3.connect(cfg.db_path)
    con.execute("""CREATE TABLE posts (
        id INTEGER PRIMARY KEY, platform VARCHAR(50), platform_post_id VARCHAR(200),
        prompt TEXT, media_type VARCHAR(10), params JSON, scraped_at DATETIME,
        favorite BOOLEAN, media_path TEXT)""")
    con.execute("INSERT INTO posts VALUES (7, 'civitai', 'legacy-1', 'legacy fox', 'image', '{}', "
                "'2025-01-01 00:00:00', 1, 'media/civitai/old.webp')")
    con.commit()
    con.close()

    engine = db_mod.init_db()
    with db_mod.session_scope() as s:
        post = s.get(Post, 7)
        assert post.prompt == "legacy fox" and post.favorite is True
        assert post.media_path == "media/civitai/old.webp"
        assert post.observed == {} and post.assertions == {}
        assert post.pipeline_state == "stored"
        assert post.origin == "scraped" and post.nsfw is False
        assert post.technique_tags == []
        # new tables exist and are usable
        s.add(PipelineJob(post_id=7, stage="enrich"))
    assert db_mod.migrate_schema(engine) == []          # idempotent
    cols = {c[1] for c in sqlite3.connect(cfg.db_path).execute("PRAGMA table_info(posts)")}
    assert {"observed", "phash", "inspiration_score", "creator_id"} <= cols


# --------------------------------------------------------------- provenance -
def test_provenance_ranking_never_lets_ai_overwrite_explicit():
    a = {}
    assert provenance.assert_field(a, "model", "Kling", "ai", 0.6, "guessed from motion")
    assert provenance.assert_field(a, "model", "Flux", "extracted", 0.85, "named in text")
    assert provenance.canonical(a, "model") == "Flux"
    assert not provenance.assert_field(a, "model", "Sora", "ai", 0.9)      # lower rank loses
    assert provenance.canonical(a, "model") == "Flux"
    assert provenance.assert_field(a, "model", "flux.1-dev", "metadata", 0.95)  # higher rank wins
    assert provenance.source_of(a, "model") == "metadata"
    assert len(a["_alternates"]["model"]) == 3
    assert provenance.is_high_confidence(a, "model")
    assert not provenance.assert_field(a, "prompt", "", "observed")
    rows = provenance.evidence_list(a)
    assert rows[0]["field"] == "model" and rows[0]["source"] == "metadata"


# ------------------------------------------------------------------ scoring -
def test_candidate_score_ranks_rich_over_noise():
    now = datetime.now(timezone.utc)
    rich = ScrapedPost(platform="civitai", platform_post_id="1", media_url="http://x/a.png",
                       prompt="cinematic portrait, 85mm lens, soft rim lighting, film grain",
                       model_name="flux.1-dev", posted_at=now - timedelta(hours=2),
                       params={"seed": 1, "steps": 30, "cfg_scale": 5, "sampler": "euler",
                               "size": "1024x1536"},
                       observed={"engagement": {"likes": 900, "comments": 40},
                                 "author": {"handle": "artx", "followers": 12000}})
    noise = ScrapedPost(platform="x", platform_post_id="2", media_url="http://x/b.jpg",
                        prompt=None, posted_at=now - timedelta(days=400),
                        params={"engagement": {"likes": 1}})
    rs, rb = scoring.candidate_score(rich)
    ns, nb = scoring.candidate_score(noise)
    assert rs > 75 > 40 > ns
    assert set(rb) == set(scoring.DEFAULT_WEIGHTS["candidate"])
    assert abs(sum(v["contribution"] for v in rb.values()) - rs) < 1.0
    # an X post that names a model + hashtag AI terms beats a bare one
    hinted = ScrapedPost(platform="x", platform_post_id="3", media_url="http://x/c.mp4",
                         media_type="video", prompt="Prompt: orbit shot of a glass city",
                         model_name="Kling", posted_at=now,
                         params={"hashtags": ["#aivideo"], "model_stated": True,
                                 "prompt_confidence": "high",
                                 "engagement": {"likes": 500, "reposts": 60}})
    hs, hb = scoring.candidate_score(hinted)
    assert hs > ns + 25 and hb["ai_likelihood"]["value"] > 0.8
    # weights are configurable — muting engagement + prompt lowers the rich one
    ws, _ = scoring.candidate_score(rich, {"candidate": {"engagement": 0, "prompt": 0}})
    assert ws < rs
    # seen-before prompt → novelty drops
    seen = {hash(rich.prompt.strip().lower())}
    ss, sb = scoring.candidate_score(rich, recent_prompt_hashes=seen)
    assert sb["novelty"]["value"] == 0.2 and ss < rs


def test_inspiration_score_and_explain(app_env):
    good = seed_post(prompt="a lone lighthouse in a storm, cinematic lighting, 35mm, volumetric fog",
                     media_width=2048, media_height=1152,
                     params={"seed": 5, "steps": 28, "cfg_scale": 4.5, "sampler": "dpm++",
                             "size": "2048x1152", "model": "flux"},
                     observed={"engagement": {"likes": 2000}}, engagement_total=2000,
                     assertions={"prompt": {"value": "x", "source": "metadata", "confidence": 0.95}})
    bad = seed_post(prompt="cat", media_width=256, media_height=256, model_name=None,
                    model_family=None, params={})
    with db_mod.session_scope() as s:
        gs, gb = scoring.inspiration_score(s.get(Post, good))
        bs, bb = scoring.inspiration_score(s.get(Post, bad))
    assert gs > 70 > 35 > bs
    rows = scoring.explain(gb)
    assert rows[0]["contribution"] >= rows[-1]["contribution"]
    assert {r["component"] for r in rows} == set(scoring.DEFAULT_WEIGHTS["inspiration"])
    # near duplicates cost novelty
    with db_mod.session_scope() as s:
        dup_s, _ = scoring.inspiration_score(s.get(Post, good), near_dups=2)
    assert dup_s < gs


# ------------------------------------------------------------------- dedupe -
def test_dhash_survives_resize_and_recompression(tmp_path):
    im = make_image(1)
    a = tmp_path / "a.png"
    im.save(a)
    b = tmp_path / "b.jpg"
    im.resize((320, 240)).save(b, quality=55)
    c = tmp_path / "c.png"
    make_image(9, (500, 700)).save(c)
    ha, hb, hc = dedupe.dhash(a), dedupe.dhash(b), dedupe.dhash(c)
    assert len(ha) == 16
    assert dedupe.hamming(ha, hb) <= 6
    assert dedupe.hamming(ha, hc) > 12
    assert dedupe.sha256_file(a) != dedupe.sha256_file(b)
    assert dedupe.hamming(None, ha) == 64
    assert dedupe.dhash(tmp_path / "missing.png") is None


def test_links_are_symmetric_and_idempotent(app_env):
    a, b = seed_post(phash="00000000000000ff"), seed_post(phash="00000000000000fe")
    with db_mod.session_scope() as s:
        assert dedupe.near_duplicates(s, "00000000000000ff", exclude_id=a) == [(b, 1)]
        assert dedupe.link_posts(s, a, b, "near", 0.98)
        assert not dedupe.link_posts(s, a, b, "near", 0.98)
        assert not dedupe.link_posts(s, a, a, "near")
        assert dedupe.links_for(s, b) == [{"post_id": a, "kind": "near", "score": 0.98}]
        assert s.execute(select(PostLink)).scalars().all().__len__() == 2


# -------------------------------------------------------------------- queue -
def test_queue_state_machine_retry_defer_and_stats(app_env, monkeypatch):
    pid = seed_post()
    with db_mod.session_scope() as s:
        j1 = queue.enqueue(s, pid, "enrich", priority=10)
        j2 = queue.enqueue(s, pid, "enrich", priority=40, payload={"why": "again"})
        assert j1.id == j2.id and j2.priority == 40 and j2.payload == {"why": "again"}
        queue.enqueue(s, pid, "analysis", priority=99)
        with pytest.raises(ValueError):
            queue.enqueue(s, pid, "nope")
    # no handler registered → nothing claimable
    assert queue.process_one() is None

    calls = []

    def flaky(post_id, payload):
        calls.append(post_id)
        if len(calls) < 3:
            raise RuntimeError("boom")
        return "complete"
    monkeypatch.setattr(queue, "_handlers", {"enrich": flaky})
    with db_mod.session_scope() as s:
        job = s.execute(select(PipelineJob).where(PipelineJob.stage == "enrich")).scalar_one()
        job.max_attempts = 2
    assert queue.process_one() == "retryable"
    assert queue.process_one() is None          # backoff holds
    monkeypatch.setattr(queue, "RETRY_BACKOFF", timedelta(0))
    assert queue.process_one() == "failed"      # attempts exhausted
    with db_mod.session_scope() as s:
        st = queue.stats(s)
        assert st["stages"]["enrich"]["failed"] == 1
        assert st["errors"][0]["error"].startswith("RuntimeError")
        assert queue.retry(s) == 1
    assert queue.process_one() == "complete"    # third call succeeds

    def broke(post_id, payload):
        raise queue.Deferred("budget")
    monkeypatch.setattr(queue, "_handlers", {"analysis": broke})
    assert queue.process_one() == "deferred"
    with db_mod.session_scope() as s:
        job = s.execute(select(PipelineJob).where(PipelineJob.stage == "analysis")).scalar_one()
        assert job.state == "queued" and job.attempts == 0
    assert queue.tick(max_jobs=5) == {"deferred": 1}   # stops after the stage defers
    with db_mod.session_scope() as s:
        assert queue.stats(s)["pending"] == 1
        assert queue.clear(s) == 1


# ------------------------------------------------------- ingest integration -
def test_ingest_builds_envelope_links_and_jobs(app_env):
    base = make_image(3)
    files = {"/a.png": png_bytes(base), "/b.jpg": jpeg_bytes(base.resize((320, 240))),
             "/c.png": png_bytes(make_image(8))}
    hits = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(request.url.path)
        return httpx.Response(200, content=files[request.url.path],
                              headers={"content-type": "image/png"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with db_mod.session_scope() as s:
        settings_store.put(s, "intel_enrich_threshold", 10)
        settings_store.put(s, "intel_analysis_threshold", 10)
        settings_store.put(s, "intel_min_candidate_score", 0)

    a = ScrapedPost(platform="civitai", platform_post_id="a", media_url="http://h/a.png",
                    prompt="neon alley, rain, cinematic lighting, 35mm",
                    model_name="flux.1-dev", author="@ArtX", source_url="http://h/p/a",
                    params={"seed": 1, "steps": 25, "cfg_scale": 4},
                    observed={"author": {"handle": "ArtX", "display_name": "Art X",
                                         "followers": 5000, "verified": True},
                              "engagement": {"likes": 120, "comments": 3, "reposts": 4},
                              "text": {"body": "neon alley"}})
    stats = ingest.ingest_batch("civitai", [a], client)
    assert stats.new == 1 and stats.filtered == 0
    with db_mod.session_scope() as s:
        post = s.get(Post, stats.new_ids[0])
        assert post.observed["engagement"]["likes"] == 120
        assert post.observed["identity"]["platform_post_id"] == "a"
        assert post.engagement_total == 127
        assert post.content_hash and len(post.content_hash) == 64
        assert post.phash and len(post.phash) == 16
        assert post.assertions["prompt"]["source"] == "observed"
        assert post.prompt_source == "observed" and post.model_source == "explicit"
        assert post.candidate_score > 50 and post.inspiration_score > 30
        assert post.analysis["inspiration"]["prompt_quality"]["value"] > 0
        assert post.discovered_at is not None
        creator = s.get(Creator, post.creator_id)
        assert creator.handle == "artx" and creator.followers == 5000 and creator.verified
        snap = s.execute(select(EngagementSnapshot).where(
            EngagementSnapshot.post_id == post.id)).scalar_one()
        assert snap.likes == 120 and snap.comments == 3
        jobs = {j.stage: j for j in s.execute(select(PipelineJob)).scalars()}
        assert {"enrich", "analysis"} <= set(jobs)
        assert jobs["enrich"].priority == post.candidate_score

    # a resized/recompressed repost elsewhere → linked, never deleted
    b = ScrapedPost(platform="lexica", platform_post_id="b", media_url="http://h/b.jpg",
                    prompt="neon alley, rain, cinematic lighting, 35mm", author="artx")
    stats_b = ingest.ingest_batch("lexica", [b], client)
    assert stats_b.new == 1 and stats_b.near_dups == 1
    with db_mod.session_scope() as s:
        pb = s.get(Post, stats_b.new_ids[0])
        links = dedupe.links_for(s, pb.id)
        assert links and links[0]["kind"] == "near" and links[0]["post_id"] == stats.new_ids[0]
        assert pb.analysis["near_dup_ids"] == [stats.new_ids[0]]
        assert pb.analysis["inspiration"]["novelty"]["value"] < 1.0
        # same creator handle on another platform is a different creator row
        assert s.execute(select(Creator)).scalars().all().__len__() == 2

    # the Candidate Score gate skips weak candidates BEFORE any download
    with db_mod.session_scope() as s:
        settings_store.put(s, "intel_min_candidate_score", 95)
    weak = ScrapedPost(platform="x", platform_post_id="c", media_url="http://h/c.png",
                       posted_at=datetime.now(timezone.utc) - timedelta(days=500))
    before = len(hits)
    stats_c = ingest.ingest_batch("x", [weak], client)
    assert stats_c.filtered == 1 and stats_c.new == 0 and len(hits) == before
    assert sum(stats_c.filter_reasons.values()) == 1
    # gate off (manual/monitoring paths) still ingests
    stats_d = ingest.ingest_batch("x", [weak], client, gate=False)
    assert stats_d.new == 1 and len(hits) == before + 1
