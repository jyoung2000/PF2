"""Generation hub tests (8.x): price math, cheapest routing, provider
adapters against mocked APIs, full E2E queue flow with learning feedback."""
import io

import httpx
import pytest
from PIL import Image

from promptforge import db as db_mod, settings_store
from promptforge.generation import pricing, queue as gen_queue, router as gen_router
from promptforge.generation.base import ProviderError
from promptforge.generation.fal import FalProvider
from promptforge.generation.replicate_provider import ReplicateProvider
from promptforge.generation.wavespeed import WaveSpeedProvider
from promptforge.models import Collection, Generation, Post


# ------------------------------------------------------------- pricing ------
def test_estimate_math_image_and_video(app_env):
    assert pricing.estimate("flux", "fal") == 0.025
    # per-megapixel: sdxl fal 0.0025/MP → 1024x1024 ≈ 1.05MP
    est = pricing.estimate("sdxl", "fal", {"size": "1024x1024"})
    assert est == round(0.0025 * 1024 * 1024 / 1_000_000, 4)
    # video per-second × resolution
    assert pricing.estimate("kling", "fal",
                            {"duration_s": 5, "resolution": "720p"}) == 0.25
    assert pricing.estimate("kling", "fal",
                            {"duration_s": 10, "resolution": "1080p"}) == 0.9
    # nearest resolution tier fallback (no 480p on kling → closest is 720p)
    assert pricing.estimate("kling", "fal",
                            {"duration_s": 5, "resolution": "480p"}) == 0.25
    # unknown combos → None
    assert pricing.estimate("flux", "nope") is None
    assert pricing.estimate("not-a-family", "fal") is None


def test_pricing_editable_copy(app_env):
    cat = pricing.load_catalog()
    assert "flux" in cat
    assert pricing.pricing_path().exists()  # copied to DATA_DIR
    cat["flux"]["providers"]["fal"]["price_per_image"] = 0.01
    pricing.save_catalog(cat)
    assert pricing.estimate("flux", "fal") == 0.01


# ------------------------------------------------------------- routing ------
def connect(providers: list[str]):
    with db_mod.session_scope() as s:
        keys = {"fal": "fal_api_key", "replicate": "replicate_api_token",
                "wavespeed": "wavespeed_api_key"}
        for name, setting in keys.items():
            settings_store.put(s, setting, "key-123" if name in providers else "")


def test_cheapest_provider_routing(app_env):
    connect(["fal", "replicate", "wavespeed"])
    with db_mod.session_scope() as s:
        provider, model_id, est = gen_router.route(s, "flux")
        assert provider == "wavespeed"          # 0.0197 < 0.025
        assert model_id == "wavespeed-ai/flux-dev"
        assert est == 0.0197
    connect(["fal", "replicate"])               # cheapest connected wins
    with db_mod.session_scope() as s:
        provider, _mid, est = gen_router.route(s, "flux")
        assert provider in ("fal", "replicate") and est == 0.025


def test_routing_override_and_errors(app_env):
    connect(["fal"])
    with db_mod.session_scope() as s:
        provider, _m, _e = gen_router.route(s, "flux", provider_override="fal")
        assert provider == "fal"
        with pytest.raises(LookupError, match="isn't connected"):
            gen_router.route(s, "flux", provider_override="replicate")
        with pytest.raises(LookupError, match="catalog"):
            gen_router.route(s, "definitely-not-real")
    connect([])
    with db_mod.session_scope() as s:
        with pytest.raises(LookupError, match="No connected provider"):
            gen_router.route(s, "flux")


def test_model_options_shape(app_env):
    connect(["fal"])
    with db_mod.session_scope() as s:
        opts = gen_router.model_options(s)
    assert opts["connected_providers"] == ["fal"]
    flux = next(m for m in opts["models"] if m["family"] == "flux")
    assert flux["offers"][0]["connected"] is True   # connected sorted first
    kling = next(m for m in opts["models"] if m["family"] == "kling")
    assert kling["kind"] == "video"


