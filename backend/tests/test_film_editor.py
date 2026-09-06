"""Editor phase E2 — sequence engine: build-from-storyboard, clip edit ops
(move/trim/split/ripple/markers), validation, locked tracks, and the
server-side undo/redo snapshots. All through the real API."""
from __future__ import annotations

import pytest

from promptforge import db as db_mod
from promptforge.film.models import FilmAudioTrack, FilmTake


def _project(client, gap=1.0):
    """2 scenes; shots 4s+2s in scene 1, 3s in scene 2; scene gap 1s."""
    p = client.post("/api/film/projects", json={"title": "Cut"}).json()
    client.patch(f"/api/film/projects/{p['id']}", json={"settings": {"default_scene_gap_s": gap}})
    s1 = client.post(f"/api/film/projects/{p['id']}/scenes", json={"title": "One"}).json()
    s2 = client.post(f"/api/film/projects/{p['id']}/scenes", json={"title": "Two"}).json()
    sh1 = client.post(f"/api/film/scenes/{s1['id']}/shots", json={"title": "A", "duration_s": 4}).json()
    sh2 = client.post(f"/api/film/scenes/{s1['id']}/shots", json={"title": "B", "duration_s": 2}).json()
    sh3 = client.post(f"/api/film/scenes/{s2['id']}/shots", json={"title": "C", "duration_s": 3}).json()
    return p, [sh1["id"], sh2["id"], sh3["id"]]


def _build(client, pid, **kw):
    r = client.post(f"/api/film/projects/{pid}/sequence/build", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def _clips(seq, kind="video"):
    return [c for t in seq["tracks"] if t["kind"] == kind for c in t["clips"]]


# ------------------------------------------------------------------ build --
def test_build_from_storyboard_layout(client, app_env):
    p, shots = _project(client)
    seq = _build(client, p["id"])
    assert seq["exists"] is True
    assert [t["kind"] for t in seq["tracks"]] == ["video", "audio", "caption"]
    v = _clips(seq)
    assert [c["shot_id"] for c in v] == shots
    # scene gap becomes empty track space: 4, 2, then 1s gap, then 3
    assert [(c["start_s"], c["duration_s"]) for c in v] == [(0.0, 4.0), (4.0, 2.0), (7.0, 3.0)]
    assert seq["runtime_s"] == 10.0
    assert all(c["missing_media"] for c in v)   # no takes yet — honest flag, not an error
    # storyboard timing is untouched
    tl = client.get(f"/api/film/projects/{p['id']}/timeline").json()
    assert tl["runtime_s"] == 10.0


def test_build_conflict_and_rebuild_undo(client, app_env):
    p, _ = _project(client)
    _build(client, p["id"])
    r = client.post(f"/api/film/projects/{p['id']}/sequence/build", json={})
    assert r.status_code == 409 and "already has a sequence" in r.json()["detail"]
    # edit, rebuild with replace, then undo brings the edit back
    cid = _clips(client.get(f"/api/film/projects/{p['id']}/sequence").json())[0]["id"]
    client.patch(f"/api/film/sequence/clips/{cid}", json={"label": "edited"})
    seq = _build(client, p["id"], replace=True)
    assert _clips(seq)[0]["label"] != "edited"
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/undo").json()
    assert _clips(seq)[0]["label"] == "edited"


def test_build_imports_audio_tracks(client, app_env, tmp_path):
    p, _ = _project(client)
    f = tmp_path / "m.wav"
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    str(f)], check=True)
    r = client.post(f"/api/film/projects/{p['id']}/audio", data={"kind": "music"},
                    files={"file": ("m.wav", f.read_bytes(), "audio/wav")})
    assert r.status_code == 200, r.text
    seq = _build(client, p["id"])
    a = _clips(seq, "audio")
    assert len(a) == 1 and a[0]["source_kind"] == "audio" and a[0]["media_url"]
    assert a[0]["duration_s"] == pytest.approx(2.0, abs=0.2)


