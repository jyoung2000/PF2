"""MuAPI adapter + artifact landing (Phase 2, upstream audit).

The contract mirrored here is the one verified in the upstream repos:
POST {base}/{endpoint} → {id}, GET {base}/predictions/{id}/result → {status,…},
x-api-key auth. No live calls — everything runs on a mock transport.
"""
import json

import httpx
import pytest

from promptforge import db as db_mod, settings_store
from promptforge.generation import queue as gen_queue
from promptforge.generation import router as gen_router
from promptforge.generation.base import ProviderError
from promptforge.generation.muapi import MuAPIProvider, extract_output_url, extract_text
from promptforge.models import Generation


def _muapi(handler):
    return MuAPIProvider(transport=httpx.MockTransport(handler))


def test_test_connection_distinguishes_bad_key_from_reachable(app_env):
    p = _muapi(lambda r: httpx.Response(401))
    assert _muapi(lambda r: httpx.Response(401)).test_connection("k")["ok"] is False
    # 404 on a nonexistent prediction means the key was accepted
    ok = _muapi(lambda r: httpx.Response(404, json={"detail": "not found"})).test_connection("k")
    assert ok["ok"] is True
    assert p.test_connection("")["ok"] is False        # no key at all
    down = _muapi(lambda r: httpx.Response(503)).test_connection("k")
    assert down["ok"] is False and "unavailable" in down["detail"]


def test_submit_maps_fields_per_endpoint(app_env):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content) if request.content else {}
        return httpx.Response(200, json={"request_id": "req-1"})

    p = _muapi(handler)
    # transcription: audio goes to audio_url, and whisper takes no prompt field
    p.submit("k", "openai-whisper", "", None,
             {"_inputs": {"audio": "https://x/a.mp3"}, "language": "en"}, "audio")
    assert seen["url"].endswith("/openai-whisper")
    assert seen["headers"]["x-api-key"] == "k"
    assert seen["body"]["audio_url"] == "https://x/a.mp3"
    assert seen["body"]["language"] == "en"
    assert "prompt" not in seen["body"]

    # TTS: prompt + voice params pass through
    p.submit("k", "minimax-speech-2.6-hd", "Hello there", None,
             {"voice_id": "female-shaonv", "speed": 1.0}, "audio")
    assert seen["body"] == {"prompt": "Hello there", "voice_id": "female-shaonv", "speed": 1.0}

    # video→audio: video goes to video_url
    p.submit("k", "mmaudio-v2-video-to-video", "footsteps", None,
             {"_inputs": {"video": "https://x/v.mp4"}, "duration": 8}, "audio")
    assert seen["body"]["video_url"] == "https://x/v.mp4" and seen["body"]["duration"] == 8

    # image tool: image goes to image_url
    p.submit("k", "ai-image-upscaler", "", None,
             {"_inputs": {"image": "https://x/i.png"}}, "image")
    assert seen["body"]["image_url"] == "https://x/i.png"


def test_submit_error_mapping(app_env):
    for code, step in ((401, "auth"), (404, "model"), (422, "params"), (500, "submit")):
        p = _muapi(lambda r, c=code: httpx.Response(c, text="nope"))
        with pytest.raises(ProviderError) as e:
            p.submit("k", "openai-whisper", "x", None, {}, "audio")
        assert e.value.step == step
    # accepted but no id
    p = _muapi(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ProviderError):
        p.submit("k", "openai-whisper", "x", None, {}, "audio")


