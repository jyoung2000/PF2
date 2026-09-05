"""Phase S2 — story import, presets + pacing, shot context inheritance and
prompt assembly, timeline/gaps, continuity modes, approval gates with
dependency-only invalidation, Backlot board, resumable jobs, and the AI
Director (deterministic fallback + mocked LLM) with accept/reject."""
from __future__ import annotations

import pytest

from promptforge import db as db_mod
from promptforge import settings_store
from promptforge.film import assets as asset_svc
from promptforge.film import (board, continuity, director, gates, jobs, presets,
                              projects as proj_svc, shotctx, story, timeline)
from promptforge.film.models import FilmJob, FilmShot
from promptforge.llm import client as llm_client

SCRIPT = """FADE IN:

INT. WAREHOUSE - NIGHT

Rain hammers the skylights. JACK (34) crouches by a crate, a brass lantern beside him.

JACK
We don't have long.

SARAH
Then stop talking and open it.

EXT. DOCKS - DAWN

Fog. A container ship groans against the pier. Jack walks alone.
"""


@pytest.fixture()
def mock_llm(app_env):
    llm_client.mock_instance.responses = []
    llm_client.mock_instance.calls = []
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "mock")
    yield llm_client.mock_instance
    llm_client.mock_instance.responses = []


# ------------------------------------------------------------------- story -
def test_script_import_and_parse(client, app_env):
    p = client.post("/api/film/projects", json={"title": "Crate"}).json()
    parsed = client.post("/api/film/story/parse", json={"text": SCRIPT}).json()["scenes"]
    assert [x["title"] for x in parsed] == ["Warehouse", "Docks"]
    assert parsed[0]["time_of_day"] == "night" and parsed[0]["weather"] == "rain"
    assert parsed[0]["characters"] == ["Jack", "Sarah"] and parsed[0]["dialogue_words"] == 10
    assert parsed[1]["interior"] is False and parsed[1]["time_of_day"] == "dawn"
    r = client.post(f"/api/film/projects/{p['id']}/story/import", json={"text": SCRIPT}).json()
    scenes = r["project"]["scenes"]
    assert [sc["title"] for sc in scenes] == ["Warehouse", "Docks"]
    assert scenes[0]["defaults"]["characters"] == ["Jack", "Sarah"]
    assert scenes[0]["defaults"]["location_name"] == "Warehouse"
    assert "Rain hammers" in scenes[0]["script_text"] and scenes[0]["summary"].startswith("Rain hammers")
    # append keeps the old scenes, replace does not
    r2 = client.post(f"/api/film/projects/{p['id']}/story/import",
                     json={"text": "# Epilogue\nA year later.", "mode": "append"}).json()
    assert [sc["title"] for sc in r2["project"]["scenes"]] == ["Warehouse", "Docks", "Epilogue"]
    r3 = client.post(f"/api/film/projects/{p['id']}/story/import", json={"text": "Just prose."}).json()
    assert len(r3["project"]["scenes"]) == 1
    assert client.post(f"/api/film/projects/{p['id']}/story/import", json={"text": " "}).status_code == 422


# ----------------------------------------------------------------- presets -
def test_presets_pacing_and_user_customisation(client, app_env):
    pr = client.get("/api/film/presets").json()
    assert len(pr["shot_types"]) == 18 and pr["shot_types"][0]["key"] == "extreme_wide"
    assert {l["key"] for l in pr["lighting_presets"]} >= {"golden_hour", "neon_night", "horror_low_key"}
    assert presets.propose_duration("close_up", "normal") == 3.5
    assert presets.propose_duration("establishing", "slow") == 10.0
    assert presets.propose_duration("insert", "hypercut") == 0.5
    assert presets.propose_duration("medium", "normal", dialogue_words=40) == 16.5 - 6.5  # reading time wins (10.0)
    assert client.get("/api/film/presets/duration?shot_type=wide&profile=trailer").json()["duration_s"] == 2.0
    out = client.put("/api/film/presets", json={
        "favorites": ["close_up", "wide"],
        "shot_type_overrides": {"close_up": {"camera": {"lens_mm": 100}, "use": "my faces"}},
        "custom_shot_types": [{"key": "hero", "label": "Hero shot", "camera": {"shot_size": "low", "lens_mm": 24}}]}).json()
    cu = next(st for st in out["shot_types"] if st["key"] == "close_up")
    assert cu["favorite"] and cu["customized"] and cu["camera"]["lens_mm"] == 100 and cu["use"] == "my faces"
    assert out["shot_types"][-1]["key"] == "custom_hero" and out["shot_types"][-1]["custom"]
    assert out["favorites"] == ["close_up", "wide"]


