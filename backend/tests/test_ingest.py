"""Ingest pipeline tests (1.8): dedupe, download w/ same client, metadata
before compression, files under DATA_DIR, per-post failure isolation, runner
state recording."""
import io

import httpx
from PIL import Image

from promptforge import db as db_mod
from promptforge import fts
from promptforge.models import Post, ScraperState
from promptforge.pipeline import hooks
from promptforge.pipeline.ingest import ingest_batch
from promptforge.scrapers.base import ScrapedPost, SourceAdapter
from promptforge.scrapers import runner
from tests.test_media_metadata import make_a1111_png


def png_bytes(with_meta=False, tmp_path=None) -> bytes:
    if with_meta:
        f = tmp_path / "meta.png"
        make_a1111_png(f)
        return f.read_bytes()
    buf = io.BytesIO()
    Image.new("RGB", (320, 480), (90, 120, 20)).save(buf, "PNG")
    return buf.getvalue()


def make_client(payload: bytes) -> httpx.Client:
    def handler(request):
        return httpx.Response(200, content=payload)
    return httpx.Client(transport=httpx.MockTransport(handler))


def sp(pid: str, **kw) -> ScrapedPost:
    defaults = dict(platform="testsite", platform_post_id=pid,
                    media_url=f"https://cdn.test/{pid}.png",
                    prompt=f"prompt {pid}", model_name="flux.1-dev")
    defaults.update(kw)
    return ScrapedPost(**defaults)


def test_ingest_stores_compresses_and_indexes(app_env):
    client = make_client(png_bytes())
    stats = ingest_batch("testsite", [sp("p1")], client)
    assert stats.new == 1 and stats.errors == 0
    with db_mod.session_scope() as s:
        post = s.query(Post).one()
        assert post.model_family == "flux"
        assert post.media_path.endswith(".webp")
        assert (app_env.data_dir / post.media_path).exists()
        assert (app_env.data_dir / post.thumb_path).exists()
        assert post.media_width == 320 and post.media_height == 480
        assert post.params["_original_bytes"] > 0
        assert fts.search_posts(s, "prompt p1") == [post.id]


def test_ingest_dedupes(app_env):
    client = make_client(png_bytes())
    ingest_batch("testsite", [sp("dup")], client)
    stats = ingest_batch("testsite", [sp("dup")], client)
    assert stats.new == 0 and stats.duplicates == 1
    with db_mod.session_scope() as s:
        assert s.query(Post).count() == 1


def test_embedded_metadata_fills_missing_fields(app_env, tmp_path):
    """Adapter gave no prompt; PNG chunk provides it (extracted pre-compression)."""
    client = make_client(png_bytes(with_meta=True, tmp_path=tmp_path))
    stats = ingest_batch("testsite", [sp("m1", prompt=None, model_name=None)], client)
    assert stats.new == 1
    with db_mod.session_scope() as s:
        post = s.query(Post).one()
        assert post.prompt.startswith("masterpiece")
        assert post.negative_prompt == "lowres, bad anatomy"
        assert post.model_name == "dreamshaper_8"   # from embedded params
        assert post.params["seed"] == 1234567
        # stored file is webp — original PNG chunks are gone, proving pre-compression parse
        assert post.media_path.endswith(".webp")


def test_site_params_win_over_embedded(app_env, tmp_path):
    client = make_client(png_bytes(with_meta=True, tmp_path=tmp_path))
    stats = ingest_batch("testsite", [sp("m2", params={"seed": 999})], client)
    assert stats.new == 1
    with db_mod.session_scope() as s:
        post = s.query(Post).one()
        assert post.params["seed"] == 999
        assert post.prompt == "prompt m2"


def test_one_bad_post_never_blocks_batch(app_env):
    def handler(request):
        if "bad" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, content=png_bytes())
    client = httpx.Client(transport=httpx.MockTransport(handler))
    stats = ingest_batch("testsite", [sp("bad"), sp("good")], client)
    assert stats.errors == 1 and stats.new == 1
    assert "bad" in stats.error_messages[0]


def test_hooks_run_and_never_break_ingest(app_env):
    seen = []
    hooks.clear()
    hooks.register("ok", lambda pid: seen.append(pid))
    hooks.register("boom", lambda pid: 1 / 0)
    try:
        client = make_client(png_bytes())
        stats = ingest_batch("testsite", [sp("h1")], client)
        assert stats.new == 1 and seen
    finally:
        hooks.clear()


class FakeAdapter(SourceAdapter):
    name = "fake"
    label = "Fake"
    fail = False

    def make_client(self, s):
        payload = png_bytes()
        return httpx.Client(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=payload)))

    def fetch_recent(self, s, client, limit=100):
        if self.fail:
            raise RuntimeError("site exploded")
        return [sp("r1", platform="fake"), sp("r2", platform="fake")]


def test_runner_records_state(app_env, monkeypatch):
    fake = FakeAdapter()
    monkeypatch.setattr(runner, "get_adapter", lambda name: fake)
    stats = runner.run_scraper("fake", manual=True)
    assert stats.new == 2
    with db_mod.session_scope() as s:
        st = s.get(ScraperState, "fake")
        assert st.last_status == "ok" and st.last_new == 2 and st.last_run_at


def test_runner_survives_adapter_crash(app_env, monkeypatch):
    fake = FakeAdapter()
    fake.fail = True
    monkeypatch.setattr(runner, "get_adapter", lambda name: fake)
    runner.run_scraper("fake", manual=True)  # must not raise
    with db_mod.session_scope() as s:
        st = s.get(ScraperState, "fake")
        assert st.last_status == "error"
        assert "site exploded" in st.last_error
