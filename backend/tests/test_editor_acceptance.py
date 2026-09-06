"""Editor acceptance journey (E8 — the spec's product test, API half):
storyboard → build sequence → every edit op → review queue → QC → export
(ffprobe-verified against the editor's own timing) → simulated restart with
the edit, history and review decisions intact."""
from __future__ import annotations

from promptforge import config as cfg_mod
from promptforge import db as db_mod
from test_film_editor import _build, _clips, _duration, _export, _import_take, _project


def test_editor_full_journey(client, app_env):
    # 1–3: storyboard with takes
    p, shots = _project(client)          # 4s + 2s | gap 1s | 3s
    pid = p["id"]
    for sid in shots:
        _import_take(client, sid, 3.0)

    # 4: build the sequence from the storyboard
    seq = _build(client, pid)
    assert seq["runtime_s"] == 10.0 and len(_clips(seq)) == 3

    # 5–9: edit — trim A, retime B, ripple-delete C, split, move
    v = _clips(seq)
    client.patch(f"/api/film/sequence/clips/{v[0]['id']}", json={"duration_s": 2.0, "trim_start_s": 0.5})
    client.patch(f"/api/film/sequence/clips/{v[1]['id']}", json={"start_s": 2.0, "speed": 2.0, "duration_s": 1.0})
    seq = client.post(f"/api/film/projects/{pid}/sequence/delete-clips",
                      json={"ids": [v[2]["id"]], "ripple": True}).json()
    assert seq["runtime_s"] == 3.0
    seq = client.post(f"/api/film/sequence/clips/{v[0]['id']}/split", json={"at_s": 1.0}).json()
    assert len(_clips(seq)) == 3
    # 10: markers + caption + effects
    client.post(f"/api/film/projects/{pid}/sequence/markers", json={"t_s": 1.5, "label": "beat"})
    cap = next(t for t in seq["tracks"] if t["kind"] == "caption")
    client.post(f"/api/film/projects/{pid}/sequence/clips",
                json={"track_id": cap["id"], "source_kind": "caption", "start_s": 0.2,
                      "duration_s": 1.0, "data": {"text": "Opening"}})
    client.patch(f"/api/film/sequence/clips/{v[1]['id']}", json={"effects": {"scale": 0.8, "opacity": 0.9}})

    # 11: undo/redo work and history is server-side
    before = client.get(f"/api/film/projects/{pid}/sequence").json()
    seq = client.post(f"/api/film/projects/{pid}/sequence/undo").json()
    assert _clips(seq, "video")[-1].get("effects") == {}
    seq = client.post(f"/api/film/projects/{pid}/sequence/redo").json()
    assert next(c for c in _clips(seq) if c["id"] == v[1]["id"])["effects"] == {"scale": 0.8, "opacity": 0.9}
    assert seq["runtime_s"] == before["runtime_s"]

    # 12: review queue — approve two, reject one
    q = client.get(f"/api/film/projects/{pid}/review-queue").json()
    assert q["counts"]["pending"] == 3
    items = q["pending"]
    client.post(f"/api/film/takes/{items[0]['take']['id']}/review", json={"status": "approved"})
    client.post(f"/api/film/takes/{items[1]['take']['id']}/review",
                json={"status": "rejected", "note": "wrong framing"})

    # 13: QC includes sequence rows and passes on media
    qa = client.get(f"/api/film/projects/{pid}/qa").json()
    keys = {c["key"]: c["status"] for c in qa["checks"]}
    assert keys["sequence_media"] == "PASS"

    # 14: export renders EXACTLY the editor's timing
    res = _export(client, pid, label="cut-v1")
    assert res["runtime_s"] == 3.0
    assert abs(_duration(client, res["url"]) - 3.0) < 0.25

    # 15: restart — sequence, markers, caption, history and reviews persist
    db_mod.dispose_db()
    cfg_mod.set_config(cfg_mod.Config(data_dir=app_env.data_dir))
    db_mod.init_db()
    from fastapi.testclient import TestClient
    from promptforge.main import create_app
    with TestClient(create_app()) as c2:
        seq2 = c2.get(f"/api/film/projects/{pid}/sequence").json()
        assert seq2["exists"] and seq2["runtime_s"] == 3.0
        assert [m["label"] for m in seq2["markers"]] == ["beat"]
        caps = c2.get(f"/api/film/projects/{pid}/sequence/preview").json()["captions"]
        assert caps and caps[0]["text"] == "Opening"
        assert seq2["can_undo"] is True            # snapshot history survived
        undone = c2.post(f"/api/film/projects/{pid}/sequence/undo").json()
        assert undone["exists"] is True
        q2 = c2.get(f"/api/film/projects/{pid}/review-queue").json()
        assert q2["counts"]["pending"] == 1 and len(q2["decided"]) == 2
        assert c2.get(f"/api/film/projects/{pid}/exports").json()["exports"][0]["status"] == "done"
