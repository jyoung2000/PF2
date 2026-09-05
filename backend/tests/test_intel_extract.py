"""Phase I3: deterministic extraction with provenance, heuristic + LLM AI
classification (never overwriting explicit data), knowledge-engine
observed/inferred/AI separation with expanded stats."""
import json
from datetime import datetime, timezone

from promptforge import db as db_mod, settings_store
from promptforge.intel import analysis, extract, provenance, queue
from promptforge.knowledge import engine, stats, techniques
from promptforge.llm import client as llm_client
from promptforge.models import Post
from tests.conftest import seed_post


# ------------------------------------------------------- deterministic -----
def test_model_versions_new_models_and_false_positives():
    ex = extract.extract_from_text("Made with Kling 2.1\nPrompt: slow orbit around a glass city #aivideo")
    assert ex["model_name"] == "Kling" and ex["model_family"] == "kling"
    assert ex["model_version"] == "2.1" and ex["model_stated"] is True
    assert ex["prompt"].startswith("slow orbit") and ex["prompt_method"] == "labelled"
    assert extract.extract_from_text("Veo 3 test, cinematic")["model_version"] == "3"
    assert extract.extract_from_text("rendered in PixVerse V4.5")["model_family"] == "pixverse"
    assert extract.extract_from_text("Vidu Q1 reference mode")["model_family"] == "vidu"
    assert extract.extract_from_text("Flux Kontext edit")["model_family"] == "flux"
    assert extract.detect_model_version("flux.1 kontext dev", "flux") == "kontext"
    assert extract.detect_model_version("midjourney --v 7 --ar 16:9", "midjourney") == "7"
    assert extract.detect_model_version("gen-4 turbo", "runway") == "4"
    none = extract.extract_from_text("sparkling water on a sunny influx of tourists, my pikachu plush")
    assert none["model_name"] is None and none["prompt_method"] != "labelled"
    assert extract.detect_model_version("nothing here", "kling") is None


def test_camera_lighting_composition_and_taxonomy():
    text = ("shot on 35mm, low angle close-up, golden hour with a hard rim light, "
            "rule of thirds, volumetric light, dutch angle, shallow depth of field, "
            "film grain, start frame and end frame interpolation, 85mm portrait lens")
    cam = extract.detect_camera(text)
    assert cam["lens_mm"] == [35, 85]
    assert [s["value"] for s in cam["shot_size"]] == ["close-up"]
    assert [a["value"] for a in cam["angle"]] == ["low angle", "dutch angle"]
    assert cam["angle"][0]["evidence"]
    light = [l["value"] for l in extract.detect_lighting(text)]
    assert {"golden hour", "rim light", "volumetric"} <= set(light)
    assert [c["value"] for c in extract.detect_composition(text)] == ["rule of thirds"]
    slugs = set(techniques.detect_techniques(text))
    assert {"volumetric-light", "dutch-angle", "shallow-dof", "film-grain",
            "start-end-frame", "35mm", "85mm", "low-angle", "golden-hour"} <= slugs
    assert extract.detect_camera("") == {} and extract.detect_lighting(None) == []


def test_apply_extraction_writes_assertions_and_heuristic_status(app_env):
    civ = seed_post(platform="civitai", prompt="volumetric light, 50mm, low-key portrait")
    x_meta = seed_post(platform="x", prompt=None, model_name=None, model_family=None,
                       params={"workflow": {"1": {}}, "metadata_format": "comfyui"})
    x_real = seed_post(platform="x", prompt=None, model_name=None, model_family=None,
                       observed={"text": {"body": "shot on iPhone 15, no AI, just golden hour"}})
    x_model = seed_post(platform="x", prompt="Prompt: neon alley", model_name="Kling",
                        model_family="kling", model_version=None,
                        observed={"text": {"body": "made with Kling 2.1"}},
                        assertions={"model": {"value": "Kling", "source": "extracted", "confidence": 0.85}})
    x_plain = seed_post(platform="x", prompt=None, model_name=None, model_family=None,
                        observed={"text": {"body": "morning coffee"}})
    with db_mod.session_scope() as s:
        summary = extract.apply_extraction(s.get(Post, civ))
        p = s.get(Post, civ)
        assert p.ai_status == "definitely_ai" and p.ai_confidence >= 0.9
        assert p.assertions["camera"]["value"]["lens_mm"] == [50]
        assert p.assertions["lighting"]["source"] == "extracted" and p.assertions["lighting"]["evidence"]
        assert "volumetric-light" in p.technique_tags and "50mm" in p.technique_tags
        assert p.assertions["model_family"]["value"] == "flux"
        assert summary["ai_status"] == "definitely_ai" and summary["lighting"]
        extract.apply_extraction(s.get(Post, x_meta))
        assert s.get(Post, x_meta).ai_status == "definitely_ai"
        extract.apply_extraction(s.get(Post, x_real))
        assert s.get(Post, x_real).ai_status == "probably_not_ai"
        extract.apply_extraction(s.get(Post, x_model))
        pm = s.get(Post, x_model)
        assert pm.ai_status == "probably_ai" and pm.model_version == "2.1"
        assert pm.assertions["model_version"]["source"] == "extracted"
        extract.apply_extraction(s.get(Post, x_plain))
        pp = s.get(Post, x_plain)
        assert pp.ai_status == "uncertain" and pp.analysis["ai"]["source"] == "heuristic"
        # ingest-time heuristic never clobbers a later LLM verdict
        pp.analysis = {"ai": {"status": "definitely_not_ai", "source": "mock"}}
        pp.ai_status = "definitely_not_ai"
        extract.apply_extraction(pp)
        assert pp.ai_status == "definitely_not_ai"


