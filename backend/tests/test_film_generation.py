"""Phase S3 — provider capabilities + scoring, budget control, takes through
the existing generation queue (frames, chaining, imports, compare), local
media (stills, cards), footage corpus + stock search (mocked HTTP), audio
tracks, subtitles, QA + repair queue, export with gaps/dissolves/audio/
burn-in, reference-video analysis + proposal, sample/batch runs."""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import httpx
import pytest
from PIL import Image

from promptforge import db as db_mod
from promptforge import settings_store
from promptforge.film import (assets as asset_svc, capabilities, costs, export as export_svc, footage,
                              gates, graphics, jobs, production, projects as proj_svc, qa, reference,
                              scoring, subtitles as sub_svc, takes as take_svc)
from promptforge.film.models import FilmJob, FilmShot, FilmTake
from promptforge.generation import queue as gen_queue
from promptforge.generation import router as gen_router
from promptforge.generation.base import ProviderError

SCRATCH = Path("/tmp/claude-0/-home-user-PF2/df08b266-09dd-5b0a-8a74-61e636895d83/scratchpad/media")


def _ffmpeg(args: list[str], out: Path) -> bytes:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args, str(out)], check=True, capture_output=True, timeout=120)
    return out.read_bytes()


def mp4(seconds: float = 1.0, pattern: str = "testsrc", size: str = "320x180", name: str = "clip") -> bytes:
    src = f"{pattern}=size={size}:rate=24" if pattern == "testsrc" else f"color=c={pattern}:s={size}:r=24"
    return _ffmpeg(["-f", "lavfi", "-i", src, "-t", f"{seconds}", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                    "-preset", "ultrafast"], SCRATCH / f"{name}.mp4")


def mp4_cuts(name: str = "cuts") -> bytes:
    """Three 1-second colour blocks → two hard cuts."""
    return _ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=1", "-f", "lavfi", "-i",
                    "color=c=blue:s=320x180:r=24:d=1", "-f", "lavfi", "-i", "color=c=green:s=320x180:r=24:d=1",
                    "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast"], SCRATCH / f"{name}.mp4")


def wav(seconds: float = 2.0) -> bytes:
    return _ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}", "-ac", "2"],
                   SCRATCH / "tone.wav")