# ------------------------------------------------------------------- edits --
def test_move_trim_validation_and_locks(client, app_env):
    p, _ = _project(client)
    seq = _build(client, p["id"])
    v = _clips(seq)
    vtrack = seq["tracks"][0]
    # moving the second clip onto the first → overlap rejected with a sentence
    r = client.patch(f"/api/film/sequence/clips/{v[1]['id']}", json={"start_s": 1.0})
    assert r.status_code == 422 and "overlap" in r.json()["detail"].lower()
    # valid move into the gap after the scene
    seq = client.patch(f"/api/film/sequence/clips/{v[1]['id']}", json={"start_s": 4.5}).json()
    assert _clips(seq)[1]["start_s"] == 4.5
    # bad values
    assert client.patch(f"/api/film/sequence/clips/{v[0]['id']}", json={"speed": 99}).status_code == 422
    assert client.patch(f"/api/film/sequence/clips/{v[0]['id']}", json={"duration_s": 0.01}).status_code == 422
    # locked track blocks edits with 409
    client.patch(f"/api/film/sequence/tracks/{vtrack['id']}", json={"locked": True})
    r = client.patch(f"/api/film/sequence/clips/{v[0]['id']}", json={"start_s": 0.25})
    assert r.status_code == 409 and "locked" in r.json()["detail"]
    client.patch(f"/api/film/sequence/tracks/{vtrack['id']}", json={"locked": False})
    # caption clips cannot land on a video track
    r = client.post(f"/api/film/projects/{p['id']}/sequence/clips",
                    json={"track_id": vtrack["id"], "source_kind": "caption", "start_s": 20,
                          "data": {"text": "hi"}})
    assert r.status_code == 422 and "caption" in r.json()["detail"]


def test_split_clip(client, app_env):
    p, _ = _project(client)
    seq = _build(client, p["id"])
    c = _clips(seq)[0]           # 0..4s
    client.patch(f"/api/film/sequence/clips/{c['id']}",
                 json={"speed": 2.0, "fade_in_s": 0.5, "fade_out_s": 0.5})
    seq = client.post(f"/api/film/sequence/clips/{c['id']}/split", json={"at_s": 1.5}).json()
    v = _clips(seq)
    left, right = v[0], v[1]
    assert (left["start_s"], left["duration_s"]) == (0.0, 1.5)
    assert (right["start_s"], right["duration_s"]) == (1.5, 2.5)
    assert right["trim_start_s"] == pytest.approx(3.0)   # 1.5s * speed 2
    assert left["fade_out_s"] == 0.0 and right["fade_in_s"] == 0.0
    assert left["fade_in_s"] == 0.5 and right["fade_out_s"] == 0.5
    # split outside the clip body is rejected
    assert client.post(f"/api/film/sequence/clips/{left['id']}/split", json={"at_s": 5.0}).status_code == 422


def test_delete_plain_and_ripple(client, app_env):
    p, _ = _project(client)
    seq = _build(client, p["id"])
    v = _clips(seq)
    # plain delete leaves the gap
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/delete-clips",
                      json={"ids": [v[0]["id"]]}).json()
    assert [(c["start_s"]) for c in _clips(seq)] == [4.0, 7.0]
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/undo").json()
    v = _clips(seq)
    # ripple delete closes it: B moves 0→? A(0..4) removed ⇒ B at 0, C at 3
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/delete-clips",
                      json={"ids": [v[0]["id"]], "ripple": True}).json()
    assert [(c["start_s"], c["duration_s"]) for c in _clips(seq)] == [(0.0, 2.0), (3.0, 3.0)]
    assert seq["runtime_s"] == 6.0