# ------------------------------------------------------------- LLM stage ---
def _mock_llm(*replies: dict):
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "mock")
    llm_client.mock_instance.responses = [json.dumps(r) for r in replies]
    llm_client.mock_instance.calls.clear()


def test_llm_analysis_respects_provenance_and_whitelists(app_env):
    explicit = seed_post(platform="x", prompt="Prompt: glass whale over a harbor",
                         model_name="Kling", model_family="kling", technique_tags=[],
                         assertions={"prompt": {"value": "glass whale over a harbor", "source": "extracted",
                                                "confidence": 0.9},
                                     "model": {"value": "Kling", "source": "extracted", "confidence": 0.85}})
    blank = seed_post(platform="x", prompt=None, model_name=None, model_family=None,
                      observed={"text": {"body": "orbit shot of a neon temple #aivideo"}},
                      assertions={})
    _mock_llm(
        {"ai_status": "definitely_ai", "ai_confidence": 0.93, "ai_reason": "hashtags + model named",
         "prompt": "AI TRIED TO REWRITE THIS", "prompt_confidence": 0.9,
         "model": "Sora", "model_confidence": 0.9, "model_reason": "looks like sora",
         "techniques": ["orbit", "not-a-slug"], "descriptors": {"subject": "whale", "style": "glassy"}},
        {"ai_status": "probably_ai", "ai_confidence": 0.7, "ai_reason": "aivideo hashtag",
         "prompt": "orbit shot of a neon temple", "prompt_confidence": 0.6,
         "model": "Kling", "model_confidence": 0.55, "model_reason": "typical kling hashtag set",
         "techniques": ["orbit"], "descriptors": {"camera": "orbit"}},
    )
    assert analysis.analyze_post(explicit, {}) == "complete"
    assert analysis.analyze_post(blank, {}) == "complete"
    with db_mod.session_scope() as s:
        e = s.get(Post, explicit)
        assert e.prompt == "Prompt: glass whale over a harbor"      # explicit prompt untouched
        assert e.model_name == "Kling" and e.model_source != "ai"    # explicit model untouched
        assert e.ai_status == "definitely_ai" and e.ai_confidence == 0.93
        assert e.analysis["ai"]["source"] == "mock" and e.analysis["descriptors"]["subject"] == "whale"
        assert e.technique_tags == ["orbit"]                          # whitelist enforced
        assert e.assertions["_alternates"]["prompt"][0]["source"] == "ai"  # kept as alternate
        assert e.pipeline_state == "analyzed"
        b = s.get(Post, blank)
        assert b.prompt == "orbit shot of a neon temple" and b.prompt_source == "ai"
        assert b.model_name == "Kling" and b.model_family == "kling" and b.model_source == "ai"
        assert b.params["model_inferred"] is True
        assert b.assertions["model"]["confidence"] == 0.55
        assert b.ai_status == "probably_ai"
    # the prompt sent to the LLM tells it what is already resolved
    assert "already resolved" in llm_client.mock_instance.calls[0][1]
    assert "already stated" in llm_client.mock_instance.calls[0][1]