# ------------------------------------------------------- provider adapters --
def fal_server(state):
    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        if auth != "Key good":
            return httpx.Response(401, json={"detail": "unauthorized"})
        path = request.url.path
        if request.method == "POST":
            state["payload"] = __import__("json").loads(request.content)
            return httpx.Response(200, json={"request_id": "req-1"})
        if path.endswith("/status"):
            if "00000000" in path:
                return httpx.Response(404, json={"detail": "not found"})
            state.setdefault("polls", 0)
            state["polls"] += 1
            if state["polls"] < 2:
                return httpx.Response(200, json={"status": "IN_PROGRESS"})
            return httpx.Response(200, json={"status": "COMPLETED"})
        return httpx.Response(200, json={
            "images": [{"url": "https://out.fal/img.png"}]})
    return httpx.MockTransport(handler)


def test_fal_adapter_flow_and_test():
    state = {}
    p = FalProvider(transport=fal_server(state))
    assert p.test_connection("good")["ok"] is True
    bad = p.test_connection("bad")
    assert bad["ok"] is False and "401" in bad["detail"]
    assert p.test_connection("")["ok"] is False
    ref = p.submit("good", "fal-ai/flux/dev", "a fox", None,
                   {"size": "832x1216", "seed": 5}, "image")
    assert ref == "req-1"
    assert state["payload"]["image_size"] == {"width": 832, "height": 1216}
    assert state["payload"]["seed"] == 5
    assert p.poll("good", "fal-ai/flux/dev", ref)["status"] == "running"
    result = p.poll("good", "fal-ai/flux/dev", ref)
    assert result == {"status": "succeeded", "output_url": "https://out.fal/img.png"}
    with pytest.raises(ProviderError, match="401"):
        p.submit("bad", "fal-ai/flux/dev", "x", None, {}, "image")


def replicate_server(state):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != "Bearer good":
            return httpx.Response(401, json={"detail": "unauthorized"})
        path = request.url.path
        if path == "/v1/account":
            return httpx.Response(200, json={"username": "jalon"})
        if "predictions" in path and request.method == "POST":
            if "missing/model" in path:
                return httpx.Response(404, json={"detail": "not found"})
            state["payload"] = __import__("json").loads(request.content)
            return httpx.Response(201, json={"id": "pred-9", "status": "starting"})
        if path == "/v1/predictions/pred-9":
            return httpx.Response(200, json={
                "id": "pred-9", "status": "succeeded",
                "output": ["https://replicate.delivery/out.png"]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_replicate_adapter():
    state = {}
    p = ReplicateProvider(transport=replicate_server(state))
    ok = p.test_connection("good")
    assert ok["ok"] and "jalon" in ok["detail"]
    assert p.test_connection("bad")["ok"] is False
    ref = p.submit("good", "black-forest-labs/flux-dev", "a fox", "blurry",
                   {"size": "1024x1024"}, "image")
    assert state["payload"]["input"]["negative_prompt"] == "blurry"
    result = p.poll("good", "black-forest-labs/flux-dev", ref)
    assert result["output_url"] == "https://replicate.delivery/out.png"
    with pytest.raises(ProviderError, match="doesn't know model"):
        p.submit("good", "missing/model", "x", None, {}, "image")


def wavespeed_server(state):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != "Bearer good":
            return httpx.Response(401, json={"message": "unauthorized"})
        path = request.url.path
        if request.method == "POST":
            state["payload"] = __import__("json").loads(request.content)
            return httpx.Response(200, json={"data": {"id": "ws-7"}})
        if "00000000" in path:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json={"data": {
            "status": "completed", "outputs": ["https://ws.out/clip.mp4"]}})
    return httpx.MockTransport(handler)


def test_wavespeed_adapter():
    state = {}
    p = WaveSpeedProvider(transport=wavespeed_server(state))
    assert p.test_connection("good")["ok"] is True
    assert p.test_connection("bad")["ok"] is False
    ref = p.submit("good", "wavespeed-ai/wan-2.2/t2v-720p", "ink in water",
                   None, {"duration_s": 4}, "video")
    assert state["payload"]["duration"] == 4
    result = p.poll("good", "wavespeed-ai/wan-2.2/t2v-720p", ref)
    assert result["output_url"] == "https://ws.out/clip.mp4"


# ------------------------------------------------------------- E2E flow -----
class FakeProvider:
    name = "fal"
    label = "fal.ai"

    def __init__(self, fail_submit=False):
        self.fail_submit = fail_submit
        self.submits = 0

    def get_key(self, s):
        return "key"

    def submit(self, key, model_id, prompt, negative, params, kind):
        self.submits += 1
        if self.fail_submit:
            raise ProviderError("fal.ai rejected the request (422): bad size",
                                "params")
        return "job-1"

    def poll(self, key, model_id, job_ref):
        return {"status": "succeeded", "output_url": "https://cdn.fake/out.png"}


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), (120, 40, 200)).save(buf, "PNG")
    return buf.getvalue()