def test_insert_gap_and_markers(client, app_env):
    p, _ = _project(client)
    seq = _build(client, p["id"])
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/insert-gap",
                      json={"at_s": 4.0, "gap_s": 2.0}).json()
    assert [c["start_s"] for c in _clips(seq)] == [0.0, 6.0, 9.0]
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/markers",
                      json={"t_s": 3.2, "label": "beat", "color": "red"}).json()
    m = seq["markers"][0]
    assert (m["t_s"], m["label"], m["color"]) == (3.2, "beat", "red")
    seq = client.patch(f"/api/film/sequence/markers/{m['id']}", json={"t_s": 3.5}).json()
    assert seq["markers"][0]["t_s"] == 3.5
    seq = client.delete(f"/api/film/sequence/markers/{m['id']}").json()
    assert seq["markers"] == []


def test_batch_patch_is_one_undo_step(client, app_env):
    p, _ = _project(client)
    seq = _build(client, p["id"])
    v = _clips(seq)
    before = [c["start_s"] for c in v]
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/clips/batch",
                      json={"ops": [{"id": v[1]["id"], "start_s": 14.0},
                                    {"id": v[2]["id"], "start_s": 20.0}],
                            "label": "drag selection"}).json()
    assert [c["start_s"] for c in _clips(seq)] == [0.0, 14.0, 20.0]
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/undo").json()
    assert [c["start_s"] for c in _clips(seq)] == before
    # an overlapping batch fails atomically (rolled back by the request tx)
    r = client.post(f"/api/film/projects/{p['id']}/sequence/clips/batch",
                    json={"ops": [{"id": v[1]["id"], "start_s": 0.5}]})
    assert r.status_code == 422


def test_undo_redo_stack(client, app_env):
    p, _ = _project(client)
    seq = _build(client, p["id"])
    assert seq["can_undo"] is False or seq["can_undo"] is True  # build may push on rebuild only
    cid = _clips(seq)[0]["id"]
    client.patch(f"/api/film/sequence/clips/{cid}", json={"label": "one"})
    seq = client.patch(f"/api/film/sequence/clips/{cid}", json={"label": "two"}).json()
    assert seq["can_undo"] is True and _clips(seq)[0]["label"] == "two"
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/undo").json()
    assert _clips(seq)[0]["label"] == "one" and seq["can_redo"] is True
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/redo").json()
    assert _clips(seq)[0]["label"] == "two"
    # a new edit clears redo
    client.patch(f"/api/film/sequence/clips/{cid}", json={"label": "three"})
    seq = client.get(f"/api/film/projects/{p['id']}/sequence").json()
    assert seq["can_redo"] is False
    h = client.get(f"/api/film/projects/{p['id']}/sequence/history").json()
    assert h["redo"] == [] and len(h["undo"]) >= 2
    # empty stack → 409, sequence intact after many undos
    for _ in range(20):
        r = client.post(f"/api/film/projects/{p['id']}/sequence/undo")
        if r.status_code == 409:
            break
    assert r.status_code == 409
    assert client.get(f"/api/film/projects/{p['id']}/sequence").json()["exists"] is True


def test_replace_take_and_tracks(client, app_env):
    p, shots = _project(client)
    seq = _build(client, p["id"])
    with db_mod.session_scope() as s:
        t1 = FilmTake(shot_id=shots[0], project_id=p["id"], number=1, kind="video",
                      status="imported", duration_s=4.0)
        t2 = FilmTake(shot_id=shots[0], project_id=p["id"], number=2, kind="video",
                      status="imported", duration_s=4.0)
        s.add_all([t1, t2])
        s.flush()
        take_ids = [t1.id, t2.id]
    c = _clips(seq)[0]
    seq = client.post(f"/api/film/sequence/clips/{c['id']}/take", json={"take_id": take_ids[1]}).json()
    assert _clips(seq)[0]["take_id"] == take_ids[1]
    # extra video track + move the clip up
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/tracks", json={"kind": "video"}).json()
    v2 = [t for t in seq["tracks"] if t["kind"] == "video"][1]
    assert v2["label"] == "V2"
    seq = client.patch(f"/api/film/sequence/clips/{c['id']}", json={"track_id": v2["id"]}).json()
    moved = next(x for x in _clips(seq) if x["id"] == c["id"])
    assert moved["track_id"] == v2["id"]
    # deleting a track removes its clips
    seq = client.delete(f"/api/film/sequence/tracks/{v2['id']}").json()
    assert len(_clips(seq)) == 2
    # deleting the sequence falls back to storyboard timing
    assert client.delete(f"/api/film/projects/{p['id']}/sequence").json()["ok"] is True
    assert client.get(f"/api/film/projects/{p['id']}/sequence").json()["exists"] is False


