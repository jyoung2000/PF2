"""Inspiration 2.0 I9: the shared prompt parser and the new Grok-free social
sources (Reddit, Bluesky, YouTube) — all parsed from saved fixtures, no live
HTTP, no browser, no LLM."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from promptforge.db import session_scope
from promptforge.intel import prompt_parser as pp
from promptforge.scrapers import all_adapters, get_adapter
from promptforge.scrapers.social_base import capability_report

FIX = Path(__file__).parent / "fixtures" / "social"


def load(name: str):
    text = (FIX / name).read_text()
    return json.loads(text) if name.endswith(".json") else text


# ------------------------------------------------------------- the parser ---
def test_labelled_prompt_beats_everything():
    r = pp.parse("check this out\n\nPrompt: a fox in a paper boat, watercolor, "
                 "soft light\nNegative: text, watermark\nSeed: 42 Steps: 30 CFG: 7.5")
    assert r.prompt.startswith("a fox in a paper boat")
    assert r.negative == "text, watermark"
    assert r.prompt_source == "explicit_caption" and r.is_explicit
    assert r.method == "labelled" and r.confidence >= 0.9
    assert r.params["seed"] == 42 and r.params["steps"] == 30 and r.params["cfg_scale"] == 7.5
    assert r.fragments[0].location == "caption"


def test_loose_prose_is_scored_never_promoted():
    """§118/§21: prompt-shaped prose is a low-confidence candidate, and it is
    never labelled as the published prompt."""
    r = pp.parse("Used a 35mm anamorphic look, slow push in, rainy Tokyo at night, "
                 "neon reflections, shallow depth of field, cinematic grade")
    assert r.prompt and r.prompt_source == "deterministic_inference"
    assert not r.is_explicit and r.confidence < 0.7
    assert any("not a labelled prompt" in n for n in r.notes)
    # chatter is not a prompt at all
    chat = pp.parse("wow this is amazing, check the thread and follow me!")
    assert chat.prompt is None and chat.prompt_source == "unknown"


def test_source_precedence_never_downgrades():
    assert pp.stronger_source("embedded_metadata", "explicit_caption")
    assert pp.stronger_source("explicit_caption", "ai_extraction")
    assert not pp.stronger_source("ai_inference", "assembled")
    assert not pp.stronger_source("deterministic_inference", "explicit_comment")


def test_metadata_wins_over_text_but_keeps_the_evidence():
    out = pp.extract_prompt(
        {"text": "Prompt: what I typed roughly",
         "metadata": {"prompt": "exact prompt from the PNG chunk", "seed": 99}},
        {"platform": "civitai"})
    assert out.prompt == "exact prompt from the PNG chunk"
    assert out.prompt_source == "embedded_metadata" and out.confidence == 1.0
    texts = [f.text for f in out.fragments]
    assert "exact prompt from the PNG chunk" in texts
    assert any("what I typed roughly" in t for t in texts)   # not discarded
    assert out.params["seed"] == 99


def test_thread_assembly_records_every_fragment():
    """§22/§92: a prompt split across the post and the creator's replies is
    reconstructed, labelled `assembled`, and keeps its parts."""
    out = pp.parse_thread(
        "Prompt: a lone figure in a neon alley",
        [{"id": "c1", "author": "mara", "text": "Negative: text, watermark"},
         {"id": "c2", "author": "mara", "text": "Prompt: ...35mm anamorphic, volumetric fog"},
         {"id": "c3", "author": "fan", "text": "Prompt: I think it was Sora"}],
        creator="mara")
    assert out.prompt_source == "assembled"
    assert "neon alley" in out.prompt and "anamorphic" in out.prompt
    assert "Sora" not in (out.prompt or "")      # a stranger cannot supply the prompt
    assert out.negative == "text, watermark"
    creator_frags = [f for f in out.fragments if f.author_is_creator]
    assert len(creator_frags) >= 1 and all(f.ref for f in creator_frags)
    assert any("reconstructed" in n for n in out.notes)


def test_prompt_in_comments_pointer_and_creator_reply_promotion():
    out = pp.parse_thread("kling test — prompt in the comments!",
                          [{"id": "c1", "author": "kenji",
                            "text": "Prompt: slow dolly through a rainy alley"}],
                          creator="kenji")
    assert out.wants_comments is True
    assert out.prompt == "slow dolly through a rainy alley"
    assert out.prompt_source == "explicit_thread"   # the creator's own reply
    assert any("creator's own reply" in n for n in out.notes)


def test_components_and_model_vocabulary():
    r = pp.parse("Prompt: wide shot, 85mm, golden hour, slow dolly in, rule of thirds "
                 "— made with Kling 2.5 --ar 16:9")
    assert r.model_name == "Kling" and r.model_family == "kling"
    assert 85 in r.components["camera"]["lens_mm"]
    assert "golden hour" in r.components["lighting"]
    assert any("dolly" in m for m in r.components["motion"])
    assert r.params["mj_flags"]["ar"] == "16:9"


# ------------------------------------------------------------------ reddit --
def test_reddit_listing_parse(app_env):
    a = get_adapter("reddit")
    posts = a.parse_listing(load("reddit_listing.json"))
    assert [p.platform_post_id for p in posts] == ["abc123", "vid001", "gal001"]  # text post skipped
    first = posts[0]
    assert first.prompt.startswith("neon-drenched alley")
    assert first.negative_prompt == "text, watermark"
    assert first.model_name == "Flux"
    assert first.params["prompt_source"] == "explicit_caption"
    assert first.params["seed"] == 12345 and first.params["steps"] == 30
    assert first.observed["engagement"]["likes"] == 412
    assert first.observed["relations"]["subreddit"] == "StableDiffusion"
    assert first.source_url.endswith("/r/StableDiffusion/comments/abc123/neon/")
    video = posts[1]
    assert video.media_type == "video" and video.media_url.endswith(".mp4")
    assert video.params.get("wants_comments") is True     # "prompt in the comments!"
    gallery = posts[2]
    assert gallery.media_url.startswith("https://preview.redd.it/aaa.jpg?width=1080&crop")


def test_reddit_comment_thread_yields_creator_prompt(app_env):
    a = get_adapter("reddit")
    rows = a.parse_comments(load("reddit_comments.json"), author="kenji")
    assert rows[0]["is_creator"] and "slow dolly" in rows[0]["text"]
    assert any(r["author"] == "randomuser" for r in rows)
    out = pp.parse_thread("kling test", rows, creator="kenji")
    assert out.prompt.startswith("slow dolly in through rainy tokyo")
    assert out.prompt_source in ("explicit_thread", "assembled")
    assert out.model_name == "Kling"


def test_reddit_search_and_author_through_mock_transport(app_env):
    a = get_adapter("reddit")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=load("reddit_listing.json"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with session_scope() as s:
        posts = a.search(s, client, "veo prompt", limit=10, period="week")
        assert "search.json" in seen["url"] and "veo+prompt" in seen["url"].replace("%20", "+")
        assert len(posts) == 3
        a.fetch_author(s, client, "mara_makes")
        assert "/user/mara_makes/submitted.json" in seen["url"]
        a.fetch_recent(s, client, limit=5)
        assert "/new.json" in seen["url"]


# ----------------------------------------------------------------- bluesky --
def test_bluesky_search_parse(app_env):
    a = get_adapter("bluesky")
    posts = a.parse_search(load("bluesky_search.json"))
    assert len(posts) == 2                     # the text-only post has no media
    img = posts[0]
    assert img.media_url.endswith("aaa.jpg") and img.media_type == "image"
    assert img.author == "mara.bsky.social"
    assert img.model_name == "Flux"
    assert img.prompt.startswith("neon-drenched alley")
    assert img.params["prompt_source"] == "explicit_caption"
    assert img.observed["engagement"]["likes"] == 120
    assert img.source_url == "https://bsky.app/profile/mara.bsky.social/post/3kabc"
    vid = posts[1]
    assert vid.media_type == "video" and vid.media_url.endswith(".m3u8")


def test_bluesky_thread_prompt(app_env):
    a = get_adapter("bluesky")
    rows = a.parse_thread(load("bluesky_thread.json"), author="kenji.bsky.social")
    assert rows[0]["is_creator"] and "slow dolly" in rows[0]["text"]
    out = pp.parse_thread("kling test, prompt in thread", rows, creator="kenji.bsky.social")
    assert out.prompt.startswith("slow dolly through a rainy tokyo alley")


def test_bluesky_needs_no_credentials(app_env):
    a = get_adapter("bluesky")
    with session_scope() as s:
        assert a.is_configured(s) and a.needs_setup_reason(s) is None
    assert a.tier == 0 and a.auth_kind == "none"
    assert capability_report(a)["how_it_works"].startswith("Public API")


# ----------------------------------------------------------------- youtube --
def test_youtube_search_and_description_mining(app_env):
    a = get_adapter("youtube")
    posts = a.parse_search(load("youtube_search.html"))
    assert [p.platform_post_id for p in posts] == ["vid_abc", "vid_def"]
    assert posts[0].author == "PromptLab"
    assert posts[0].observed["engagement"]["views"] == 12345
    assert posts[0].media_url.endswith("hq.jpg")
    assert posts[0].params["media_note"].startswith("thumbnail stored")
    detail = a.parse_watch(load("youtube_watch.html"))
    assert detail["description"].startswith("Full prompt:")
    assert detail["duration_s"] == 511 and detail["views"] == 12345


def test_youtube_search_pulls_descriptions(app_env):
    a = get_adapter("youtube")

    def handler(request: httpx.Request) -> httpx.Response:
        if "results" in request.url.path:
            return httpx.Response(200, text=load("youtube_search.html"))
        return httpx.Response(200, text=load("youtube_watch.html"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with session_scope() as s:
        posts = a.search(s, client, "veo prompt", limit=5, with_descriptions=1)
    assert posts[0].prompt.startswith("a lone figure walks a neon-lit alley")
    assert posts[0].params["prompt_source"] == "explicit_caption"
    assert posts[0].negative_prompt == "text, watermark"
    assert posts[0].model_name == "Veo"


def test_youtube_degrades_on_shape_change(app_env):
    a = get_adapter("youtube")
    assert a.parse_search("<html><body>nothing here</body></html>") == []
    assert a.parse_watch("<html></html>")["description"] is None
    assert a.experimental is True


# ------------------------------------------------------------- the registry --
def test_registry_declares_sources_truthfully(app_env):
    adapters = all_adapters()
    assert {"reddit", "bluesky", "youtube", "x", "civitai", "tiktok"} <= set(adapters)
    # every capability an adapter claims must be a known one (§14)
    from promptforge.scrapers.social_base import ALL_CAPABILITIES
    legacy = {"browser_session", "related", "metadata", "detail", "search",
              "author", "comments", "thread", "video", "api"}
    for name, a in adapters.items():
        unknown = set(a.capabilities) - ALL_CAPABILITIES - legacy
        assert not unknown, f"{name} claims unknown capabilities {unknown}"
    # browser-only sites are honest about needing setup before a workflow exists
    with session_scope() as s:
        tiktok = adapters["tiktok"]
        assert not tiktok.is_configured(s)
        assert "workflow" in tiktok.needs_setup_reason(s).lower()
        assert adapters["reddit"].is_configured(s)


def test_browser_sites_never_crash_without_engines(app_env):
    """A browser social source with no workflow and no AI engine logs and
    returns nothing — it never breaks the run (§128/§188)."""
    a = get_adapter("tiktok")
    with session_scope() as s:
        assert a.fetch_recent(s, httpx.Client(), limit=5) == []
