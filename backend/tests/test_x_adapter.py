"""Phase X1 tests: x_text extraction rules, XAdapter GraphQL parsing, media
variants, scope filters, low-confidence knowledge weighting."""
import json
from pathlib import Path

from promptforge import db as db_mod, settings_store
from promptforge.scrapers import x_text
from promptforge.scrapers.x import XAdapter, parse_tweet

FIXTURES = Path(__file__).parent / "fixtures"
X_FIXTURE = json.loads((FIXTURES / "x_graphql.json").read_text())


def captured():
    return [{"url": "https://x.com/i/api/graphql/AbCd/SearchTimeline?q=x",
             "json": X_FIXTURE}]


# ------------------------------------------------------------- x_text -------
def test_extract_prompt_label():
    r = x_text.extract("check this out\n\nPrompt: a fox in a paper boat, "
                       "misty river, 35mm\n\n#flux #AIart https://t.co/xyz")
    assert r.prompt == "a fox in a paper boat, misty river, 35mm"
    assert r.prompt_confidence == "high"
    assert r.model_name == "Flux" and r.model_stated is True
    assert "flux" in r.hashtags


def test_extract_fenced_and_negative():
    r = x_text.extract("run settings below\n```\nglass cathedral at dawn, "
                       "volumetric god rays\n```\nNegative: text, watermark")
    assert r.prompt == "glass cathedral at dawn, volumetric god rays"
    assert r.negative == "text, watermark"
    assert r.prompt_confidence == "high"


def test_extract_quoted_block():
    r = x_text.extract('made with love — "an astronaut tending a rooftop '
                       'garden on a generation ship, warm practical lights" '
                       'so happy with it')
    assert r.prompt.startswith("an astronaut tending")
    assert r.prompt_confidence == "high"


def test_extract_fallback_low_confidence():
    r = x_text.extract("dreamy result from tonight's session @friend #wip "
                       "https://t.co/abc")
    assert r.prompt == "dreamy result from tonight's session"
    assert r.prompt_confidence == "low"
    assert r.model_name is None


def test_extract_quoted_tweet_prompt():
    r = x_text.extract("sharing because the prompt is a masterclass",
                       quoted_text="Prompt: brutalist cathedral interior, 24mm")
    assert r.prompt == "brutalist cathedral interior, 24mm"
    assert r.prompt_confidence == "high"


def test_model_keyword_no_false_positives():
    assert x_text.detect_model("sparkling water on the influx of tourists") is None
    assert x_text.detect_model("my pikachu drawing, ponytail girl") is None
    assert x_text.detect_model("aurora borealis over iceland") is None
    assert x_text.detect_model("kling 2.1 handles water so well") == "Kling"
    assert x_text.detect_model("made with flux.1 dev") == "Flux"
    assert x_text.detect_model("testing #sora tonight") == "Sora"
    assert x_text.detect_model("Grok Imagine does motion now") == "Grok Imagine"
    assert x_text.detect_model("nano banana is wild for edits") == "Nano Banana"


# ------------------------------------------------------------- parsing ------
def test_parse_captured_full_fixture(app_env):
    posts = XAdapter().parse_captured(captured())
    by_id = {p.platform_post_id: p for p in posts}
    # 1 photo + 1 video + reply + 2-photo tweet (2 posts) + low-eng + RT-inner
    # + quote-carrier = 8 media posts; text-only tweet skipped
    assert len(posts) == 8
    # newest-first ordering by tweet id
    assert posts[0].platform_post_id.startswith("1960000000000000007") or \
        int(str(posts[0].platform_post_id).split("-")[0]) >= \
        int(str(posts[-1].platform_post_id).split("-")[0])

    a = by_id["1960000000000000001"]
    assert a.media_url == "https://pbs.twimg.com/media/GXaaa111.jpg?name=orig"
    assert a.prompt.startswith("a lighthouse keeper wading")
    assert a.negative_prompt == "blurry, text"
    assert a.model_name == "Flux"
    assert a.author == "@auroraforge"
    assert a.source_url == "https://x.com/auroraforge/status/1960000000000000001"
    assert a.params["engagement"]["likes"] == 812
    assert a.params["prompt_confidence"] == "high"
    assert a.posted_at is not None and a.posted_at.year == 2025

    video = by_id["1960000000000000002"]
    assert video.media_type == "video"
    assert video.media_url.endswith("1280x720/high.mp4")  # top bitrate mp4
    assert video.model_name == "Kling"

    # multi-image tweet → two posts, ids tweet and tweet-1
    assert "1960000000000000004" in by_id and "1960000000000000004-1" in by_id
    assert by_id["1960000000000000004"].prompt.startswith("papercraft diorama")
    assert by_id["1960000000000000004"].model_name == "Midjourney"

    # retweet unwrapped to the ORIGINAL author + id
    rt = by_id["1959999999000000001"]
    assert rt.author == "@seedream_fan"
    assert rt.model_name == "Seedream"
    assert rt.prompt.startswith("vintage travel poster")

    # quote-carrier pulls the prompt from the quoted tweet
    q = by_id["1960000000000000007"]
    assert q.prompt.startswith("brutalist cathedral interior")
    assert q.params["prompt_confidence"] == "high"
    # photo url that already has a query keeps it untouched
    assert q.media_url == "https://pbs.twimg.com/media/GXggg777.jpg?format=jpg"

    # low-confidence fallback flagged
    low = by_id["1960000000000000005"]
    assert low.params["prompt_confidence"] == "low"
    assert low.model_name is None  # 'sparkling'/'influx' didn't false-match

    # reply detected
    assert by_id["1960000000000000003"].params["_is_reply"] is True