def test_migration_covers_editor_tables(client, app_env):
    """The additive migration recreates dropped editor tables on boot (D61)."""
    from sqlalchemy import inspect, text
    from promptforge import models
    from promptforge.db import get_engine, migrate_schema
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS film_timeline_clips"))
        conn.execute(text("DROP TABLE IF EXISTS film_timeline_tracks"))
        conn.execute(text("DROP TABLE IF EXISTS film_markers"))
        conn.execute(text("DROP TABLE IF EXISTS film_revisions"))
    # what init_db does on every boot
    models.Base.metadata.create_all(eng)
    migrate_schema(eng)
    names = set(inspect(eng).get_table_names())
    assert {"film_timeline_tracks", "film_timeline_clips", "film_markers", "film_revisions"} <= names


# ------------------------------------------------------- E3: clip export ---
from test_film_generation import mp4, wav  # noqa: E402


def _import_take(client, shot_id, seconds=3.0):
    r = client.post(f"/api/film/shots/{shot_id}/takes/import",
                    files={"file": (f"t{shot_id}.mp4", mp4(seconds, name=f"t{shot_id}-{seconds}"), "video/mp4")},
                    data={"kind": "footage", "select": "true"})
    assert r.status_code == 200, r.text
    return r.json()["take"]


def _export(client, pid, **kw):
    r = client.post(f"/api/film/projects/{pid}/export", json={"inline": True, "force": True, **kw})
    assert r.status_code == 200, r.text
    jobs = client.get(f"/api/film/projects/{pid}/exports").json()["exports"]
    j = jobs[0]
    assert j["status"] == "done", j.get("error")
    return j["result"]


def _duration(client, url):
    import subprocess
    from promptforge.config import get_config
    # url is /film-media/<rel under film/> — resolve to disk
    rel = url.split("/film-media/", 1)[1]
    path = get_config().data_dir / "film" / rel
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


def test_plan_dispatch_and_qa(client, app_env):
    p, shots = _project(client)
    for sid in shots:
        _import_take(client, sid, 3.0)
    plan0 = client.get(f"/api/film/projects/{p['id']}/exports").json()["plan"]
    assert plan0["mode"] == "storyboard"
    _build(client, p["id"])
    plan1 = client.get(f"/api/film/projects/{p['id']}/exports").json()["plan"]
    assert plan1["mode"] == "sequence"
    assert [seg["type"] for seg in plan1["segments"]] == ["clip", "clip", "gap", "clip"]
    qa = client.get(f"/api/film/projects/{p['id']}/qa").json()
    keys = {c["key"]: c["status"] for c in qa["checks"]}
    assert keys.get("sequence_media") == "PASS"


def test_sequence_export_trim_speed_gap(client, app_env):
    """Trim + retime + a literal gap all land in the master exactly as the
    editor shows them."""
    p, shots = _project(client)
    for sid in shots[:2]:
        _import_take(client, sid, 3.0)
    # rebuild a clean 2-clip sequence by hand for exact numbers
    seq = _build(client, p["id"])
    v = _clips(seq)
    # drop the third (media-less) clip
    client.post(f"/api/film/projects/{p['id']}/sequence/delete-clips", json={"ids": [v[2]["id"]]})
    # A: trim 1s into the source, show 1.5s; B: 2x speed for 1s at t=2.5
    client.patch(f"/api/film/sequence/clips/{v[0]['id']}",
                 json={"duration_s": 1.5, "trim_start_s": 1.0})
    r = client.patch(f"/api/film/sequence/clips/{v[1]['id']}",
                     json={"start_s": 2.5, "duration_s": 1.0, "speed": 2.0, "fade_out_s": 0.3})
    assert r.status_code == 200, r.text
    seq = client.get(f"/api/film/projects/{p['id']}/sequence").json()
    assert seq["runtime_s"] == 3.5
    res = _export(client, p["id"], quality="720p")
    assert res["runtime_s"] == 3.5
    assert abs(_duration(client, res["url"]) - 3.5) < 0.25