# ------------------------------------------------------------ shot context -
def _film(s):
    jack = asset_svc.create_asset(s, "character", "Jack", data={"eyes": "green", "hair": "black", "age": "34"},
                                  negative_constraints=["no beard"])
    wh = asset_svc.create_asset(s, "location", "Warehouse",
                                data={"architecture": "brick industrial hall", "lighting": "sodium practicals"})
    style = asset_svc.create_asset(s, "style", "Neon noir", data={"palette": "teal and magenta",
                                                                  "film_grain": "coarse",
                                                                  "negative_style": "no cartoon"})
    p = proj_svc.create_project(s, "Crate", settings={"visual_style": "gritty 35mm", "aspect_ratio": "2.39:1"})
    sc = proj_svc.create_scene(s, p, "Warehouse", defaults={
        "assets": [{"asset_id": jack.id}, {"asset_id": wh.id}, {"asset_id": style.id}],
        "time_of_day": "night", "weather": "rain", "lighting_preset": "neon_night",
        "camera": {"lens_mm": 35}, "mood": "tense"})
    return p, sc, jack, wh, style


def test_effective_context_inherits_and_tracks_sources(app_env):
    with db_mod.session_scope() as s:
        p, sc, jack, wh, style = _film(s)
        sh = proj_svc.create_shot(s, sc, "Jack finds the crate", duration_s=5,
                                  overrides={"shot_type": "close_up", "camera": {"movement": "push_in"},
                                             "action": "Jack pries the crate open", "expression": "wary"},
                                  locks=["camera"])
        ctx = shotctx.effective_context(s, sh)
        cam = ctx["camera"]
        assert cam["shot_size"] == "close_up" and cam["angle"] == "eye_level"     # from the preset
        assert cam["lens_mm"] == 35                                              # scene beats preset
        assert cam["movement"] == "push_in"                                      # shot beats scene
        assert ctx["sources"]["camera.shot_size"] == "preset:close_up"
        assert ctx["sources"]["camera.lens_mm"] == "scene" and ctx["sources"]["camera.movement"] == "shot"
        assert ctx["lighting"]["mood"] == "electric, noir" and ctx["sources"]["lighting.mood"] == "preset:neon_night"
        assert ctx["environment"] == {"time_of_day": "night", "weather": "rain"}
        assert ctx["style"]["visual_style"] == "gritty 35mm" and ctx["sources"]["style.visual_style"] == "project"
        assert [a["name"] for a in ctx["assets"]] == ["Jack", "Warehouse", "Neon noir"]
        assert {v["name"]: v["version"] for v in ctx["asset_versions"]} == {"Jack": 1, "Warehouse": 1, "Neon noir": 1}
        assert "Jack:face" in ctx["asset_locks"] and ctx["locks"] == ["camera"]
        assert any(c.startswith("Jack: eyes = green") for c in ctx["constraints"])

        pr = shotctx.build_prompt(ctx)
        text = pr["prompt"]
        assert text.startswith("gritty 35mm, Neon noir (style v1)")
        assert "close-up, 35mm lens, push in camera move" in text
        assert "Jack pries the crate open" in text and "expression: wary" in text
        assert "Jack (character v1). LOCKED — eyes: green; hair: black" in text
        assert "Location — Warehouse (location v1). LOCKED — architecture: brick industrial hall" in text
        assert "electric, noir lighting" in text and "night, rain" in text
        assert text.endswith("cinematic video, 2.39:1")
        assert pr["negative"] == "no beard, no cartoon"
        # same context ⇒ same prompt (deterministic)
        assert shotctx.build_prompt(shotctx.effective_context(s, sh))["prompt"] == text

        # targeted regeneration never lets locked groups into `change`
        rg = shotctx.regeneration_prompt(ctx, change=["clothing", "camera", "hair"], preserve=["Warehouse"],
                                         instruction="give him a red jacket")
        assert rg["change"] == ["clothing"] and set(rg["blocked"]) == {"camera", "hair"}
        assert "Change only: clothing" in rg["prompt"] and "Requested change: give him a red jacket" in rg["prompt"]
        assert "Keep exactly as in the reference: Warehouse, camera, hair" in rg["prompt"]
        # raw prompt override replaces the body, constraints stay
        proj_svc.update_shot(s, sh, overrides={**sh.overrides, "prompt": "RAW BODY"})
        t2 = shotctx.build_prompt(shotctx.effective_context(s, sh))["prompt"]
        assert "RAW BODY" in t2 and "LOCKED — eyes: green" in t2 and "pries the crate" not in t2