def test_scope_filters(app_env):
    adapter = XAdapter()
    posts = adapter.parse_captured(captured())
    with db_mod.session_scope() as s:
        # defaults: skip replies on → reply dropped
        out = adapter.apply_scope(s, posts)
        assert "1960000000000000003" not in {p.platform_post_id for p in out}
        # min engagement cuts the noise
        settings_store.put(s, "x_min_engagement", 100)
        out = adapter.apply_scope(s, posts)
        ids = {p.platform_post_id for p in out}
        assert "1960000000000000005" not in ids  # 2 likes
        assert "1960000000000000001" in ids      # 812 likes
        # media filter
        settings_store.put(s, "x_min_engagement", 0)
        settings_store.put(s, "x_media_filter", "videos")
        out = adapter.apply_scope(s, posts)
        assert all(p.media_type == "video" for p in out) and out
        # max per run
        settings_store.put(s, "x_media_filter", "both")
        settings_store.put(s, "x_max_per_run", 3)
        assert len(adapter.apply_scope(s, posts)) == 3


def test_wants_response():
    a = XAdapter()
    assert a.wants_response(
        "https://x.com/i/api/graphql/xYz123/SearchTimeline?variables=%7B%7D")
    assert a.wants_response(
        "https://x.com/i/api/graphql/qQq/UserMedia?vars=1")
    assert a.wants_response("https://api.x.com/1.1/search/adaptive.json?q=x")
    assert not a.wants_response("https://x.com/i/api/graphql/abc/DataSaverMode")
    assert not a.wants_response("https://abs.twimg.com/responsive-web/main.js")


def test_ingest_dedupes_by_tweet_id(app_env):
    """Same fixture ingested twice → all dupes second time (tweet-id keys)."""
    import httpx
    from promptforge.pipeline.ingest import ingest_batch
    from tests.test_ingest import png_bytes
    posts = XAdapter().parse_captured(captured())
    with db_mod.session_scope() as s:
        posts = XAdapter().apply_scope(s, posts)
    payload = png_bytes()
    client = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=payload)))
    # images only (mock payload is a PNG)
    posts = [p for p in posts if p.media_type == "image"]
    stats1 = ingest_batch("x", posts, client)
    assert stats1.new == len(posts) and stats1.errors == 0
    stats2 = ingest_batch("x", posts, client)
    assert stats2.new == 0 and stats2.duplicates == len(posts)


def test_low_confidence_excluded_from_knowledge(app_env):
    from promptforge.knowledge import engine, stats
    from promptforge.pipeline import hooks
    from tests.conftest import seed_post
    engine.register_hooks()
    try:
        high = seed_post(platform="x", model_family="flux",
                         prompt="golden hour rooftop garden, 35mm",
                         params={"prompt_confidence": "high"})
        low = seed_post(platform="x", model_family="flux",
                        prompt="random tweet chatter that is not a prompt",
                        params={"prompt_confidence": "low"})
        hooks.run_post_ingested(high)
        hooks.run_post_ingested(low)
        data = stats.load_stats("flux")
        assert data["count"] == 2                      # both counted as posts
        blob = json.dumps(data["terms"])
        assert "rooftop garden" in blob                # high-conf vocab kept
        assert "tweet chatter" not in blob             # low-conf vocab excluded
        # analysis batch also skips the low-confidence row but advances watermark
        with db_mod.session_scope() as s:
            settings_store.put(s, "llm_provider", "")
        engine.analyze_family("flux")
        assert stats.load_stats("flux")["last_analyzed_post_id"] >= low
    finally:
        hooks.clear()


def test_x_adapter_listed_needs_setup(client):
    r = client.get("/api/scrapers")
    x = next(s for s in r.json()["scrapers"] if s["name"] == "x")
    assert x["status"] == "needs_setup"
    assert x["session_status"] == "missing"
    assert "capture_login" in (x["status_detail"] or "")