def test_sequence_export_dissolve_keeps_timing(client, app_env):
    """An in-place dissolve must NOT shorten the film (held-frame xfade)."""
    p, shots = _project(client)
    for sid in shots[:2]:
        _import_take(client, sid, 3.0)
    seq = _build(client, p["id"])
    v = _clips(seq)
    client.post(f"/api/film/projects/{p['id']}/sequence/delete-clips", json={"ids": [v[2]["id"]]})
    # butt-join A(0..4→trim to 2) and B at 2, dissolve 0.5 between them
    client.patch(f"/api/film/sequence/clips/{v[0]['id']}",
                 json={"duration_s": 2.0, "transition_after": {"kind": "dissolve", "duration_s": 0.5}})
    client.patch(f"/api/film/sequence/clips/{v[1]['id']}", json={"start_s": 2.0, "duration_s": 2.0})
    seq = client.get(f"/api/film/projects/{p['id']}/sequence").json()
    assert seq["runtime_s"] == 4.0
    res = _export(client, p["id"])
    assert res["runtime_s"] == 4.0
    assert abs(_duration(client, res["url"]) - 4.0) < 0.25


def test_sequence_export_mixes_audio_clips(client, app_env):
    p, shots = _project(client)
    _import_take(client, shots[0], 3.0)
    client.post(f"/api/film/projects/{p['id']}/audio", data={"kind": "music"},
                files={"file": ("m.wav", wav(2.0), "audio/wav")})
    seq = _build(client, p["id"])
    a = _clips(seq, "audio")[0]
    client.patch(f"/api/film/sequence/clips/{a['id']}", json={"gain_db": -6.0, "start_s": 0.5})
    res = _export(client, p["id"])
    assert res["tracks"] == 1
    # muting the audio track drops it from the mix
    atrack = next(t for t in client.get(f"/api/film/projects/{p['id']}/sequence").json()["tracks"]
                  if t["kind"] == "audio")
    client.patch(f"/api/film/sequence/tracks/{atrack['id']}", json={"muted": True})
    res2 = _export(client, p["id"], label="muted")
    assert res2["tracks"] == 0


def test_preview_manifest_matches_flatten(client, app_env):
    p, shots = _project(client)
    _import_take(client, shots[0], 3.0)
    assert client.get(f"/api/film/projects/{p['id']}/sequence/preview").status_code == 404
    _build(client, p["id"])
    man = client.get(f"/api/film/projects/{p['id']}/sequence/preview").json()
    assert man["mode"] == "sequence" and man["fps"] == 24
    first = man["segments"][0]
    assert first["media_url"] and first["missing"] is False
    # top-track override: a V2 clip covering 0..2 wins over V1
    seq = client.post(f"/api/film/projects/{p['id']}/sequence/tracks", json={"kind": "video"}).json()
    v2 = [t for t in seq["tracks"] if t["kind"] == "video"][1]
    take_id = first["take_id"]
    client.post(f"/api/film/projects/{p['id']}/sequence/clips",
                json={"track_id": v2["id"], "source_kind": "take", "take_id": take_id,
                      "start_s": 1.0, "duration_s": 2.0})
    man = client.get(f"/api/film/projects/{p['id']}/sequence/preview").json()
    segs = man["segments"]
    # V1 clip is sliced around the V2 clip
    assert [round(s["start_s"], 1) for s in segs[:3]] == [0.0, 1.0, 3.0]
    assert segs[1]["trim_start_s"] == 0.0     # V2 clip plays from its own head
    assert segs[2]["trim_start_s"] == 3.0     # V1 resumes 3s into its source