# ---------------------------------------------------------------- timeline -
def test_timeline_gaps_transitions_and_runtime(client, app_env):
    p = client.post("/api/film/projects", json={"title": "T"}).json()
    s1 = client.post(f"/api/film/projects/{p['id']}/scenes", json={"title": "One"}).json()
    s2 = client.post(f"/api/film/projects/{p['id']}/scenes", json={"title": "Two"}).json()
    a = client.post(f"/api/film/scenes/{s1['id']}/shots", json={"duration_s": 6}).json()
    b = client.post(f"/api/film/scenes/{s1['id']}/shots", json={"duration_s": 2.5}).json()
    client.post(f"/api/film/scenes/{s2['id']}/shots", json={"duration_s": 4})
    tl = client.get(f"/api/film/projects/{p['id']}/timeline").json()
    assert tl["runtime_s"] == 13.0 and tl["runtime_tc"] == "00:00:13.0"
    assert tl["scenes"][0]["gap_after_s"] == 0.5 and tl["scenes"][0]["gap_inherited"] is True
    assert tl["scenes"][0]["shots"][1]["start_s"] == 6.0 and tl["scenes"][1]["start_s"] == 9.0
    assert tl["scenes"][1]["gap_after_s"] is None                       # nothing after the last scene
    # per-scene override, others keep the default
    tl = client.post(f"/api/film/scenes/{s1['id']}/gap", json={"gap_after_s": 2.0}).json()
    assert tl["runtime_s"] == 14.5 and tl["scenes"][0]["gap_inherited"] is False
    # apply to all → explicit overrides everywhere
    tl = client.post(f"/api/film/projects/{p['id']}/timeline/gap", json={"apply_to_all": 1.0}).json()
    assert tl["runtime_s"] == 13.5 and tl["scenes"][0]["gap_after_s"] == 1.0 and not tl["scenes"][0]["gap_inherited"]
    # reset scene 1 to default
    tl = client.post(f"/api/film/scenes/{s1['id']}/gap", json={"gap_after_s": None}).json()
    assert tl["runtime_s"] == 13.0 and tl["scenes"][0]["gap_inherited"] is True
    # project default changes propagate to inheriting scenes only
    tl = client.post(f"/api/film/projects/{p['id']}/timeline/gap", json={"default_gap_s": 1.5}).json()
    assert tl["runtime_s"] == 14.0 and tl["default_scene_gap_s"] == 1.5
    # editorial transition ≠ gap: a dissolve overlaps shots inside the scene
    client.patch(f"/api/film/shots/{a['id']}", json={"transition": {"kind": "dissolve", "duration_s": 0.5}})
    tl = client.get(f"/api/film/projects/{p['id']}/timeline").json()
    assert tl["scenes"][0]["duration_s"] == 8.0 and tl["runtime_s"] == 13.5
    assert tl["scenes"][0]["shots"][0]["transition"] == {"kind": "dissolve", "duration_s": 0.5}
    assert tl["scenes"][0]["shots"][1]["transition"] is None            # last shot of the scene
    # a shot-duration change recalculates downstream timecodes
    client.patch(f"/api/film/shots/{b['id']}", json={"duration_s": 4.5})
    tl = client.get(f"/api/film/projects/{p['id']}/timeline").json()
    assert tl["scenes"][1]["tc_in"] == "00:00:11.5" and tl["runtime_tc"] == "00:00:15.5"
    assert timeline.format_tc(3725.04) == "01:02:05.0"