def test_analysis_queue_semantics_budget_and_unconfigured(app_env):
    pid = seed_post(platform="x", prompt=None, model_name=None, model_family=None)
    queue.ensure_handlers()
    assert "analysis" in queue.handlers()
    with db_mod.session_scope() as s:
        queue.enqueue(s, pid, "analysis", priority=90)
    # no provider → skipped (not stuck, not an error)
    assert queue.process_one(("analysis",)) == "skipped"
    # cloud provider over budget → deferred, job stays queued, no attempt counted
    with db_mod.session_scope() as s:
        queue.enqueue(s, pid, "analysis", priority=90)
        settings_store.put(s, "llm_provider", "openai")
        settings_store.put(s, "openai_api_key", "sk-test")
        settings_store.put(s, "llm_daily_budget", 1)
        settings_store.put(s, "llm_usage", {"date": llm_client._budget_key_today(), "calls": 1})
    assert queue.process_one(("analysis",)) == "deferred"
    with db_mod.session_scope() as s:
        assert queue.stats(s)["stages"]["analysis"]["queued"] == 1
        settings_store.put(s, "intel_ai_analysis_enabled", False)
    assert queue.process_one(("analysis",)) == "skipped"
    # uncertain verdicts are stored, never deleted
    _mock_llm({"ai_status": "uncertain", "ai_confidence": 0.4, "ai_reason": "no evidence",
               "prompt": None, "model": None, "techniques": [], "descriptors": {}})
    with db_mod.session_scope() as s:
        settings_store.put(s, "intel_ai_analysis_enabled", True)
    assert analysis.analyze_post(pid, {}) == "complete"
    with db_mod.session_scope() as s:
        p = s.get(Post, pid)
        assert p is not None and p.ai_status == "uncertain" and p.prompt is None


# ------------------------------------------------------ knowledge gating ---
def test_knowledge_separates_observed_inferred_ai(app_env):
    now = datetime.now(timezone.utc)
    high = seed_post(model_family="kling", model_name="Kling", model_source="explicit",
                     prompt="slow dolly in, golden hour, 35mm lens, shallow depth of field",
                     media_type="video", media_width=1920, media_height=1080,
                     engagement_total=5000, technique_tags=["dolly"], posted_at=now,
                     observed={"author": {"handle": "motionmuse"}},
                     assertions={"prompt": {"value": "x", "source": "extracted", "confidence": 0.9}})
    ai_prompt = seed_post(model_family="kling", model_name="Kling", model_source="explicit",
                          prompt="AI GUESSED PROMPT TEXT unique zebra token",
                          assertions={"prompt": {"value": "x", "source": "ai", "confidence": 0.9}})
    inferred_model = seed_post(model_family="kling", model_name="Kling", model_source="inferred",
                               prompt="inferred model prompt with another unique giraffe token",
                               assertions={"prompt": {"value": "x", "source": "observed", "confidence": 0.96}})
    low_conf = seed_post(model_family="kling", model_name="Kling", model_source="explicit",
                         prompt="low confidence text with a kangaroo token",
                         assertions={"prompt": {"value": "x", "source": "extracted", "confidence": 0.5}})
    for pid in (high, ai_prompt, inferred_model, low_conf):
        engine._on_post_ingested(pid)
    data = stats.load_stats("kling")
    assert data["count"] == 3                       # inferred-model post never counted
    terms = " ".join(data["terms"])
    assert "golden hour" in terms
    assert "zebra" not in terms and "giraffe" not in terms and "kangaroo" not in terms
    assert data["aspects"] == {"16:9": 1, "2:3": 2}   # seed_post default is 512x768
    assert data["techniques"]["dolly"] == 1
    assert data["creators"] == {"motionmuse": 1}
    assert data["structure"] == {"tag-list": 1}
    assert list(data["weekly"]) == [now.strftime("%G-W%V")]
    assert data["weighted_terms"]["golden hour"] > 1.0   # engagement-weighted
    rendered = stats.render_stats_section(data)
    for line in ("Aspect ratios", "Techniques", "Camera vocabulary", "Engagement-weighted",
                 "Frequent creators", "Recent weeks", "Prompt structure"):
        assert line in rendered
    # accepting AI is an explicit opt-in
    with db_mod.session_scope() as s:
        settings_store.put(s, "knowledge_accept_ai", True)
    engine._on_post_ingested(ai_prompt)
    assert "zebra" in " ".join(stats.load_stats("kling")["terms"])
    assert stats.aspect_bucket(1080, 1920) == "9:16" and stats.aspect_bucket(0, 5) is None
    assert stats.prompt_structure("A fox walks home. It is raining hard.") == "natural"