def test_generation_e2e(client, app_env, monkeypatch):
    connect(["fal"])
    with db_mod.session_scope() as s:
        c = Collection(name="Gen Target", model_family="flux")
        s.add(c)
        s.flush()
        cid = c.id
        settings_store.put(s, "llm_provider", "")  # deterministic learning only

    fake = FakeProvider()
    monkeypatch.setattr(gen_router, "get_provider", lambda name: fake)
    payload = png_bytes()
    real_client = httpx.Client
    monkeypatch.setattr(
        "promptforge.generation.queue.httpx.Client",
        lambda **kw: real_client(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=payload))))

    r = client.post("/api/generation/start", json={
        "prompt": "a violet cube on glass", "model_family": "flux",
        "params": {"size": "1024x1024"}, "collection_id": cid})
    assert r.status_code == 200, r.text
    gen = r.json()
    assert gen["status"] == "queued"
    assert gen["provider"] == "wavespeed" or gen["provider"] == "fal"
    gid = gen["id"]

    gen_queue.process_generation(gid)

    r = client.get(f"/api/generation/{gid}")
    body = r.json()
    assert body["status"] == "succeeded", body
    assert body["cost_actual"] == body["cost_estimate"]
    post_id = body["output_post_id"]
    assert post_id is not None
    detail = client.get(f"/api/posts/{post_id}").json()
    assert detail["origin"] == "generated"
    assert detail["prompt"] == "a violet cube on glass"
    assert detail["media_url"].endswith(".webp")   # compressed like scraped media
    # auto-added to the source collection
    assert any(col["id"] == cid for col in detail["collections"])
    # spend totals recorded
    spend = client.get("/api/generation/spend").json()
    assert spend["total"] > 0
    # learning feedback landed in the model file
    from promptforge.knowledge import files as kfiles
    _fm, kbody = kfiles.read_md(kfiles.model_file_path("flux"))
    assert "Generation generated" in kbody


def test_generation_failure_no_double_charge(client, app_env, monkeypatch):
    connect(["fal"])
    fake = FakeProvider(fail_submit=True)
    monkeypatch.setattr(gen_router, "get_provider", lambda name: fake)
    r = client.post("/api/generation/start", json={
        "prompt": "x", "model_family": "flux", "provider": "fal"})
    gid = r.json()["id"]
    gen_queue.process_generation(gid)
    body = client.get(f"/api/generation/{gid}").json()
    assert body["status"] == "failed"
    assert "422" in body["error"]
    # reprocessing a failed job is a no-op — never double-charges
    gen_queue.process_generation(gid)
    assert fake.submits == 1
    # no spend recorded on failure
    assert client.get("/api/generation/spend").json()["totals"] == {}


def test_start_without_provider_is_409(client, app_env):
    connect([])
    r = client.post("/api/generation/start",
                    json={"prompt": "x", "model_family": "flux"})
    assert r.status_code == 409
    assert "Settings" in r.json()["detail"]


def test_provider_test_endpoints(client, app_env, monkeypatch):
    state = {}
    monkeypatch.setattr(
        gen_router, "all_providers",
        lambda: {"fal": FalProvider(transport=fal_server(state))})
    with db_mod.session_scope() as s:
        settings_store.put(s, "fal_api_key", "good")
    r = client.post("/api/integrations/providers/fal/test")
    assert r.status_code == 200 and r.json()["ok"] is True
    with db_mod.session_scope() as s:
        settings_store.put(s, "fal_api_key", "bad")
    r = client.post("/api/integrations/providers/fal/test")
    assert r.status_code == 400
    assert "401" in r.json()["detail"]["message"]
    r = client.get("/api/integrations/providers")
    fal_status = next(p for p in r.json()["providers"] if p["name"] == "fal")
    assert fal_status["status"] == "error"
    assert fal_status["last_tested"] is not None