# -------------------------------------------------------------- continuity -
def test_continuity_checks_and_modes(app_env):
    with db_mod.session_scope() as s:
        p, sc, jack, wh, style = _film(s)
        docks = asset_svc.create_asset(s, "location", "Docks")
        lantern = asset_svc.create_asset(s, "prop", "Brass lantern")
        v1 = asset_svc.current_version(s, jack)
        a = proj_svc.create_shot(s, sc, "A", overrides={"shot_type": "close_up"})
        b = proj_svc.create_shot(s, sc, "B", overrides={"shot_type": "close_up"})
        c = proj_svc.create_shot(s, sc, "C", overrides={"shot_type": "wide"}, duration_s=30)
        proj_svc.pin_asset(s, a, lantern)
        proj_svc.pin_asset(s, c, lantern)
        v2, _ = asset_svc.edit_version(s, jack, {"hair": "grey"})
        proj_svc.pin_asset(s, b, jack, v2.id)
        proj_svc.pin_asset(s, c, docks)
        rep = continuity.validate_project(s, p)
        kinds = {(w["kind"], tuple(w["shot_ids"])) for w in rep["warnings"]}
        assert ("character_version", (a.id, b.id)) in kinds
        assert ("jump_cut", (a.id, b.id)) in kinds
        assert ("prop_disappearance", (a.id, b.id, c.id)) in kinds
        assert ("location_mismatch", (b.id, c.id)) in kinds
        assert ("timing", (c.id,)) in kinds                       # 30s vs 4s median
        assert rep["mode"] == "balanced" and rep["blocking"] is False
        assert any(w["kind"] == "character_version" and w["severity"] == "warn" for w in rep["warnings"])
        s.refresh(b)
        assert {w["kind"] for w in b.warnings} >= {"character_version", "jump_cut", "location_mismatch"}
        # flexible: everything informational
        proj_svc.update_project(s, p, settings={"continuity_mode": "flexible"})
        rep = continuity.validate_project(s, p)
        assert {w["severity"] for w in rep["warnings"]} == {"info"}
        # strict: canonical kinds block until the shot is explicitly overridden
        proj_svc.update_project(s, p, settings={"continuity_mode": "strict"})
        rep = continuity.validate_project(s, p)
        assert rep["blocking"] and rep["counts"]["block"] == 4   # jack v1→v2 (a,b), v2→v1 (b,c), prop, location
        ok, reasons = continuity.can_generate(s, s.get(FilmShot, b.id))
        assert ok is False and any("Jack changes from v1 to v2" in r for r in reasons)
        for sh in (a, b, c):
            proj_svc.update_shot(s, sh, overrides={**(sh.overrides or {}), "continuity_override": True})
        rep = continuity.validate_project(s, p)
        assert rep["blocking"] is False and any(w.get("overridden") for w in rep["warnings"])


