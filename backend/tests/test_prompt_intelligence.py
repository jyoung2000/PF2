"""Inspiration 2.0 I11 — prompt intelligence end to end.

The ladder (§20/§122) has to survive the whole journey, not just the parser:
adapter → ingest → stored row → enrichment → analysis → search. These tests
pin the two absolutes: a weaker source NEVER overwrites a stronger one, and
PF2 NEVER presents text the creator did not publish as their prompt (§21).
"""
from __future__ import annotations

import io

import httpx
from PIL import Image

from promptforge import db as db_mod, settings_store
from promptforge.intel import enrichment
from promptforge.intel import prompt_parser as pp
from promptforge.intel import query as iquery
from promptforge.models import Post
from promptforge.pipeline.ingest import ingest_batch
from promptforge.scrapers.base import ScrapedPost
from promptforge.scrapers.social_base import SocialAdapter
from tests.conftest import seed_post


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 480), (40, 60, 90)).save(buf, "PNG")
    return buf.getvalue()


def client() -> httpx.Client:
    payload = png()
    return httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=payload)))


class _Src(SocialAdapter):
    """Minimal adapter: the shared parser is what builds its posts."""
    name = "testsocial"
    label = "Test Social"


def built(post_id: str, text: str, **kw) -> ScrapedPost:
    return _Src().build_post(platform="testsocial", post_id=post_id,
                             media_url=f"https://cdn.test/{post_id}.png",
                             media_type="image", text=text,
                             source_url=f"https://test/{post_id}", **kw)


def stored(post_id: str) -> Post | None:
    with db_mod.session_scope() as s:
        return s.query(Post).filter_by(platform="testsocial",
                                       platform_post_id=post_id).one_or_none()


# ---------------------------------------------------------------- ingest ---
def test_ladder_value_reaches_the_stored_row(app_env):
    """A labelled caption is `explicit_caption` on the column, on the
    assertion (as its coarse rank) and in the evidence — one journey."""
    stats = ingest_batch("testsocial", [built(
        "cap1", "new one!\n\nPrompt: a glass lighthouse at dusk, volumetric fog\n"
                "Negative: text, watermark\nSeed: 7 Steps: 24 — made with Flux")], client())
    assert stats.new == 1
    p = stored("cap1")
    assert p.prompt.startswith("a glass lighthouse at dusk")
    assert p.prompt_source == "explicit_caption"
    assert pp.coarse_source(p.prompt_source) == "extracted"
    assert p.assertions["prompt"]["source"] == "extracted"
    assert "explicit caption" in p.assertions["prompt"]["evidence"]
    assert p.assertions["prompt"]["confidence"] == pp.SOURCE_CONFIDENCE["explicit_caption"]
    assert p.negative_prompt == "text, watermark"
    assert p.params["seed"] == 7 and p.params["steps"] == 24
    assert p.params["prompt_fragments"][0]["location"] == "caption"


def test_prose_is_stored_as_inference_and_says_so(app_env):
    """§21/§118: prompt-shaped prose is kept, labelled, and never dressed up
    as something the creator published."""
    ingest_batch("testsocial", [built(
        "prose1", "shot this on a 35mm anamorphic, slow push in through rainy "
                  "Tokyo at night, neon reflections, shallow depth of field")], client())
    p = stored("prose1")
    assert p.prompt_source == "deterministic_inference"
    assert pp.coarse_source(p.prompt_source) == "extracted"
    assert p.assertions["prompt"]["confidence"] < 0.7
    assert not pp.is_explicit_source(p.prompt_source)
    assert any("not a labelled prompt" in n for n in p.params["prompt_notes"])


def test_no_prompt_means_no_prompt(app_env):
    """The absolute: nothing published, nothing invented (§21)."""
    ingest_batch("testsocial", [built("chat1", "wow this is amazing, follow me!")],
                 client())
    p = stored("chat1")
    assert p.prompt is None and p.prompt_source is None
    assert "prompt" not in (p.assertions or {})


def test_embedded_metadata_outranks_the_caption(app_env, tmp_path):
    """A PNG chunk beats what the creator typed — and the typed text is kept
    as an alternate, never dropped (§122/§52)."""
    from tests.test_media_metadata import make_a1111_png
    f = tmp_path / "meta.png"
    make_a1111_png(f)
    payload = f.read_bytes()
    c = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=payload)))
    ingest_batch("testsocial", [built("meta1", "Prompt: roughly what I typed")], c)
    p = stored("meta1")
    assert p.assertions["prompt"]["source"] == "metadata"
    assert pp.coarse_source(p.prompt_source) in ("metadata", "extracted")
    alts = [a["value"] for a in (p.assertions.get("_alternates") or {}).get("prompt", [])]
    assert any("roughly what I typed" in a for a in alts)


