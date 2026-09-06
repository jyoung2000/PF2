"""Highlight ranking + overlap suppression (Phase 2, concept from
AI-Youtube-Shorts-Generator) and 9:16 reframing in the clip node."""
from promptforge.forge import highlights


def test_segments_from_cuts_respects_length_bounds():
    segs = highlights.segments_from_cuts([10.0, 12.0, 40.0], duration=60.0, max_clip_s=15)
    assert all(s["duration_s"] >= highlights.MIN_S for s in segs)
    assert all(s["duration_s"] <= 15.0 + 1e-6 for s in segs)
    assert segs[0]["start_s"] == 0.0
    # the 10→12s gap is too short to be a candidate
    assert not any(abs(s["start_s"] - 10.0) < 0.01 and s["duration_s"] < 3 for s in segs)


def test_scoring_prefers_target_length_and_whole_scenes():
    near = {"start_s": 0, "end_s": 15, "duration_s": 15, "scene_bounded": True}
    short = {"start_s": 20, "end_s": 25, "duration_s": 5, "scene_bounded": True}
    mid = {"start_s": 40, "end_s": 55, "duration_s": 15, "scene_bounded": False}
    ranked = highlights.score_segments([short, mid, near])
    assert ranked[0]["start_s"] == 0            # closest to target and whole
    assert ranked[0]["score"] > ranked[-1]["score"]
    assert "scene-bounded" in ranked[0]["reason"]


def test_overlap_suppression_avoids_three_cuts_of_one_moment():
    overlapping = [
        {"start_s": 0, "end_s": 15, "duration_s": 15, "score": 99},
        {"start_s": 1, "end_s": 16, "duration_s": 15, "score": 98},   # ~93% overlap
        {"start_s": 2, "end_s": 17, "duration_s": 15, "score": 97},
        {"start_s": 60, "end_s": 75, "duration_s": 15, "score": 50},
    ]
    kept = highlights.suppress_overlaps(overlapping, count=3)
    assert [k["start_s"] for k in kept] == [0, 60]     # the clones are dropped
    # a small overlap is tolerated
    kept2 = highlights.suppress_overlaps(
        [{"start_s": 0, "end_s": 15, "duration_s": 15, "score": 90},
         {"start_s": 13, "end_s": 28, "duration_s": 15, "score": 80}], count=2)
    assert len(kept2) == 2


def test_pick_is_deterministic_without_an_llm():
    out = highlights.pick([10.0, 30.0, 50.0], duration=70.0, count=2)
    assert out["basis"] == "structure" and out["note"] is None
    assert len(out["highlights"]) == 2
    assert out == highlights.pick([10.0, 30.0, 50.0], duration=70.0, count=2)


def test_llm_refinement_falls_back_honestly(app_env):
    out = highlights.pick([10.0, 30.0], duration=45.0, count=2,
                          transcript="", use_llm=True)
    assert out["basis"] == "structure" and "no transcript" in out["note"]
    out2 = highlights.pick([10.0, 30.0], duration=45.0, count=2,
                           transcript="some words here", use_llm=True)
    assert out2["basis"] == "structure" and "unavailable" in out2["note"]
    assert out2["highlights"]                      # still produced picks


def test_short_sources_fall_back_to_an_even_split_not_zero_clips():
    out = highlights.pick([1.0, 2.0], duration=3.0, count=3, max_clip_s=15)
    assert out["basis"] == "even-split" and "minimum highlight length" in out["note"]
    assert len(out["highlights"]) == 3
    assert all(h["duration_s"] > 0 for h in out["highlights"])