# ------------------------------------------------------------------- gates -
def test_gates_snapshot_and_dependency_only_invalidation(client, app_env):
    with db_mod.session_scope() as s:
        p, sc, jack, wh, style = _film(s)
        sc2 = proj_svc.create_scene(s, p, "Docks", defaults={"assets": [{"asset_id": wh.id}]})
        a = proj_svc.create_shot(s, sc, "A")
        b = proj_svc.create_shot(s, sc2, "B")
        pid, sc_id, sc2_id, a_id, b_id, jack_id, wh_id, style_id = p.id, sc.id, sc2.id, a.id, b.id, jack.id, wh.id, style.id
    g = client.get(f"/api/film/projects/{pid}/gates").json()["gates"]
    assert [x["kind"] for x in g] == ["plan", "assets", "storyboard", "rough_cut", "rough_cut", "qa", "export"]
    assert all(x["status"] == "pending" for x in g)
    assert client.post(f"/api/film/projects/{pid}/gates/rough_cut", json={"status": "approved"}).status_code == 422
    assert client.post(f"/api/film/projects/{pid}/gates/bogus", json={"status": "approved"}).status_code == 422

    ok = client.post(f"/api/film/projects/{pid}/gates/assets", json={"status": "approved"}).json()
    assert ok["status"] == "approved" and set(ok["snapshot"]["versions"]) == {str(jack_id), str(wh_id), str(style_id)}
    assert all(client.get(f"/api/film/assets/{x}").json()["approved"] for x in (jack_id, wh_id))
    sb = client.post(f"/api/film/projects/{pid}/gates/storyboard", json={"status": "approved"}).json()
    assert sb["status"] == "approved" and client.get(f"/api/film/shots/{a_id}").json()["approved"]
    rc = client.post(f"/api/film/projects/{pid}/gates/rough_cut", json={"status": "approved", "scene_id": sc_id}).json()
    assert rc["scene_id"] == sc_id and client.get(f"/api/film/scenes/{sc_id}").json()["approved"]

    # reject ONLY Jack: shot A (uses Jack) loses approval, shot B (Warehouse only) keeps it
    rj = client.post(f"/api/film/projects/{pid}/gates/assets",
                     json={"status": "rejected", "item_ids": [jack_id], "note": "face drifts"}).json()
    assert rj["invalidated"]["shots"] == [a_id] and rj["invalidated"]["assets"] == [jack_id]
    assert rj["invalidated"]["scenes"] == [sc_id] and "storyboard" in rj["invalidated"]["gates"]
    sa = client.get(f"/api/film/shots/{a_id}").json()
    assert sa["approved"] is False and sa["warnings"][0]["kind"] == "asset_rejected"
    assert client.get(f"/api/film/shots/{b_id}").json()["approved"] is True
    assert client.get(f"/api/film/assets/{jack_id}").json()["approved"] is False
    assert client.get(f"/api/film/assets/{wh_id}").json()["approved"] is True
    g = {x["kind"] + (f":{x['scene_id']}" if x["scene_id"] else ""): x["status"]
         for x in client.get(f"/api/film/projects/{pid}/gates").json()["gates"]}
    assert g["storyboard"] == "pending" and g[f"rough_cut:{sc_id}"] == "pending" and g["assets"] == "rejected"
    # stale detection: approve storyboard, then change a shot
    client.post(f"/api/film/projects/{pid}/gates/storyboard", json={"status": "approved"})
    client.patch(f"/api/film/shots/{b_id}", json={"duration_s": 9})
    sb = next(x for x in client.get(f"/api/film/projects/{pid}/gates").json()["gates"] if x["kind"] == "storyboard")
    assert sb["status"] == "approved" and sb["stale"] is True
    ev = client.get(f"/api/film/projects/{pid}/events?kind=gate").json()["events"]
    assert any(e["reason"] == "face drifts" for e in ev)