# ------------------------------------------------------------ enrichment ---
def test_thread_assembly_promotes_and_records_every_fragment(app_env):
    """A prompt split across the creator's own replies is reconstructed,
    labelled `assembled`, and each published part is kept with its ref."""
    pid = seed_post(platform="testsocial", platform_post_id="thr1",
                    prompt="kling test — prompt in the comments!",
                    prompt_source="deterministic_inference",
                    model_name=None, model_family=None, author="mara",
                    observed={"text": {"body": "kling test — prompt in the comments!"}},
                    assertions={"prompt": {"value": "kling test — prompt in the comments!",
                                           "source": "extracted", "confidence": 0.4,
                                           "evidence": "loose prose"}},
                    params={"prompt_source": "deterministic_inference"})
    with db_mod.session_scope() as s:
        post = s.get(Post, pid)
        enrichment._apply_comment_evidence(post, [
            {"id": "c1", "author": "mara", "text": "Prompt: a lone figure in a neon alley",
             "by_author": True},
            {"id": "c2", "author": "mara", "text": "Prompt: ...35mm anamorphic, volumetric fog "
                                                   "— shot on Kling 2.5", "by_author": True},
            {"id": "c3", "author": "someone", "text": "Prompt: I reckon it was Sora",
             "by_author": False}])
    p = stored("thr1")
    assert p.prompt_source == "assembled"
    assert "neon alley" in p.prompt and "anamorphic" in p.prompt
    assert "Sora" not in p.prompt              # a stranger cannot supply the prompt
    refs = [f["ref"] for f in p.params["prompt_fragments"] if f["author_is_creator"]]
    assert refs == ["c1", "c2"]
    assert "author's reply thread" in p.assertions["prompt"]["evidence"]
    assert p.model_name == "Kling"


def test_enrichment_never_downgrades_a_stronger_source(app_env):
    """§122: a comment cannot overwrite an embedded-metadata prompt."""
    pid = seed_post(platform="testsocial", platform_post_id="strong1",
                    prompt="exact prompt from the PNG chunk",
                    prompt_source="embedded_metadata", author="mara",
                    observed={"text": {"body": "here it is"}},
                    assertions={"prompt": {"value": "exact prompt from the PNG chunk",
                                           "source": "metadata", "confidence": 1.0,
                                           "evidence": "embedded generation metadata"}},
                    params={"prompt_source": "embedded_metadata"})
    with db_mod.session_scope() as s:
        enrichment._apply_comment_evidence(s.get(Post, pid), [
            {"id": "c1", "author": "mara", "text": "Prompt: something else entirely",
             "by_author": True}])
    p = stored("strong1")
    assert p.prompt == "exact prompt from the PNG chunk"
    assert p.prompt_source == "embedded_metadata"
    assert p.assertions["_alternates"]["prompt"][0]["value"] == "something else entirely"


def test_comment_cap_is_a_setting_and_author_replies_rank_first(app_env):
    with db_mod.session_scope() as s:
        settings_store.put(s, "research_max_comments", 3)
    comments = [{"id": f"c{i}", "author": "fan", "text": "nice one", "likes": i}
                for i in range(10)]
    comments.append({"id": "cx", "author": "mara", "text": "Prompt: the real one", "likes": 0})
    ranked = enrichment.prioritize_comments(comments, "mara")
    assert len(ranked) == 3
    assert ranked[0]["id"] == "cx" and ranked[0]["by_author"] is True


# ---------------------------------------------------------------- search ---
def test_prompt_source_qualifier_matches_both_vocabularies(app_env):
    explicit = seed_post(platform="testsocial", prompt="a fox",
                         prompt_source="explicit_caption")
    guessed = seed_post(platform="testsocial", prompt="a fox",
                        prompt_source="ai_inference")
    legacy = seed_post(platform="testsocial", prompt="a fox", prompt_source="ai")
    from sqlalchemy import select

    def ids(q: str) -> set[int]:
        pq = iquery.parse(q)
        with db_mod.session_scope() as s:
            stmt = iquery.apply_filters(select(Post), pq)
            return {p.id for p in s.execute(stmt).scalars()}

    assert ids("prompt_source:explicit") == {explicit}
    assert ids("prompt_source:ai") == {guessed, legacy}       # legacy rows still match
    assert ids("prompt_source:ai_inference") == {guessed}
    assert iquery.parse("prompt_source:nonsense").ignored == ["prompt_source:nonsense"]


def test_ai_written_prompts_never_become_model_exemplars(app_env):
    """§21/§93: `best_for_model` teaches the knowledge engine — an LLM's words
    are not evidence, in either vocabulary."""
    from promptforge.intel import similar
    good = seed_post(platform="testsocial", model_family="kling", prompt="a real prompt",
                     prompt_source="explicit_caption", inspiration_score=90,
                     assertions={"prompt": {"value": "a real prompt", "source": "extracted",
                                            "confidence": 0.95}})
    seed_post(platform="testsocial", model_family="kling", prompt="an llm guess",
              prompt_source="ai_inference", inspiration_score=99,
              assertions={"prompt": {"value": "an llm guess", "source": "ai",
                                     "confidence": 0.9}})
    seed_post(platform="testsocial", model_family="kling", prompt="a legacy llm guess",
              prompt_source="ai", inspiration_score=99,
              assertions={"prompt": {"value": "a legacy llm guess", "source": "ai",
                                     "confidence": 0.9}})
    with db_mod.session_scope() as s:
        assert similar.best_for_model(s, "kling") == [good]
