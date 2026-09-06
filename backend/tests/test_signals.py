"""Inspiration 2.0 I14 — cross-source trends and ranking.

Statistical tests on seeded data. Nothing here may need an AI provider, and
no number may be invented: a signal PF2 cannot observe is reported as absent,
never estimated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from promptforge import db as db_mod
from promptforge.intel import signals
from promptforge.main import create_app
from promptforge.models import Creator, EngagementSnapshot
from tests.conftest import seed_post

NOW = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)


def weeks_ago(n: float) -> datetime:
    return NOW - timedelta(weeks=n)


def post(platform="x", when: float = 0.5, **kw):
    kw.setdefault("posted_at", weeks_ago(when))
    kw.setdefault("scraped_at", weeks_ago(when))
    return seed_post(platform=platform, **kw)


# ------------------------------------------------------------- velocity ----
def test_velocity_measures_growth_and_acceleration():
    assert signals.velocity([0, 0, 1, 1, 4, 6])["direction"] == "rising"
    assert signals.velocity([6, 5, 5, 4, 1, 0])["direction"] == "falling"
    assert signals.velocity([3, 3, 3, 3, 3, 3])["direction"] == "steady"
    # up on the window but the growth itself is slowing → "cooling", not "rising"
    cooling = signals.velocity([1, 1, 2, 8, 9, 9])
    assert cooling["velocity"] >= 1.5 and cooling["acceleration"] < 0
    assert cooling["direction"] == "cooling"


def test_velocity_is_honest_about_thin_history():
    out = signals.velocity([2, 5])
    assert out["direction"] == "unknown" and "not enough history" in out["detail"]


def test_velocity_does_not_report_infinite_growth():
    """0 → 3 is real, but calling it infinite would drown everything else."""
    assert signals.velocity([0, 0, 0, 0, 1, 2])["velocity"] < 5


# ------------------------------------------------------- platform spread ---
def test_a_signal_on_many_platforms_outranks_a_bigger_single_platform_one(app_env):
    for _ in range(12):                       # loud, but only on one platform
        post("civitai", 0.4, prompt=None, model_family="loud", model_name="Loud",
             model_source="explicit")
    for platform in ("x", "reddit", "bluesky", "youtube"):
        post(platform, 0.4, prompt=None, model_family="wide", model_name="Wide",
             model_source="explicit")
    with db_mod.session_scope() as s:
        out = signals.cross_platform_signals(s, weeks=8, now=NOW)
    models = [r for r in out["signals"] if r["kind"] == "model"]
    top = models[0]
    assert top["key"] == "wide" and top["platform_count"] == 4
    assert "4 platforms" in top["why"]
    loud = next(r for r in models if r["key"] == "loud")
    assert loud["total"] == 12 and loud["platform_count"] == 1
    # ranked by reach first: 4 posts on 4 platforms beat 12 on one
    assert models.index(top) < models.index(loud)
    assert out["cross_platform_count"] == 1


def test_inferred_models_never_become_a_signal(app_env):
    """§93: a model an AI guessed is not evidence of a trend."""
    for platform in ("x", "reddit", "bluesky"):
        post(platform, 0.4, prompt=None, model_family="guessed", model_name="Guessed",
             model_source="ai")
    with db_mod.session_scope() as s:
        out = signals.cross_platform_signals(s, weeks=8, now=NOW)
    assert not [r for r in out["signals"] if r["key"] == "guessed"]


def test_rare_signals_are_not_reported(app_env):
    post("x", 0.4, prompt=None, model_family="onceoff", model_name="Once",
         model_source="explicit")
    with db_mod.session_scope() as s:
        assert signals.cross_platform_signals(s, weeks=8, now=NOW)["signals"] == []


# -------------------------------------------------------- prompt patterns --
def test_prompt_patterns_need_published_prompts(app_env):
    pair = "neon alley, volumetric fog"
    for platform in ("x", "reddit", "bluesky", "civitai"):
        post(platform, 0.5, prompt=f"{pair}, 35mm anamorphic",
             prompt_source="explicit_caption",
             assertions={"prompt": {"value": pair, "source": "extracted",
                                    "confidence": 0.95}})
    # a corpus with other work in it, so "these travel together" is a real
    # measurement and not an artefact of every prompt being identical
    for i in range(8):
        post("x", 0.5, prompt=f"sunny meadow, wildflowers, soft focus {i}",
             prompt_source="explicit_caption", assertions={})
    for i in range(2):                       # one phrase without the other
        post("reddit", 0.5, prompt=f"neon alley, midday sun {i}",
             prompt_source="explicit_caption", assertions={})
    # the same phrases, but the prompt was written by an AI → excluded (§21)
    for _ in range(4):
        post("x", 0.5, prompt=f"{pair}, 35mm anamorphic", prompt_source="ai_inference",
             assertions={"prompt": {"value": "x", "source": "ai", "confidence": 0.9}})
    with db_mod.session_scope() as s:
        out = signals.prompt_patterns(s, weeks=12, now=NOW, min_support=3)
    assert out["prompts_considered"] == 14         # AI prompts never counted
    trio = {"neon alley", "volumetric fog", "35mm anamorphic"}
    top = out["patterns"][0]
    assert set(top["phrases"]) < trio                # a pair out of the recurring trio
    assert top["platform_count"] == 4 and top["posts"] == 4
    assert top["lift"] > 1.2 and top["notable"] and "more often than chance" in top["why"]
    # all three pairings of the trio are mined, each spanning the 4 platforms
    cross = [r for r in out["patterns"] if set(r["phrases"]) < trio]
    assert len(cross) == 3 and all(r["platform_count"] == 4 for r in cross)
    assert out["notable"] >= 3 and "excluded" in out["basis"]


def test_a_pattern_seen_twice_is_a_coincidence(app_env):
    for _ in range(2):
        post("x", 0.5, prompt="lonely lighthouse, storm light",
             prompt_source="explicit_caption", assertions={})
    with db_mod.session_scope() as s:
        assert signals.prompt_patterns(s, now=NOW)["patterns"] == []


# ---------------------------------------------------- engagement growth ----
def test_growth_comes_from_repeat_observations_only(app_env):
    fast = post("x", 1.0, engagement_total=100)
    slow = post("x", 1.0, engagement_total=100)
    once = post("x", 1.0, engagement_total=9999)
    with db_mod.session_scope() as s:
        s.add_all([
            EngagementSnapshot(post_id=fast, at=NOW - timedelta(hours=24), likes=100),
            EngagementSnapshot(post_id=fast, at=NOW, likes=1300),
            EngagementSnapshot(post_id=slow, at=NOW - timedelta(days=30), likes=100),
            EngagementSnapshot(post_id=slow, at=NOW, likes=1300),
            EngagementSnapshot(post_id=once, at=NOW, likes=9999),
        ])
    with db_mod.session_scope() as s:
        out = signals.engagement_growth(s, now=NOW)
    ids = [r["post_id"] for r in out["growing"]]
    assert ids[0] == fast and slow in ids
    assert once not in ids                       # seen once ⇒ no growth rate
    assert out["growing"][0]["gain"] == 1200
    assert out["posts_with_history"] == 2 and out["posts_seen_once"] == 1
    assert "never estimated" in out["note"]


# -------------------------------------------------------- discovery modes --
def test_every_mode_explains_every_result(app_env):
    gem = post("x", 0.3, inspiration_score=88, engagement_total=4,
               prompt="a quiet lighthouse at dawn, 35mm", prompt_source="explicit_caption")
    popular = post("x", 0.3, inspiration_score=40, engagement_total=90_000)
    flow = post("civitai", 0.3, inspiration_score=70, has_workflow=True)
    with db_mod.session_scope() as s:
        for mode in signals.MODES:
            out = signals.discover(s, mode=mode, now=NOW)
            assert out["mode"] == mode and out["detail"]
            for row in out["results"]:
                assert row["why"], f"{mode} produced a result with no reason"
        assert signals.discover(s, "hidden_gems", now=NOW)["results"][0]["post_id"] == gem
        assert [r["post_id"] for r in signals.discover(s, "workflows", now=NOW)["results"]] == [flow]
        assert signals.discover(s, "trending", now=NOW)["results"][0]["post_id"] == popular
        best = signals.discover(s, "best_prompts", now=NOW)["results"]
        assert [r["post_id"] for r in best] == [gem]     # only published prompts


def test_ai_written_prompts_are_labelled_not_hidden(app_env):
    guessed = post("x", 0.3, inspiration_score=95, engagement_total=10,
                   prompt="an llm's guess", prompt_source="ai_inference")
    with db_mod.session_scope() as s:
        rows = signals.discover(s, "hidden_gems", now=NOW)["results"]
    row = next(r for r in rows if r["post_id"] == guessed)
    assert any("written by an AI" in w for w in row["why"])


def test_query_relevance_outranks_the_shelf_signal(app_env):
    loud = post("x", 0.3, inspiration_score=95, engagement_total=99_999,
                prompt=None, model_name=None, model_family=None)
    on_topic = post("x", 0.3, inspiration_score=20, engagement_total=3,
                    prompt="slow dolly through a rainy alley, volumetric fog",
                    prompt_source="explicit_caption", model_name="Kling",
                    model_family="kling", params={"prompt_source": "explicit_caption"})
    with db_mod.session_scope() as s:
        plain = signals.discover(s, "trending", now=NOW)["results"]
        asked = signals.discover(s, "trending", query="kling prompt", now=NOW)
    assert plain[0]["post_id"] == loud
    assert asked["results"][0]["post_id"] == on_topic
    assert asked["results"][0]["relevance"] > 0.4
    assert "query relevance" in asked["ranked_by"]
    assert loud not in [r["post_id"] for r in asked["results"]]   # not an answer


def test_cross_platform_mode_only_shows_travelling_signals(app_env):
    for platform in ("x", "reddit", "bluesky"):
        post(platform, 0.4, model_family="wide", model_name="Wide",
             model_source="explicit", inspiration_score=60)
    local = post("civitai", 0.4, model_family="local", model_name="Local",
                 model_source="explicit", inspiration_score=99)
    with db_mod.session_scope() as s:
        rows = signals.discover(s, "cross_platform", now=NOW)["results"]
    assert rows and local not in [r["post_id"] for r in rows]
    assert all("3 platforms" in " ".join(r["why"]) for r in rows)


# --------------------------------------------------------------------- API --
def test_signal_api_needs_no_ai_provider(app_env):
    recent = datetime.now(timezone.utc) - timedelta(days=3)
    for platform in ("x", "reddit", "bluesky"):
        seed_post(platform=platform, posted_at=recent, scraped_at=recent,
                  model_family="wide", model_name="Wide", model_source="explicit",
                  prompt="neon alley, volumetric fog", prompt_source="explicit_caption",
                  assertions={})
    client = TestClient(create_app())
    sig = client.get("/api/inspiration/analytics/signals").json()
    assert sig["signals"][0]["platform_count"] == 3
    assert client.get("/api/inspiration/analytics/patterns").json()["patterns"]
    growth = client.get("/api/inspiration/analytics/growth").json()
    assert growth["growing"] == [] and "never estimated" in growth["note"]
    summary = client.get("/api/inspiration/analytics/signals/summary").json()
    assert summary["requires_ai"] is False
    shelf = client.get("/api/inspiration/discover?mode=best_prompts").json()
    assert shelf["items"] and all(item["why"] for item in shelf["items"])
    assert client.get("/api/inspiration/discover?mode=nonsense").json()["mode"] == "trending"