# ---------------------------------------------------------- board + jobs --
def test_board_derives_from_state_and_jobs_resume_from_checkpoint(client, app_env):
    p = client.post("/api/film/projects", json={"title": "Board"}).json()
    b = client.get(f"/api/film/projects/{p['id']}/board").json()
    stages = {st["key"]: st for st in b["stages"]}
    assert stages["concept"]["status"] == "todo" and stages["story"]["status"] == "todo"
    client.post(f"/api/film/projects/{p['id']}/story/import", json={"text": SCRIPT})
    b = client.get(f"/api/film/projects/{p['id']}/board").json()
    stages = {st["key"]: st for st in b["stages"]}
    assert stages["story"]["status"] == "done" and stages["story"]["progress"] == {"done": 2, "total": 2}
    assert stages["shot_generation"]["status"] == "todo" and stages["export"]["status"] == "todo"
    assert b["cost"] == {"estimated_usd": 0, "actual_usd": 0, "budget": {"mode": "warn", "threshold_usd": 5.0, "cap_usd": None}}
    rp = client.get(f"/api/film/projects/{p['id']}/replay").json()
    assert rp["count"] >= 2 and rp["events"][0]["title"].startswith("Project")

    processed: list[int] = []
    state = {"paused_once": False}

    def handler(job_id: int):
        done = set(jobs.done_items(job_id))
        for item in [1, 2, 3, 4, 5]:
            if item in done:
                continue
            jobs.check_stop(job_id)
            processed.append(item)
            jobs.checkpoint(job_id, item, current=f"item {item}")
            if item == 2 and not state["paused_once"]:
                state["paused_once"] = True
                with db_mod.session_scope() as s:
                    jobs.pause(s, s.get(FilmJob, job_id))
        return {"processed": len(processed)}

    jobs.register("test_batch", handler)
    with db_mod.session_scope() as s:
        j = jobs.create(s, p["id"], "test_batch", total=5)
        jid = j.id
    assert jobs.run(jid) == "paused" and processed == [1, 2]
    jd = client.get(f"/api/film/jobs/{jid}").json()
    assert jd["status"] == "paused" and jd["checkpoint"]["done"] == [1, 2] and jd["progress"]["done"] == 2
    with db_mod.session_scope() as s:
        jobs.resume(s, s.get(FilmJob, jid), inline=True)
    assert processed == [1, 2, 3, 4, 5]                                  # nothing redone
    jd = client.get(f"/api/film/jobs/{jid}").json()
    assert jd["status"] == "done" and jd["result"] == {"processed": 5} and jd["progress"]["done"] == 5
    # crash recovery re-queues jobs stuck in 'running'; missing handlers fail loudly
    with db_mod.session_scope() as s:
        j2 = jobs.create(s, p["id"], "no_such_kind")
        j2.status = "running"
        j2id = j2.id
    assert jobs.recover_on_boot() == 1
    assert jobs.run(j2id) == "failed"
    assert "no handler" in client.get(f"/api/film/jobs/{j2id}").json()["error"]
    assert client.post(f"/api/film/jobs/{j2id}/cancel").json()["status"] == "cancelled"