def png(w=64, h=48, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _connect(names):
    with db_mod.session_scope() as s:
        for n in names:
            settings_store.put(s, {"fal": "fal_api_key", "replicate": "replicate_api_token",
                                   "wavespeed": "wavespeed_api_key"}[n], "key-" + n)


class FakeProvider:
    name = "fal"
    label = "fal.ai"

    def __init__(self):
        self.submits: list[dict] = []
        self.fail_next = False

    def get_key(self, s):
        return "key"

    def is_configured(self, s):
        return True

    def submit(self, key, model_id, prompt, negative, params, kind):
        self.submits.append({"model_id": model_id, "prompt": prompt, "negative": negative, "params": params, "kind": kind})
        if self.fail_next:
            self.fail_next = False
            raise ProviderError("fal.ai rejected the request (422): bad size", "params")
        return f"job-{len(self.submits)}-{kind}"

    def poll(self, key, model_id, job_ref):
        return {"status": "succeeded", "output_url": f"https://cdn.fake/{job_ref}." + ("mp4" if job_ref.endswith("video") else "png")}


@pytest.fixture()
def providers(app_env, monkeypatch):
    _connect(["fal", "wavespeed"])
    fake = FakeProvider()
    monkeypatch.setattr(gen_router, "get_provider", lambda name: fake)
    video, image = mp4(1.0), png(512, 288)
    real = httpx.Client
    counter = {"n": 0}

    def handler(req):
        if req.url.path.endswith(".mp4"):
            return httpx.Response(200, content=video)
        counter["n"] += 1                       # every image output is a distinct picture
        return httpx.Response(200, content=png(512, 288, (200, 30, (counter["n"] * 40) % 255)))

    monkeypatch.setattr("promptforge.generation.queue.httpx.Client",
                        lambda **kw: real(transport=httpx.MockTransport(handler)))
    return fake


def _project(client, title="Gen", settings=None, shots=(("A", 2.0), ("B", 1.5))):
    p = client.post("/api/film/projects", json={"title": title, "settings": settings or {}}).json()
    sc = client.post(f"/api/film/projects/{p['id']}/scenes", json={"title": "Scene"}).json()
    ids = [client.post(f"/api/film/scenes/{sc['id']}/shots", json={"title": t, "duration_s": d}).json()["id"]
           for t, d in shots]
    return p, sc, ids


# ------------------------------------------------------------ capabilities -
def test_capability_matrix_and_scoring(client, app_env):
    m = client.get("/api/film/capabilities").json()
    assert not any(x["supported"] for x in m["modes"]) and "connect one" in m["modes"][0]["reason"]
    assert m["extra"]["tts"]["supported"] is False and m["local"]["concat_export"]["supported"] is True
    _connect(["fal"])
    m = client.get("/api/film/capabilities").json()
    modes = {x["key"]: x for x in m["modes"]}
    assert modes["text_to_video"]["supported"] and "kling" in modes["start_end_to_video"]["families"]
    assert modes["storyboard_to_video"]["supported"] and modes["reference_to_video"]["supported"]
    assert m["providers"]["fal"]["connected"] and not m["providers"]["replicate"]["connected"]
    with db_mod.session_scope() as s:
        assert capabilities.supports(s, "kling", "fal", "start_end_to_video") == "fal-ai/kling-video/v2.1/pro/image-to-video"
        assert capabilities.supports(s, "kling", "fal", "storyboard_to_video") == "fal-ai/kling-video/v2.1/standard/image-to-video"
        assert capabilities.supports(s, "hunyuan", "fal", "start_end_to_video") is None
        assert capabilities.inputs_map("kling", "fal", "start_end_to_video") == {"image": "image_url", "end_image": "tail_image_url"}
        _connect(["wavespeed"])
        ranked = scoring.score_candidates(s, "text_to_video", "video", {"duration_s": 5, "resolution": "720p"}, "kling")
        assert [c["provider"] for c in ranked] == ["wavespeed", "fal"]          # same tier, cheaper first
        assert ranked[0]["scores"]["cost"] == 1.0 and "cheapest option" in " ".join(ranked[0]["reasons"])
        assert ranked[0]["basis"].startswith("priors") and ranked[0]["scores"]["consistency"] == 1.0
        best, _ = scoring.pick(s, "text_to_video", "video", {"duration_s": 5}, provider="fal")
        assert best["provider"] == "fal"
        d = scoring.decision(best, ranked, user_override=True)
        assert d["user_override"] and d["selected"]["provider"] == "fal" and d["alternatives"]
        assert scoring.score_candidates(s, "reference_to_image", "image", {}, "sdxl") == []   # not declared


# ------------------------------------------------------------------- takes -
def test_takes_ride_the_generation_queue_with_frames_and_chaining(client, app_env, providers):
    p, sc, (a, b) = _project(client, settings={"aspect_ratio": "16:9", "budget": {"mode": "observe"}})
    client.patch(f"/api/film/shots/{b}", json={"chain_from_previous": True})
    with db_mod.session_scope() as s:
        jack = asset_svc.create_asset(s, "character", "Jack", data={"eyes": "green"})
        jid = jack.id
    client.post(f"/api/film/assets/{jid}/refs", files={"file": ("p.png", png(), "image/png")}, data={"kind": "portrait"})
    client.post(f"/api/film/shots/{a}/assets", json={"asset_id": jid})

    r = client.post(f"/api/film/shots/{a}/takes", json={"kind": "video"})
    assert r.status_code == 200, r.text
    take = r.json()["take"]
    assert take["status"] == "queued" and take["provider"] == "wavespeed" and take["mode"] == "reference_to_video"
    assert take["cost_estimate"] == 0.092 and take["decision"]["selected"]["provider"] == "wavespeed"
    assert take["context"]["assets"][0]["name"] == "Jack" and take["params"]["inputs"]["references"]
    assert "Jack (character v1)" in take["prompt"] and r.json()["shot"]["status"] == "framed"
    ev = client.get(f"/api/film/projects/{p['id']}/events?kind=cost").json()["events"]
    assert any(e["title"].startswith("Reserved $0.092") for e in ev)

    gen_queue.process_generation(take["generation_id"])
    assert providers.submits[-1]["kind"] == "video" and providers.submits[-1]["params"]["duration_s"] == 2.0
    assert providers.submits[-1]["params"]["_inputs"]["image"].endswith(".png")
    assert providers.submits[-1]["params"]["_input_map"] == {"image": "image"}
    assert providers.submits[-1]["params"]["_film_take_id"] == take["id"]
    shot = client.get(f"/api/film/shots/{a}").json()
    assert shot["status"] == "generated" and shot["selected_take_id"] == take["id"]
    t = shot["selected_take"]
    assert t["status"] == "succeeded" and t["media_url"].startswith("/media/promptforge/") and t["thumb_url"]
    assert t["cost_actual"] == 0.092 and t["qa"]["verdict"] in ("PASS", "WARN")
    assert t["params"]["last_frame_path"].startswith(f"film/projects/{p['id']}/frames/")
    # the chained next shot got the last frame as its start frame automatically
    nxt = client.get(f"/api/film/shots/{b}").json()
    assert nxt["start_frame"]["kind"] == "previous_shot" and nxt["start_frame"]["source_shot_id"] == a
    assert nxt["start_frame"]["path"] == t["params"]["last_frame_path"]
    # generating B now uses image_to_video with that frame; an end frame upgrades to start/end
    client.post(f"/api/film/shots/{b}/frames/end_frame/upload", files={"file": ("e.png", png(), "image/png")})
    r = client.post(f"/api/film/shots/{b}/takes", json={"kind": "video", "provider": "fal"}).json()
    assert r["take"]["mode"] == "start_end_to_video" and r["take"]["provider"] == "fal"
    assert r["take"]["params"]["inputs"]["end_image"] and r["take"]["cost_estimate"] == 0.135   # pro tier price
    assert r["take"]["decision"]["user_override"] is True
    gen_queue.process_generation(r["take"]["generation_id"])
    sub = providers.submits[-1]["params"]
    assert sub["_mode"] == "start_end_to_video" and sub["_input_map"]["end_image"] == "tail_image_url"
    # frame takes set the shot frame; a second video take is an alternate, not a replacement
    fr = client.post(f"/api/film/shots/{a}/frames/start_frame/generate", json={}).json()["take"]
    assert fr["kind"] == "start_frame" and fr["mode"] == "reference_to_image"
    gen_queue.process_generation(fr["generation_id"])
    shot = client.get(f"/api/film/shots/{a}").json()
    assert shot["start_frame"]["kind"] == "generated" and shot["start_frame"]["take_id"] == fr["id"]
    alt = client.post(f"/api/film/shots/{a}/takes", json={"kind": "video", "instruction": "brighter",
                                                          "change": ["lighting"], "preserve": ["face"]}).json()["take"]
    assert "Change only: lighting" in alt["prompt"] and alt["mode"] == "image_to_video"
    gen_queue.process_generation(alt["generation_id"])
    listing = client.get(f"/api/film/shots/{a}/takes").json()
    assert [t["kind"] for t in listing["takes"]] == ["video", "start_frame", "video"]
    assert listing["selected_take_id"] == take["id"]                       # first take stays selected
    sel = client.post(f"/api/film/takes/{alt['id']}/select").json()
    assert sel["selected_take_id"] == alt["id"]
    cmp = client.get(f"/api/film/takes/{take['id']}/compare/{alt['id']}").json()
    assert "prompt" in cmp["differences"] and cmp["a"]["provider"] == "wavespeed"
    # a failed take never touches the selected one
    providers.fail_next = True
    bad = client.post(f"/api/film/shots/{a}/takes", json={"kind": "video"}).json()["take"]
    gen_queue.process_generation(bad["generation_id"])
    bad = client.get(f"/api/film/takes/{bad['id']}").json()
    assert bad["status"] == "failed" and "422" in bad["error"]
    assert client.get(f"/api/film/shots/{a}").json()["selected_take_id"] == alt["id"]
    spend = client.get(f"/api/film/projects/{p['id']}/costs").json()
    assert spend["spent_usd"] > 0 and spend["by_provider"]["wavespeed"] > 0 and spend["by_shot"][str(a)] > 0
    # "use previous shot's last frame" explicitly + lock protects it
    client.post(f"/api/film/shots/{b}/frames/start_frame", json={"kind": "lock", "locked": True})
    assert client.post(f"/api/film/shots/{b}/frames/start_frame", json={"kind": "previous_shot"}).status_code == 422
    client.post(f"/api/film/shots/{b}/frames/start_frame", json={"kind": "lock", "locked": False})
    fr2 = client.post(f"/api/film/shots/{b}/frames/start_frame", json={"kind": "previous_shot"}).json()
    assert fr2["start_frame"]["take_id"] == alt["id"]
    assert client.post(f"/api/film/shots/{a}/frames/start_frame", json={"kind": "previous_shot"}).status_code == 422


def test_budget_modes_strategy_and_continuity_block_generation(client, app_env, providers):
    p, sc, (a, b) = _project(client, settings={"budget": {"mode": "cap", "cap_usd": 0.05, "threshold_usd": 0.01}})
    r = client.post(f"/api/film/shots/{a}/takes", json={"kind": "video"})
    assert r.status_code == 409 and "Hard cap" in r.json()["detail"]["message"]
    assert r.json()["detail"]["budget"]["allowed"] is False
    client.patch(f"/api/film/projects/{p['id']}", json={"settings": {"budget": {"mode": "approve", "threshold_usd": 0.01}}})
    r = client.post(f"/api/film/shots/{a}/takes", json={"kind": "video"})
    assert r.status_code == 409 and r.json()["detail"]["budget"]["requires_approval"] is True
    r = client.post(f"/api/film/shots/{a}/takes", json={"kind": "video", "approve_cost": True})
    assert r.status_code == 200
    chk = client.post(f"/api/film/projects/{p['id']}/costs/check", json={"amount_usd": 1.0}).json()
    assert chk["requires_approval"] and chk["projected_usd"] > 1.0
    client.patch(f"/api/film/projects/{p['id']}", json={"settings": {"budget": {"mode": "warn", "threshold_usd": 0.01}}})
    assert client.post(f"/api/film/projects/{p['id']}/costs/check", json={"amount_usd": 1.0}).json()["warning"]
    # non-AI strategy → use the matching tool
    client.patch(f"/api/film/shots/{b}", json={"media_strategy": "stock"})
    r = client.post(f"/api/film/shots/{b}/takes", json={"kind": "video"})
    assert r.status_code == 422 and "Footage search" in r.json()["detail"]
    # strict continuity blocks
    client.patch(f"/api/film/shots/{b}", json={"media_strategy": "ai_video"})
    with db_mod.session_scope() as s:
        jack = asset_svc.create_asset(s, "character", "Jack")
        v2, _ = asset_svc.edit_version(s, jack, {"hair": "grey"}, force_new=True)
        proj_svc.pin_asset(s, s.get(FilmShot, a), jack, asset_svc.versions_of(s, jack.id)[0].id)
        proj_svc.pin_asset(s, s.get(FilmShot, b), jack, v2.id)
    client.patch(f"/api/film/projects/{p['id']}", json={"settings": {"continuity_mode": "strict"}})
    client.post(f"/api/film/projects/{p['id']}/continuity")
    r = client.post(f"/api/film/shots/{b}/takes", json={"kind": "video"})
    assert r.status_code == 409 and "Strict continuity" in r.json()["detail"]["message"]
    # no provider at all → honest 422
    with db_mod.session_scope() as s:
        settings_store.put(s, "fal_api_key", "")
        settings_store.put(s, "wavespeed_api_key", "")
    client.patch(f"/api/film/projects/{p['id']}", json={"settings": {"continuity_mode": "flexible"}})
    client.post(f"/api/film/projects/{p['id']}/continuity")
    r = client.post(f"/api/film/shots/{b}/takes", json={"kind": "video"})
    assert r.status_code == 422 and "connect fal.ai" in r.json()["detail"]


# ------------------------------------------------------- local media/imports
def test_imports_stills_cards_and_qa(client, app_env):
    p, sc, (a, b) = _project(client, shots=(("A", 1.0), ("B", 1.0)))
    up = client.post(f"/api/film/shots/{a}/takes/import", files={"file": ("f.mp4", mp4(1.0), "video/mp4")})
    assert up.status_code == 200, up.text
    t = up.json()["take"]
    assert t["status"] == "imported" and t["kind"] == "footage" and t["duration_s"] and t["thumb_url"]
    assert t["qa"]["verdict"] == "PASS" and up.json()["shot"]["selected_take_id"] == t["id"]
    assert t["params"]["last_frame_path"]
    # a black clip trips the (heuristic) black-frame check
    blk = client.post(f"/api/film/shots/{b}/takes/import", files={"file": ("k.mp4", mp4(1.0, "black", name="black"), "video/mp4")}).json()["take"]
    checks = {c["key"]: c for c in blk["qa"]["checks"]}
    assert checks["black_frames"]["status"] == "WARN" and checks["black_frames"]["heuristic"] is True
    assert client.post(f"/api/film/shots/{a}/takes/import", files={"file": ("x.txt", b"nope", "text/plain")}).status_code == 422
    # still → video (Ken Burns) and a title card, both local + free
    client.post(f"/api/film/shots/{b}/frames/start_frame/upload", files={"file": ("s.png", png(320, 180), "image/png")})
    st = client.post(f"/api/film/shots/{b}/still", json={"source": "start_frame"}).json()
    assert st["take"]["provider"] == "local" and st["take"]["mode"] == "still_to_video"
    assert abs(st["take"]["duration_s"] - 1.0) < 0.2 and st["shot"]["media_strategy"] == "still"
    card = client.post(f"/api/film/shots/{b}/card", json={"text": "RAINY CITY", "subtitle": "a film", "style": "title"}).json()
    assert card["take"]["kind"] == "graphics" and card["take"]["cost_estimate"] == 0
    assert card["shot"]["media_strategy"] == "still"          # strategy only auto-changes from ai_video
    with db_mod.session_scope() as s:
        tk = s.get(FilmTake, card["take"]["id"])
        info = qa.probe(take_svc.abs_path(tk.media_path))
        assert info["width"] == 1280 and abs(info["duration"] - 1.0) < 0.2
    lower = graphics.render_card("Jane Doe", "Director", "lower_third", "16:9")
    assert lower.size == (1280, 720)
    # project QA + repair queue
    rep = client.get(f"/api/film/projects/{p['id']}/qa").json()
    assert rep["verdict"] in ("PASS", "WARN") and {c["key"] for c in rep["checks"]} >= {"missing_media", "continuity", "subtitles"}
    with db_mod.session_scope() as s:
        tk = s.get(FilmTake, t["id"])
        take_svc.abs_path(tk.media_path).unlink()          # media vanished → FAIL → repair
    rep = client.get(f"/api/film/projects/{p['id']}/qa").json()
    assert rep["verdict"] == "FAIL" and rep["repairs"][0]["kind"] == "regenerate_shot"
    assert rep["repairs"][0]["entity_id"] == a and rep["repairs"][0]["action"].endswith(f"/shots/{a}/takes")
    assert client.get(f"/api/film/projects/{p['id']}/repairs").json()["repairs"][0]["entity_id"] == a


# ----------------------------------------------------------------- footage -
def test_footage_search_corpus_and_attach(client, app_env):
    with db_mod.session_scope() as s:
        settings_store.put(s, "pexels_api_key", "px")
        settings_store.put(s, "pixabay_api_key", "pb")
    clip_bytes = mp4(1.0, name="stock")

    def handler(req):
        host = req.url.host
        if host == "api.pexels.com":
            assert req.headers["Authorization"] == "px"
            return httpx.Response(200, json={"videos": [{"id": 11, "url": "https://www.pexels.com/video/11/", "duration": 12,
                                                         "image": "https://images.pexels.com/11.jpg", "user": {"name": "Ana"},
                                                         "video_files": [{"link": "https://cdn.pexels.com/11-720.mp4", "height": 720, "width": 1280},
                                                                         {"link": "https://cdn.pexels.com/11-4k.mp4", "height": 2160, "width": 3840}]}]})
        if host == "pixabay.com":
            return httpx.Response(500, text="boom")
        if host == "archive.org":
            return httpx.Response(200, json={"response": {"docs": [{"identifier": "city-night-1950", "title": "City at night",
                                                                    "description": ["Archival footage"], "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"}]}})
        if host == "images-api.nasa.gov":
            return httpx.Response(200, json={"collection": {"items": []}})
        if host == "commons.wikimedia.org":
            return httpx.Response(200, json={"query": {"pages": {}}})
        if host == "cdn.pexels.com":
            return httpx.Response(200, content=clip_bytes)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    src = {s_["key"]: s_ for s_ in client.get("/api/film/footage/sources").json()["sources"]}
    assert src["pexels"]["configured"] and not src["unsplash"]["configured"] and src["archive"]["configured"]
    with db_mod.session_scope() as s:
        out = footage.search(s, "city at night", media_type="video", transport=transport)
    assert {r["source"] for r in out["results"]} == {"pexels", "archive"} and out["errors"]["pixabay"].startswith("HTTPStatusError")
    px = next(r for r in out["results"] if r["source"] == "pexels")
    assert px["download_url"].endswith("11-720.mp4") and px["license"]["name"] == "Pexels License"
    assert px["attribution"] == "Video by Ana on Pexels"
    ar = next(r for r in out["results"] if r["source"] == "archive")
    assert ar["license"] == {"name": "as stated by the item", "url": "https://creativecommons.org/publicdomain/mark/1.0/"}
    assert out["needs_setup"] == []

    p, sc, (a, b) = _project(client, shots=(("A", 1.0), ("B", 1.0)))
    with db_mod.session_scope() as s:
        clip = footage.download_result(s, px, transport=transport)
        assert clip.source == "pexels" and clip.duration_s and clip.license["name"] == "Pexels License"
        assert footage.download_result(s, px, transport=transport).id == clip.id          # idempotent
        take = footage.attach_clip(s, s.get(FilmShot, a), clip)
        assert take.kind == "footage" and take.status == "imported"
        assert take.context["provenance"]["attribution"] == "Video by Ana on Pexels"
        assert s.get(FilmShot, a).media_strategy == "stock"
    # user footage: analysed, indexed and searchable by segment
    up = client.post("/api/film/footage/upload", files={"file": ("mine.mp4", mp4_cuts(), "video/mp4")},
                     data={"title": "Harbour at dawn", "description": "wide shot of the harbour, fog", "tags": "harbour,fog"})
    assert up.status_code == 200, up.text
    clip = up.json()
    assert len(clip["segments"]) == 3 and clip["pacing"]["shots"] == 3 and clip["license"]["name"] == "Your own footage"
    assert clip["notes"]["transcript_note"].startswith("No configured provider")
    hits = client.get("/api/film/footage/clips?q=wide harbour fog").json()["results"]
    assert hits and hits[0]["clip_id"] == clip["id"] and hits[0]["confidence"] > 0.5 and hits[0]["timecode"].startswith("0.00")
    assert client.get("/api/film/footage/clips?q=spaceship").json()["results"] == []
    att = client.post(f"/api/film/footage/clips/{clip['id']}/attach", json={"shot_id": b, "start_s": 1.0, "end_s": 2.0}).json()
    assert att["take"]["kind"] == "footage" and abs(att["take"]["duration_s"] - 1.0) < 0.2
    assert att["take"]["context"]["provenance"]["segment"] == {"start_s": 1.0, "end_s": 2.0}
    assert att["shot"]["media_strategy"] == "user_footage"


# ---------------------------------------------------- audio + subtitles ----
def test_audio_tracks_and_subtitles_follow_timing(client, app_env):
    p = client.post("/api/film/projects", json={"title": "Sub", "script": "INT. ROOM - DAY\n\nJACK\nWe go now.\n\nSARAH\nNot yet.\n"}).json()
    client.post(f"/api/film/projects/{p['id']}/story/import", json={"text": p["script"]})
    sc = client.get(f"/api/film/projects/{p['id']}").json()["scenes"][0]
    a = client.post(f"/api/film/scenes/{sc['id']}/shots", json={"duration_s": 4}).json()["id"]
    b = client.post(f"/api/film/scenes/{sc['id']}/shots", json={"duration_s": 4}).json()["id"]
    au = client.post(f"/api/film/projects/{p['id']}/audio", files={"file": ("tone.wav", wav(2.0), "audio/wav")},
                     data={"kind": "music", "anchor_kind": "shot", "anchor_id": str(b), "gain_db": "-6"})
    assert au.status_code == 200, au.text
    tr = au.json()
    assert abs(tr["duration_s"] - 2.0) < 0.1 and tr["start_s"] == 4.0 and tr["end_s"] == 6.0 and tr["gain_db"] == -6
    assert client.post(f"/api/film/projects/{p['id']}/audio", files={"file": ("x.txt", b"no", "text/plain")}).status_code == 422
    aud = client.get(f"/api/film/projects/{p['id']}/audio").json()
    assert aud["mix"]["by_kind"] == {"music": 1} and aud["capabilities"]["tts"]["supported"] is False
    tr = client.patch(f"/api/film/audio/{tr['id']}", json={"muted": True, "fade_in_s": 0.5}).json()
    assert tr["muted"] and client.get(f"/api/film/projects/{p['id']}/audio").json()["mix"]["tracks"] == []
    client.patch(f"/api/film/audio/{tr['id']}", json={"muted": False})
    subs = client.post(f"/api/film/projects/{p['id']}/subtitles/from-script").json()
    cues = subs["cues"]
    assert [c["text"] for c in cues] == ["We go now.", "Not yet."] and cues[0]["shot_id"] == a
    assert cues[0]["start_s"] == 0.0 and cues[1]["start_s"] == pytest.approx(4.8, abs=0.01)
    assert subs["validation"]["status"] == "PASS" and subs["source"] == "script"
    # shot A grows → anchored cues move with it after resync
    client.patch(f"/api/film/shots/{a}", json={"duration_s": 6})
    rs = client.post(f"/api/film/projects/{p['id']}/subtitles/resync").json()
    assert rs["cues"][1]["start_s"] == pytest.approx(6.8, abs=0.01)
    assert client.get(f"/api/film/projects/{p['id']}/audio").json()["tracks"][0]["start_s"] == 6.0
    srt = client.get(f"/api/film/projects/{p['id']}/subtitles.srt").text
    assert srt.startswith("1\n00:00:00,000 --> ") and "We go now." in srt
    vtt = client.get(f"/api/film/projects/{p['id']}/subtitles.vtt").text
    assert vtt.startswith("WEBVTT") and "00:00:06.800 --> " in vtt
    imp = client.post(f"/api/film/projects/{p['id']}/subtitles/import", json={"text": srt}).json()
    assert len(imp["cues"]) == 2 and imp["source"] == "imported"
    bad = client.put(f"/api/film/projects/{p['id']}/subtitles",
                     json={"cues": [{"start_s": 0, "end_s": 2, "text": "a"}, {"start_s": 1, "end_s": 3, "text": "b"}],
                           "burn_in": True, "style": {"font_size": 40, "bogus": 1}}).json()
    assert bad["validation"]["status"] == "WARN" and "overlaps" in bad["validation"]["message"]
    assert bad["burn_in"] is True and bad["style"]["font_size"] == 40 and "bogus" not in bad["style"]


# ------------------------------------------------------------------ export -
def test_export_renders_timeline_with_gaps_dissolves_audio_and_burn_in(client, app_env):
    p = client.post("/api/film/projects", json={"title": "Cut", "settings": {"default_scene_gap_s": 0.5, "fps": 24}}).json()
    s1 = client.post(f"/api/film/projects/{p['id']}/scenes", json={"title": "One", "transition": "fade_black"}).json()
    s2 = client.post(f"/api/film/projects/{p['id']}/scenes", json={"title": "Two"}).json()
    a = client.post(f"/api/film/scenes/{s1['id']}/shots", json={"duration_s": 2, "transition": {"kind": "dissolve", "duration_s": 0.5}}).json()["id"]
    b = client.post(f"/api/film/scenes/{s1['id']}/shots", json={"duration_s": 1.5}).json()["id"]
    c = client.post(f"/api/film/scenes/{s2['id']}/shots", json={"duration_s": 2}).json()["id"]
    for sid, secs, name in ((a, 2.5, "a"), (b, 1.0, "b")):
        client.post(f"/api/film/shots/{sid}/takes/import", files={"file": (f"{name}.mp4", mp4(secs, name=name), "video/mp4")})
    client.post(f"/api/film/shots/{c}/takes/import", files={"file": ("c.png", png(640, 360, (20, 120, 220)), "image/png")})
    client.post(f"/api/film/projects/{p['id']}/audio", files={"file": ("tone.wav", wav(2.0), "audio/wav")}, data={"kind": "music"})
    client.put(f"/api/film/projects/{p['id']}/subtitles", json={"cues": [{"start_s": 0.2, "end_s": 1.5, "text": "Hello"}], "burn_in": True})
    tl = client.get(f"/api/film/projects/{p['id']}/timeline").json()
    assert tl["runtime_s"] == 5.5
    pl = client.get(f"/api/film/projects/{p['id']}/exports").json()["plan"]
    assert [sg["type"] for sg in pl["segments"]] == ["clip", "clip", "gap", "clip"]
    assert pl["segments"][0]["join_after"]["kind"] == "dissolve" and pl["segments"][1]["join_after"]["kind"] == "fade_black"
    job = client.post(f"/api/film/projects/{p['id']}/export", json={"label": "v1", "quality": "720p", "inline": True}).json()
    assert job["status"] == "done", job
    res = job["result"]
    assert res["url"].endswith("/exports/v1.mp4") and res["srt_url"].endswith("v1.srt") and res["burn_in"] is True
    assert res["width"] == 1280 and res["height"] == 720 and res["tracks"] == 1
    with db_mod.session_scope() as s:
        final = take_svc.abs_path(res["path"])
        info = qa.probe(final)
        assert info["audio"] and abs(info["duration"] - 5.5) < 0.3 and info["width"] == 1280
        sources = json.loads(take_svc.abs_path(res["path"].replace(".mp4", ".sources.json")).read_text())
        assert [sh["label"] for sh in sources["shots"]] == ["1.1", "1.2", "2.1"] and sources["subtitles"]["cues"]
    assert res["review"]["verdict"] in ("PASS", "WARN") and len(res["samples"]) == 3
    assert {c["key"] for c in res["review"]["checks"]} >= {"valid", "runtime", "audio_level", "black_frames"}
    # missing media blocks export unless forced; QA gate approval lets it through
    with db_mod.session_scope() as s:
        tk = s.get(FilmTake, client.get(f"/api/film/shots/{a}").json()["selected_take_id"])
        take_svc.abs_path(tk.media_path).unlink()
    r = client.post(f"/api/film/projects/{p['id']}/export", json={"label": "v2", "inline": True})
    assert r.status_code == 422 and "QA fails" in r.json()["detail"]
    job = client.post(f"/api/film/projects/{p['id']}/export", json={"label": "v2", "force": True, "quality": "720p", "inline": True}).json()
    assert job["status"] == "done" and job["result"]["review"]["verdict"] in ("PASS", "WARN")
    board = client.get(f"/api/film/projects/{p['id']}/board").json()
    assert {st["key"]: st["status"] for st in board["stages"]}["export"] == "done"


# --------------------------------------------------------------- reference -
def test_reference_video_analysis_and_grounded_proposal(client, app_env):
    p = client.post("/api/film/projects", json={"title": "Ref", "synopsis": "A courier races the rain."}).json()
    r = client.post(f"/api/film/projects/{p['id']}/reference/upload", files={"file": ("ref.mp4", mp4_cuts("ref"), "video/mp4")})
    assert r.status_code == 200, r.text
    ref = r.json()["reference"]
    assert ref["shot_count"] == 3 and ref["pacing"]["median_s"] == 1.0 and ref["pacing_profile"] == "hypercut"
    assert ref["aspect_ratio"] == "16:9" and ref["audio"] is False and len(ref["keyframes"]) == 3
    assert ref["transcript"] is None and "No configured provider" in ref["transcript_note"]
    assert ref["style"]["heuristic"] is True and ref["source"]["kind"] == "file"
    assert client.post(f"/api/film/projects/{p['id']}/reference", json={"url": "https://youtu.be/x"}).status_code == 422
    prop = client.post(f"/api/film/projects/{p['id']}/reference/propose", json={"use_llm": False}).json()
    assert prop["kind"] == "reference_proposal" and prop["source"] == "fallback"
    pp = prop["proposal"]
    assert pp["pacing_profile"] == "hypercut" and len(pp["scenes"]) == 2 and pp["estimated_cost_usd"] > 0
    assert any("no footage or text is reused" in x for x in pp["changed"])
    acc = client.post(f"/api/film/proposals/{prop['id']}/accept").json()["result"]
    assert acc["structure_created"] and len(acc["scene_ids"]) == 2
    proj = client.get(f"/api/film/projects/{p['id']}").json()
    assert proj["settings"]["pacing_profile"] == "hypercut" and proj["shot_count"] == 3
    assert proj["reference"]["proposal_accepted"]["job_id"] == prop["id"] and proj["plan"]["approved"] is False
    assert proj["scenes"][0]["shots"][0]["overrides"]["shot_type"] == "establishing"


# ------------------------------------------------------------------- runs --
def test_sample_and_batch_runs_respect_gates_and_checkpoints(client, app_env, providers):
    p, sc, _ids = _project(client, settings={"budget": {"mode": "observe"}},
                           shots=(("wide", 2.0), ("close", 1.5), ("card", 1.0)))
    ids = [sh["id"] for sh in client.get(f"/api/film/scenes/{sc['id']}").json()["shots"]]
    client.patch(f"/api/film/shots/{ids[0]}", json={"overrides": {"shot_type": "establishing"}})
    client.patch(f"/api/film/shots/{ids[1]}", json={"overrides": {"shot_type": "close_up"}})
    client.patch(f"/api/film/shots/{ids[2]}", json={"media_strategy": "motion_graphics"})
    sample = client.get(f"/api/film/projects/{p['id']}/sample-shots").json()["shots"]
    assert [s_["id"] for s_ in sample] == [ids[0], ids[1], ids[2]]
    r = client.post(f"/api/film/projects/{p['id']}/runs", json={"kind": "video"})
    assert r.status_code == 409 and r.json()["detail"]["missing_gates"] == ["plan", "storyboard"]
    job = client.post(f"/api/film/projects/{p['id']}/runs", json={"kind": "video", "sample": True, "inline": True}).json()
    assert job["status"] == "done" and len(job["result"]["take_ids"]) == 2
    assert job["result"]["skipped"] == [] and job["checkpoint"]["done"] == ids[:2]   # non-AI shot filtered out up front
    for tid in job["result"]["take_ids"]:
        gen_queue.process_generation(client.get(f"/api/film/takes/{tid}").json()["generation_id"])
    assert client.get(f"/api/film/shots/{ids[0]}").json()["status"] == "generated"
    client.post(f"/api/film/projects/{p['id']}/gates/plan", json={"status": "approved"})
    client.post(f"/api/film/projects/{p['id']}/gates/storyboard", json={"status": "approved"})
    r = client.post(f"/api/film/projects/{p['id']}/runs", json={"kind": "video", "inline": True})
    assert r.status_code == 422 and "Nothing to generate" in r.json()["detail"]     # everything done or non-AI
    job = client.post(f"/api/film/projects/{p['id']}/runs", json={"kind": "video", "inline": True, "skip_done": False}).json()
    assert job["status"] == "done" and len(job["result"]["take_ids"]) == 2
    assert len(client.get(f"/api/film/shots/{ids[0]}/takes").json()["takes"]) == 2
    board = client.get(f"/api/film/projects/{p['id']}/board").json()
    gen = {st["key"]: st for st in board["stages"]}["shot_generation"]
    assert gen["status"] == "in_progress" and gen["progress"]["done"] == 2 and gen["cost"]["estimated_usd"] > 0


# ------------------------------------------------------------ asset AI ----
def test_asset_ai_tools_add_generated_references(client, app_env, providers):
    jack = client.post("/api/film/assets", json={"type": "character", "name": "Jack", "data": {"eyes": "green", "hair": "black"},
                                                 "negative_constraints": ["no beard"]}).json()
    tools = {t["key"]: t for t in client.get(f"/api/film/assets/{jack['id']}/tools").json()["tools"]}
    assert tools["generate"]["supported"] and not tools["variation"]["supported"]
    assert "reference image first" in tools["variation"]["reason"]
    assert tools["upscale"]["supported"] is False and "No configured provider" in tools["upscale"]["reason"]
    assert client.post(f"/api/film/assets/{jack['id']}/generate", json={"tool": "variation"}).status_code == 422
    g = client.post(f"/api/film/assets/{jack['id']}/generate", json={"tool": "generate", "instruction": "rain on his face"}).json()
    assert g["mode"] == "text_to_image" and g["prompt"].startswith("Character reference portrait")
    assert "LOCKED — eyes: green; hair: black" in g["prompt"] and "Direction: rain on his face" in g["prompt"]
    assert "Keep exactly: eyes, hair" in g["prompt"]
    gen_queue.process_generation(g["generation_id"])
    assert providers.submits[-1]["negative"] == "no beard" and providers.submits[-1]["kind"] == "image"
    a = client.get(f"/api/film/assets/{jack['id']}").json()
    ref = a["current_version"]["refs"][0]
    assert ref["source"] == f"generation:{g['generation_id']}" and ref["provenance"]["origin"] == "generated"
    assert ref["kind"] == "portrait" and a["current_version"]["primary_ref_id"] == ref["id"]
    tools = {t["key"]: t for t in client.get(f"/api/film/assets/{jack['id']}/tools").json()["tools"]}
    assert tools["variation"]["supported"] and tools["edit"]["supported"]
    v = client.post(f"/api/film/assets/{jack['id']}/generate", json={"tool": "edit", "instruction": "red jacket", "strength": 0.4}).json()
    gen_queue.process_generation(v["generation_id"])
    sub = providers.submits[-1]["params"]
    assert sub["_inputs"]["strength"] == 0.4 and sub["_inputs"]["image"].endswith(".webp") and sub["_mode"] == "image_to_image"   # gallery copies are WebP
    gens = client.get(f"/api/film/assets/{jack['id']}/tools").json()["generations"]
    assert [x["tool"] for x in gens] == ["edit", "generate"] and all(x["ref"] for x in gens)
    assert client.get(f"/api/film/assets/{jack['id']}").json()["ref_count"] == 2
