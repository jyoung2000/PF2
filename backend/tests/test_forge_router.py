"""Intent extraction, routing and the prompt compiler (spec §3–§4)."""
from promptforge.forge import intent


def test_intent_spec_example():
    i = intent.extract("Create a cinematic 15-second 9:16 sci-fi trailer with "
                       "the same character across shots, under $2")
    assert i["modality"] == "video" and i["duration_s"] == 15.0
    assert i["aspect_ratio"] == "9:16" and "cinematic" in i["styles"]
    assert i["character_consistency"] and i["references_needed"]
    assert i["budget_sensitive"] and i["budget_cap_usd"] == 2.0
    assert i["evidence"]["duration_s"]              # every inference cites text


def test_intent_portrait_genre_vs_orientation_and_avoid():
    i = intent.extract("A noir portrait of a violinist, no rain, square image")
    assert i["aspect_ratio"] == "1:1"               # square wins; 'portrait of' is genre
    assert i["avoid"] == ["rain"]
    assert i["modality"] == "image"
    i2 = intent.extract("vertical wallpaper of a mountain")
    assert i2["aspect_ratio"] == "9:16"
    i3 = intent.extract('a poster with the title "NIGHT SHIFT" in bold type')
    assert i3["needs_typography"] and i3["text_content"] == ["NIGHT SHIFT"]


def test_route_is_explainable_and_reports_unsupported(client):
    r = client.post("/api/forge/route", json={
        "brief": "cinematic 15-second 9:16 trailer, same character across shots"}).json()
    best = r["recommended"]
    assert best and best["reasons"], "selection carries reasons"
    assert any("10s" in u for u in best["unsupported_constraints"]), \
        "the 15s-vs-cap constraint is reported, not dropped"
    assert best["parameter_recommendations"].get("duration_s") == 10.0
    assert r["alternatives"] and all(a["total"] <= best["total"] for a in r["alternatives"])
    # audio is honestly unsupported end to end
    r = client.post("/api/forge/route", json={"brief": "a 30 second narration voiceover"}).json()
    assert r["recommended"] is None and "audio" in r["unsupported"]


def test_route_override_pins_family(client):
    r = client.post("/api/forge/route", json={
        "brief": "cinematic vertical trailer", "family": "wan"}).json()
    assert r["policy"] == "explicit"
    assert all(c["family"] == "wan" for c in r["candidates"])


def test_compile_differs_per_model_and_recompile_keeps_intent(client):
    idea = "A noir portrait of a violinist under a streetlight, no rain, square"
    sdxl = client.post("/api/forge/compile", json={"idea": idea, "family": "sdxl"}).json()
    assert sdxl["params"]["aspect_ratio"] == "1:1"
    assert sdxl["negative_prompt"] == "rain"                      # negative supported
    assert "masterpiece" in sdxl["optimized_prompt"]              # tag style
    assert "no rain" not in sdxl["optimized_prompt"]

    flux = client.post("/api/forge/compile",
                       json={"package": sdxl, "family": "flux"}).json()
    assert flux["original"] == idea and flux["intent"]["aspect_ratio"] == "1:1"
    assert flux["negative_prompt"] is None                        # flux has none
    assert "without rain" in flux["optimized_prompt"]             # folded instead
    assert "masterpiece" not in flux["optimized_prompt"]          # natural language
    assert flux["evaluation_criteria"] and flux["route"]["alternatives"] is not None
    assert flux["llm_polish"] is None                             # LLM off by default


def test_compile_llm_optional_never_fatal(client):
    p = client.post("/api/forge/compile",
                    json={"idea": "a cozy cabin", "family": "flux", "use_llm": True}).json()
    assert p["llm_polish"]["applied"] is False                    # not configured → note
    assert p["optimized_prompt"]                                  # deterministic result stands