# ---------------------------------------------------------------- director -
def test_director_fallback_story_plan_shot_and_accept(client, app_env):
    p = client.post("/api/film/projects", json={"title": "Crate", "script": SCRIPT,
                                                "settings": {"pacing_profile": "fast"}}).json()
    pid = p["id"]
    prop = client.post(f"/api/film/projects/{pid}/director/story", json={"use_llm": False}).json()
    assert prop["source"] == "fallback" and prop["applied"] is False
    scenes = prop["proposal"]["scenes"]
    assert [sc["title"] for sc in scenes] == ["Warehouse", "Docks"]
    assert [sh["shot_type"] for sh in scenes[0]["shots"]] == ["establishing", "medium", "two_shot", "close_up"]
    assert [sh["shot_type"] for sh in scenes[1]["shots"]] == ["establishing", "wide", "insert"]
    assert scenes[0]["lighting_preset"] == "overcast" and scenes[1]["lighting_preset"] == "overcast"
    assert all(sh["duration_s"] <= 6.0 for sc in scenes for sh in sc["shots"])   # fast profile
    assert all(sh["reason"] for sc in scenes for sh in sc["shots"])
    names = {(a["type"], a["name"]) for k in prop["proposal"]["assets"].values() for a in k}
    assert names == {("character", "Jack"), ("character", "Sarah"), ("location", "Warehouse"), ("location", "Docks")}
    est = prop["proposal"]["estimates"]
    assert est["basis"] == "catalog" and est["total_usd"] > 0 and est["providers_connected"] is False
    assert est["video_family"] == "kling" and est["unpriced_shots"] == 0
    assert client.get(f"/api/film/projects/{pid}/proposals?pending=true").json()["proposals"][0]["id"] == prop["id"]

    acc = client.post(f"/api/film/proposals/{prop['id']}/accept", json={"mode": "replace"}).json()
    assert len(acc["result"]["scene_ids"]) == 2 and len(acc["result"]["shot_ids"]) == 7
    assert acc["proposal"]["applied"] is True
    assert client.post(f"/api/film/proposals/{prop['id']}/accept").status_code == 422   # once only
    proj = client.get(f"/api/film/projects/{pid}").json()
    assert proj["status"] == "planning"
    wh_scene = proj["scenes"][0]
    assert {a["name"] for a in wh_scene["shots"][0]["assets"]} == {"Jack", "Sarah", "Warehouse"}
    assert all(a["version"] == 1 for a in wh_scene["shots"][0]["assets"])
    assert wh_scene["shots"][2]["overrides"]["shot_type"] == "two_shot"
    assert wh_scene["shots"][2]["overrides"]["characters"] == ["Jack", "Sarah"]
    assert wh_scene["defaults"]["time_of_day"] == "night" and wh_scene["defaults"]["lighting_preset"] == "overcast"
    jack = next(a for a in client.get("/api/film/assets?type=character").json()["assets"] if a["name"] == "Jack")
    assert jack["provenance"]["origin"] == "director"
    # accepting again with the same names reuses assets instead of duplicating them
    prop2 = client.post(f"/api/film/projects/{pid}/director/story", json={"use_llm": False}).json()
    client.post(f"/api/film/proposals/{prop2['id']}/accept", json={"mode": "append"})
    assert len(client.get("/api/film/assets?type=character").json()["assets"]) == 2
    assert client.get(f"/api/film/projects/{pid}").json()["scene_count"] == 4
    ev = client.get(f"/api/film/projects/{pid}/events?kind=decision").json()["events"]
    assert any(e["actor"] == "director" and e["reason"] == "Opens the scene: geography first." for e in ev)

    # Direct Shot (fallback): keyword direction, locked camera is never changed
    shot = wh_scene["shots"][1]
    client.patch(f"/api/film/shots/{shot['id']}", json={"locks": ["camera"]})
    ds = client.post(f"/api/film/shots/{shot['id']}/director",
                     json={"instruction": "make it tense and intimate, slow, longer", "use_llm": False}).json()
    ch = ds["proposal"]["changes"]
    assert ch["lighting_preset"] == "cinematic_soft" and ch["color"] == {"contrast": "high"}
    assert ch["motion"] == {"pacing": "slow"} and ch["duration_s"] > shot["duration_s"]
    assert {b["key"] for b in ds["proposal"]["blocked"]} == {"shot_type", "camera"}
    assert "camera is locked" in ds["proposal"]["blocked"][0]["reason"]
    acc = client.post(f"/api/film/proposals/{ds['id']}/accept").json()["result"]
    assert set(acc["changed"]) == {"lighting_preset", "color", "motion", "duration_s"}
    after = client.get(f"/api/film/shots/{shot['id']}").json()
    assert after["overrides"]["lighting_preset"] == "cinematic_soft" and after["overrides"]["shot_type"] == "medium"
    assert after["overrides"]["color"]["contrast"] == "high" and after["status"] == "framed"
    # reject path
    ds2 = client.post(f"/api/film/shots/{shot['id']}/director", json={"instruction": "epic", "use_llm": False}).json()
    rj = client.post(f"/api/film/proposals/{ds2['id']}/reject", json={"note": "no"}).json()
    assert rj["rejected"] and rj["note"] == "no"
    assert client.post(f"/api/film/proposals/{ds2['id']}/accept").status_code == 422
    # scene director: replace mode swaps the shots
    dsc = client.post(f"/api/film/scenes/{wh_scene['id']}/director", json={"use_llm": False}).json()
    assert len(dsc["proposal"]["shots"]) == 4
    client.post(f"/api/film/proposals/{dsc['id']}/accept", json={"mode": "replace"})
    assert len(client.get(f"/api/film/scenes/{wh_scene['id']}").json()["shots"]) == 4

    # production plan (fallback) with catalog-based estimates; accept → plan on project; gate approves
    plan = client.post(f"/api/film/projects/{pid}/director/plan", json={"use_llm": False}).json()
    pp = plan["proposal"]
    assert pp["shot_count"] == 14 and pp["scene_count"] == 4 and pp["estimated_cost_usd"] > 0
    assert "connect a provider" in pp["provider_strategy"] and pp["shots_basis"] == "framed shots"
    assert pp["media_strategy"]["by_kind"] == {"ai_video": 14}
    acc = client.post(f"/api/film/proposals/{plan['id']}/accept", json={"edits": {"audience": "festival"}}).json()
    proj = client.get(f"/api/film/projects/{pid}").json()
    assert proj["plan"]["audience"] == "festival" and proj["plan"]["approved"] is False
    assert proj["settings"]["audience"] == "festival"
    g = client.post(f"/api/film/projects/{pid}/gates/plan", json={"status": "approved"}).json()
    assert g["status"] == "approved" and client.get(f"/api/film/projects/{pid}").json()["plan"]["approved"] is True
    stages = {st["key"]: st for st in client.get(f"/api/film/projects/{pid}/board").json()["stages"]}
    assert stages["concept"]["status"] == "done" and stages["assets"]["status"] == "in_progress"
    # direct plan edit resets approval
    client.put(f"/api/film/projects/{pid}/plan", json={"plan": {"objective": "new"}})
    assert client.get(f"/api/film/projects/{pid}").json()["plan"]["approved"] is False
    est = client.get(f"/api/film/projects/{pid}/estimate").json()
    assert est["basis"] == "catalog" and len(est["per_shot"]) == 14


