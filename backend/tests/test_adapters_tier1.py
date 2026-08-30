"""Civitai + Lexica adapter parser tests against saved fixture JSON (1.9, 1.10)."""
import json
from pathlib import Path

import httpx

from promptforge import db as db_mod
from promptforge import settings_store
from promptforge.scrapers.civitai import CivitaiAdapter, parse_item
from promptforge.scrapers.lexica import LexicaAdapter, parse_image

FIXTURES = Path(__file__).parent / "fixtures"
CIVITAI = json.loads((FIXTURES / "civitai_images.json").read_text())
LEXICA = json.loads((FIXTURES / "lexica_search.json").read_text())


def test_civitai_parse_full_meta():
    sp = parse_item(CIVITAI["items"][0])
    assert sp.platform == "civitai"
    assert sp.platform_post_id == "91001001"
    assert sp.prompt.startswith("cinematic portrait")
    assert sp.negative_prompt == "blurry, deformed hands, watermark"
    assert sp.model_name == "flux.1-dev"
    assert sp.params["seed"] == 3407221156
    assert sp.params["steps"] == 30
    assert sp.params["sampler"] == "Euler a"
    assert sp.params["cfg_scale"] == 3.5
    assert sp.params["size"] == "1024x1536"
    assert sp.params["clip_skip"] == 2
    assert sp.params["loras"] == ["FilmGrainFlux"]
    assert sp.media_type == "image"
    assert sp.author == "auroraforge"
    assert sp.source_url == "https://civitai.com/images/91001001"
    assert sp.posted_at is not None and sp.posted_at.year == 2026
    assert sp.nsfw is False


def test_civitai_parse_video_item():
    sp = parse_item(CIVITAI["items"][1])
    assert sp.media_type == "video"
    assert sp.model_name == "Wan Video 2.2"  # baseModel fallback when meta has no Model
    assert sp.prompt.startswith("FPV drone")


def test_civitai_null_meta_skipped_by_default():
    assert parse_item(CIVITAI["items"][2]) is None
    sp = parse_item(CIVITAI["items"][2], keep_metaless=True)
    assert sp is not None and sp.prompt is None and sp.nsfw is True  # nsfwLevel 4


def test_civitai_fetch_pagination(app_env):
    """Two pages via cursor; Bearer header sent when key configured."""
    page2 = {"items": [dict(CIVITAI["items"][0], id=91001099)],
             "metadata": {}}
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("Authorization")))
        if "cursor" in str(request.url):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=CIVITAI)

    with db_mod.session_scope() as s:
        settings_store.put(s, "civitai_api_key", "civi-key-123")

    adapter = CivitaiAdapter()
    with db_mod.session_scope() as s:
        real = adapter.make_client(s)
        real.close()
        client = httpx.Client(headers=real.headers,
                              transport=httpx.MockTransport(handler))
        posts = adapter.fetch_recent(s, client, limit=3)
    assert len(posts) == 3
    assert seen[0][1] == "Bearer civi-key-123"
    assert "cursor=" in seen[1][0]
    ids = [p.platform_post_id for p in posts]
    assert ids == ["91001001", "91001002", "91001099"]


def test_lexica_parse():
    sp = parse_image(LEXICA["images"][0])
    assert sp.platform == "lexica"
    assert sp.prompt.startswith("isometric cutaway")
    assert sp.model_name == "lexica-aperture-v3.5"
    assert sp.params["seed"] == "2905871142"
    assert sp.params["size"] == "768x1152"
    assert "lexica.art/prompt/" in sp.source_url
    assert parse_image(LEXICA["images"][2]) is None  # no src → skip


def test_lexica_term_rotation_and_fetch(app_env):
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=LEXICA)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = LexicaAdapter()
    with db_mod.session_scope() as s:
        settings_store.put(s, "lexica_search_terms", "term one, term two")
        posts = adapter.fetch_recent(s, client, limit=10)
        assert len(posts) == 2
    with db_mod.session_scope() as s:
        adapter.fetch_recent(s, client, limit=10)
    assert calls[0]["q"] == "term one"
    assert calls[1]["q"] == "term two"


def test_lexica_needs_setup_without_terms(app_env):
    adapter = LexicaAdapter()
    with db_mod.session_scope() as s:
        settings_store.put(s, "lexica_search_terms", "")
        assert adapter.is_configured(s) is False
        assert "Settings" in adapter.needs_setup_reason(s)
        assert adapter.health(s)["status"] == "needs_setup"
