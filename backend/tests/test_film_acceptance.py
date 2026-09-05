"""Spec AL — the minimum acceptance journey, scripted through the real app
(TestClient over the real FastAPI app + real ffmpeg) with mocked providers:
project → script → character/location → attributes + locks → references →
production plan → scenes/shots → visual shot type → durations + gaps →
camera/lighting → start/end frames → previous-frame chaining → sample →
storyboard approval → takes (alternates kept) → continuity → QA →
timeline → audio/subtitles → export → restart → persistence."""
from __future__ import annotations

from promptforge import config as cfg_mod
from promptforge import db as db_mod
from promptforge.film import takes as take_svc
from promptforge.film import qa
from promptforge.generation import queue as gen_queue
from tests.test_film_generation import SCRATCH, _connect, mp4, png, providers  # noqa: F401

SCRIPT = """INT. WAREHOUSE - NIGHT

Rain hammers the skylights. JACK crouches by a crate.

JACK
We don't have long.

SARAH
Then stop talking.

EXT. DOCKS - DAWN

Fog. Jack walks alone.
"""


def test_acceptance_journey_end_to_end(client, app_env, providers):
    # 1–2. project + script
    p = client.post("/api/film/projects", json={"title": "Rainy City", "logline": "A courier loses a package.",
                                                "settings": {"target_runtime_s": 30, "default_scene_gap_s": 0.5,
                                                             "budget": {"mode": "observe"}}}).json()
    pid = p["id"]
    r = client.post(f"/api/film/projects/{pid}/story/import", json={"text": SCRIPT}).json()
    assert len(r["scene_ids"]) == 2
    # 3–6. character + location, attributes, locks, references
    jack = client.post("/api/film/assets", json={"type": "character", "name": "Jack", "data": {"eyes": "green", "hair": "black"}}).json()
    wh = client.post("/api/film/assets", json={"type": "location", "name": "Warehouse", "data": {"architecture": "brick hall", "lighting": "sodium"}}).json()
    e = client.post(f"/api/film/assets/{jack['id']}/versions", json={"changes": {"distinctive_features": "scar"}, "locks": ["face", "hair", "body", "clothing"]}).json()
    assert e["created"] is False and e["version"]["locks"] == ["face", "hair", "body", "clothing"]
    ref = client.post(f"/api/film/assets/{jack['id']}/refs", files={"file": ("jack.png", png(256, 320, (90, 60, 40)), "image/png")}, data={"kind": "portrait"}).json()["ref"]
    assert client.get(f"/api/film/assets/{jack['id']}").json()["current_version"]["primary_ref_id"] == ref["id"]
    # 7. production plan (deterministic) → accept → approve
    plan = client.post(f"/api/film/projects/{pid}/director/plan", json={"use_llm": False}).json()
    client.post(f"/api/film/proposals/{plan['id']}/accept")
    assert client.post(f"/api/film/projects/{pid}/gates/plan", json={"status": "approved"}).json()["status"] == "approved"
    # 8. scenes + shots from the Director, replacing the imported empty scenes
    story = client.post(f"/api/film/projects/{pid}/director/story", json={"use_llm": False}).json()
    acc = client.post(f"/api/film/proposals/{story['id']}/accept", json={"mode": "replace"}).json()["result"]
    assert len(acc["scene_ids"]) == 2 and len(acc["shot_ids"]) == 7
    proj = client.get(f"/api/film/projects/{pid}").json()
    scenes = proj["scenes"]
    shots = [sh for sc in scenes for sh in sc["shots"]]
    assert {a["name"] for a in shots[0]["assets"]} >= {"Jack", "Sarah", "Warehouse"}   # Director reused the existing Jack
    assert client.get("/api/film/assets?type=character").json()["assets"].__len__() == 2
    # 9–10. visual shot type from the library, duration, project gap, one override, runtime maths
    presets = client.get("/api/film/presets").json()
    cu = next(st for st in presets["shot_types"] if st["key"] == "close_up")
    s2 = shots[1]
    client.patch(f"/api/film/shots/{s2['id']}", json={"overrides": {**s2["overrides"], "shot_type": "close_up", "camera": cu["camera"]}, "duration_s": 3.0})
    tl = client.post(f"/api/film/projects/{pid}/timeline/gap", json={"default_gap_s": 1.0}).json()
    tl = client.post(f"/api/film/scenes/{scenes[0]['id']}/gap", json={"gap_after_s": 2.5}).json()
    assert tl["scenes"][0]["gap_after_s"] == 2.5 and tl["scenes"][0]["gap_inherited"] is False
    assert tl["scenes"][1]["gap_after_s"] is None                       # last scene: nothing after it
    expected = sum(sh["duration_s"] for sh in tl["scenes"][0]["shots"]) + 2.5 + sum(sh["duration_s"] for sh in tl["scenes"][1]["shots"])
    assert abs(tl["runtime_s"] - expected) < 1e-6 and tl["default_scene_gap_s"] == 1.0
    # 11–12. camera + lighting visually (values the controls emit)
    client.patch(f"/api/film/shots/{s2['id']}", json={"overrides": {**client.get(f"/api/film/shots/{s2['id']}").json()["overrides"],
                                                                     "camera": {**cu["camera"], "lens_mm": 85, "movement": "push_in", "movement_speed": "slow"},
                                                                     "lighting": {"key_intensity": 0.7, "rim_intensity": 0.9, "color_temp_k": 4300, "direction": "key from front-left", "mood": "electric, noir"},
                                                                     "lighting_preset": "neon_night"}, "locks": ["camera"]})
    ctx = client.get(f"/api/film/shots/{s2['id']}/context").json()
    assert "close-up, 85mm lens, slow push in camera move" in ctx["prompt"]["prompt"]
    assert "4300K" in ctx["prompt"]["prompt"] and "camera" in ctx["prompt"]["locks"]
    # 13. start/end frames: generate the start frame, upload the end frame
    fr = client.post(f"/api/film/shots/{shots[0]['id']}/frames/start_frame/generate", json={}).json()["take"]
    gen_queue.process_generation(fr["generation_id"])
    assert client.get(f"/api/film/shots/{shots[0]['id']}").json()["start_frame"]["kind"] == "generated"
    client.post(f"/api/film/shots/{shots[0]['id']}/frames/end_frame/upload", files={"file": ("end.png", png(), "image/png")})
    # 14. sample run (before bulk generation) → takes land through the queue
    job = client.post(f"/api/film/projects/{pid}/runs", json={"sample": True, "inline": True}).json()
    assert job["status"] == "done" and len(job["result"]["take_ids"]) >= 2
    for tid in job["result"]["take_ids"]:
        gen_queue.process_generation(client.get(f"/api/film/takes/{tid}").json()["generation_id"])
    first = client.get(f"/api/film/shots/{shots[0]['id']}").json()
    assert first["status"] == "generated" and first["selected_take"]["mode"] == "start_end_to_video"
    # 15. previous-frame chaining: shot 2 starts from shot 1's last frame and
    #     its next take rides that frame (image → video), the sample take stays
    sample_take = client.get(f"/api/film/shots/{s2['id']}").json()["selected_take"]
    assert sample_take["mode"] == "reference_to_video"                   # no frame yet → identity reference
    chained = client.post(f"/api/film/shots/{s2['id']}/frames/start_frame", json={"kind": "previous_shot"}).json()
    assert chained["start_frame"]["kind"] == "previous_shot" and chained["start_frame"]["source_shot_id"] == shots[0]["id"]
    t2 = client.post(f"/api/film/shots/{s2['id']}/takes", json={"kind": "video"}).json()["take"]
    assert t2["mode"] == "image_to_video" and t2["params"]["inputs"]["image"].endswith("_last.png")
    gen_queue.process_generation(t2["generation_id"])
    assert providers.submits[-1]["params"]["_inputs"]["image"] == t2["params"]["inputs"]["image"]
    # 16. storyboard/contact sheet approval → 17–18. generate the rest, alternates preserved
    client.post(f"/api/film/projects/{pid}/gates/assets", json={"status": "approved"})
    assert client.post(f"/api/film/projects/{pid}/gates/storyboard", json={"status": "approved"}).json()["status"] == "approved"
    batch = client.post(f"/api/film/projects/{pid}/runs", json={"inline": True}).json()
    assert batch["status"] == "done" and len(batch["result"]["take_ids"]) == 4      # the 3 sampled shots are skipped
    for tid in batch["result"]["take_ids"]:
        gen_queue.process_generation(client.get(f"/api/film/takes/{tid}").json()["generation_id"])
    second = client.get(f"/api/film/shots/{s2['id']}").json()
    assert second["selected_take_id"] == sample_take["id"]                # a new take never replaces the chosen one
    alt = client.post(f"/api/film/shots/{s2['id']}/takes", json={"kind": "video", "instruction": "brighter", "change": ["lighting"]}).json()["take"]
    gen_queue.process_generation(alt["generation_id"])
    takes = client.get(f"/api/film/shots/{s2['id']}/takes").json()
    assert len([t for t in takes["takes"] if t["kind"] == "video"]) == 3 and takes["selected_take_id"] == sample_take["id"]
    assert client.get(f"/api/film/takes/{sample_take['id']}/compare/{alt['id']}").json()["differences"]
    client.post(f"/api/film/takes/{t2['id']}/select")
    assert client.get(f"/api/film/shots/{s2['id']}").json()["selected_take_id"] == t2["id"]
    assert all(sh["status"] in ("generated", "approved") for sh in [x for sc in client.get(f"/api/film/projects/{pid}").json()["scenes"] for x in sc["shots"]])
    # 19–20. continuity + QA, timeline, audio + subtitles
    cont = client.post(f"/api/film/projects/{pid}/continuity").json()
    assert cont["mode"] == "balanced" and cont["blocking"] is False
    client.post(f"/api/film/projects/{pid}/audio", files={"file": ("bed.wav", __import__("tests.test_film_generation", fromlist=["wav"]).wav(2.0), "audio/wav")}, data={"kind": "music"})
    subs = client.post(f"/api/film/projects/{pid}/subtitles/from-script").json()
    assert len(subs["cues"]) == 2 and subs["validation"]["status"] == "PASS"
    report = client.get(f"/api/film/projects/{pid}/qa").json()
    assert report["verdict"] in ("PASS", "WARN") and all(v["verdict"] != "FAIL" for v in report["per_shot"].values())
    # 21. export master + sources
    exp = client.post(f"/api/film/projects/{pid}/export", json={"label": "master", "quality": "720p", "inline": True}).json()
    assert exp["status"] == "done", exp
    res = exp["result"]
    assert res["review"]["verdict"] in ("PASS", "WARN") and res["sources_url"] and res["srt_url"]
    with db_mod.session_scope() as s:
        info = qa.probe(take_svc.abs_path(res["path"]))
        assert info["audio"] and abs(info["duration"] - res["runtime_s"]) < 0.5
    board = {st["key"]: st["status"] for st in client.get(f"/api/film/projects/{pid}/board").json()["stages"]}
    assert board["export"] == "done" and board["shot_generation"] == "done"
    # 22. restart: new engine over the same data dir, everything persists
    db_mod.dispose_db()
    cfg = cfg_mod.Config(data_dir=app_env.data_dir)
    cfg_mod.set_config(cfg)
    db_mod.init_db()
    from fastapi.testclient import TestClient
    from promptforge.main import create_app
    with TestClient(create_app()) as c2:
        again = c2.get(f"/api/film/projects/{pid}").json()
        assert again["shot_count"] == 7 and again["plan"]["approved"] is True
        sh = c2.get(f"/api/film/shots/{s2['id']}").json()
        assert sh["locks"] == ["camera"] and sh["take_count"] == 3 and sh["start_frame"]["kind"] == "previous_shot"
        assert c2.get(f"/api/film/projects/{pid}/exports").json()["exports"][0]["status"] == "done"
        gates = {g["kind"]: g["status"] for g in c2.get(f"/api/film/projects/{pid}/gates").json()["gates"]}
        assert gates["plan"] == "approved" and gates["storyboard"] == "approved"
        assert c2.get(f"/api/film/assets/{jack['id']}").json()["current_version"]["locks"] == ["face", "hair", "body", "clothing"]
        log = c2.get(f"/api/film/projects/{pid}/replay").json()
        assert log["count"] > 20 and log["events"][0]["title"].startswith("Project")