def test_director_with_llm_uses_and_validates_json(client, mock_llm):
    p = client.post("/api/film/projects", json={"title": "LLM", "synopsis": "A courier loses a package."}).json()
    mock_llm.responses = ['Sure! {"scenes":[{"title":"Alley","intent":"hook","location":"Alley","time_of_day":"night",'
                          '"characters":["Mira"],"shots":[{"title":"Run","action":"Mira sprints","shot_type":"tracking",'
                          '"camera":{"lens_mm":24,"movement":"tracking","angle":"low"},"duration_s":3,'
                          '"media_strategy":"ai_video","characters":["Mira"],"reason":"energy"}]}],'
                          '"assets":{"characters":[{"name":"Mira","description":"courier","data":{"hair":"blue","bogus":1}}]},'
                          '"notes":"ok"}']
    prop = client.post(f"/api/film/projects/{p['id']}/director/story").json()
    assert prop["source"] == "llm"
    sh = prop["proposal"]["scenes"][0]["shots"][0]
    assert sh["shot_type"] == "medium" and sh["camera"] == {"lens_mm": 24, "movement": "tracking", "angle": "low"}
    assert prop["proposal"]["assets"]["characters"][0]["data"] == {"hair": "blue", "bogus": 1}
    assert mock_llm.calls[0][1].startswith("Title: LLM")
    mock_llm.responses = ["I cannot help with that."]
    r = client.post(f"/api/film/projects/{p['id']}/director/plan")
    assert r.status_code == 502 and "no usable JSON" in r.json()["detail"]
    # no provider configured at all ⇒ graceful fallback, never an error
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "")
    assert client.post(f"/api/film/projects/{p['id']}/director/plan").json()["source"] == "fallback"