def test_poll_statuses_and_output_shapes(app_env):
    def resp(body):
        return _muapi(lambda r: httpx.Response(200, json=body)).poll("k", "m", "id")

    assert resp({"status": "queued"})["status"] == "queued"
    assert resp({"status": "processing"})["status"] == "running"
    assert resp({"status": "failed", "error": "boom"}) == {"status": "failed", "error": "boom"}
    # every terminal spelling the upstream clients accept
    for done in ("succeeded", "completed", "success"):
        r = resp({"status": done, "audio_url": "https://cdn/a.mp3"})
        assert r == {"status": "succeeded", "output_url": "https://cdn/a.mp3"}
    # nested output shapes
    assert resp({"status": "completed", "outputs": {"glb_url": "https://cdn/m.glb"}})["output_url"].endswith(".glb")
    assert resp({"status": "completed", "output": ["https://cdn/x.png"]})["output_url"].endswith(".png")
    # text result (transcription) carries no file
    r = resp({"status": "completed", "text": "hello world"})
    assert r == {"status": "succeeded", "output_text": "hello world"}
    assert resp({"status": "completed"})["status"] == "failed"


def test_output_extractors_ignore_non_urls():
    assert extract_output_url({"url": "not-a-url"}) is None
    assert extract_output_url({"outputs": [{"url": "https://a/b.mp4"}]}) == "https://a/b.mp4"
    assert extract_text({"result": {"transcript": "hi"}}) == "hi"
    assert extract_text({"output": "https://a/b"}) is None      # a URL is not text


@pytest.fixture()
def muapi_connected(app_env, monkeypatch):
    with db_mod.session_scope() as s:
        settings_store.put(s, "muapi_api_key", "k")
    submitted = []

    def handler(request):
        url = str(request.url)
        if "/predictions/" in url:
            # whisper returns text; the speech endpoints return a file
            if submitted and "whisper" in submitted[-1]:
                return httpx.Response(200, json={"status": "completed", "text": "a transcript"})
            return httpx.Response(200, json={"status": "completed",
                                             "audio_url": "https://cdn/out.mp3"})
        submitted.append(url)
        return httpx.Response(200, json={"id": "req-1"})

    provider = _muapi(handler)
    monkeypatch.setattr(gen_router, "get_provider",
                        lambda name: provider if name == "muapi" else None)
    real_client = httpx.Client

    def client_factory(**kw):
        # patching queue.httpx.Client patches the httpx module globally, so
        # never clobber a transport an adapter passed in for itself
        kw.setdefault("transport", httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"ID3fake-audio-bytes")))
        return real_client(**kw)
    monkeypatch.setattr("promptforge.generation.queue.httpx.Client", client_factory)
    return submitted


def test_tts_runs_end_to_end_into_an_artifact(client, muapi_connected):
    r = client.post("/api/forge/tools/generate_speech",
                    json={"prompt": "Welcome to PromptForge.",
                          "params": {"voice_id": "female-shaonv"}}).json()
    assert r["provider"] == "muapi" and r["mode"] == "tts"
    gen_queue.process_generation(r["job_id"])
    j = client.get(f"/api/forge/jobs/{r['job_id']}").json()
    assert j["status"] == "succeeded"
    assert j["output_post_id"] is None            # audio is not a library Post
    with db_mod.session_scope() as s:
        art = s.get(Generation, r["job_id"]).params["_artifact"]
    assert art["kind"] == "audio" and art["path"].startswith("forge/artifacts/")
    assert art["bytes"] > 0
    from promptforge.forge import artifacts
    assert artifacts.resolve(art["path"]).exists()


def test_transcription_lands_text_artifact(client, muapi_connected):
    r = client.post("/api/forge/tools/transcribe_audio",
                    json={"audio": "https://example.com/interview.mp3"}).json()
    gen_queue.process_generation(r["job_id"])
    with db_mod.session_scope() as s:
        art = s.get(Generation, r["job_id"]).params["_artifact"]
    assert art["text"] == "a transcript" and art["path"].endswith(".txt")


def test_artifact_paths_are_traversal_checked(app_env):
    from promptforge.forge import artifacts
    for bad in ("../../etc/passwd", "forge/artifacts/../../../etc/passwd",
                "media/x.png", ""):
        with pytest.raises(ValueError):
            artifacts.resolve(bad)
