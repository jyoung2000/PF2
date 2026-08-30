"""Prompt Studio tests (7.x): template schema→form→prompt round-trip,
export/import both formats, enhance (mocked LLM + 409), saved prompts search,
reference image dedupe."""
import io
import json

import pytest

from promptforge import db as db_mod, settings_store
from promptforge.knowledge import template_gen
from promptforge.llm import client as llm_client
from promptforge.models import Collection, CollectionPost, Template
from tests.conftest import seed_post


@pytest.fixture()
def mock_llm(app_env):
    llm_client.mock_instance.responses = []
    llm_client.mock_instance.calls = []
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "mock")
    yield llm_client.mock_instance
    llm_client.mock_instance.responses = []


@pytest.fixture()
def styled_collection(app_env):
    with db_mod.session_scope() as s:
        c = Collection(name="Neon Noir", model_family="flux")
        s.add(c)
        s.flush()
        cid = c.id
    pids = [seed_post(model_family="flux",
                      prompt=f"neon noir alley {i}, rain-slick streets, hard rim light, "
                             f"teal and magenta palette, 35mm, moody cinematic")
            for i in range(4)]
    with db_mod.session_scope() as s:
        for pid in pids:
            s.add(CollectionPost(collection_id=cid, post_id=pid))
    return cid


def test_assemble_cleans_empty_slots():
    out = template_gen.assemble(
        "{subject}, {style}, {lighting}, {mood}, {detail}",
        {"subject": "a lighthouse", "style": ["cinematic", "film still"],
         "lighting": "", "mood": "somber", "detail": None})
    assert out == "a lighthouse, cinematic, film still, somber"


def test_template_generated_from_collection(styled_collection, client):
    tid = template_gen.sync_template_for_collection(styled_collection)
    assert tid is not None
    r = client.get(f"/api/studio/templates/{tid}")
    t = r.json()
    assert t["recommended_model"] == "flux"
    assert t["collection_name"] == "Neon Noir"
    slots = {s["key"]: s for s in t["schema"]["slots"]}
    assert slots["subject"]["required"] is True
    assert any("rim light" in o for o in slots["lighting"]["options"])
    assert len(t["ref_slots"]) == 2
    # schema → form values → assembled prompt round-trip (7.2)
    values = {"subject": "a detective at a noodle stand",
              "style": slots["style"]["default"],
              "lighting": slots["lighting"]["options"][0],
              "mood": "moody cinematic"}
    r2 = client.post(f"/api/studio/templates/{tid}/assemble", json={"values": values})
    prompt = r2.json()["prompt"]
    assert prompt.startswith("a detective at a noodle stand")
    assert slots["lighting"]["options"][0] in prompt
    assert ",," not in prompt


def test_template_editor_and_user_edit_protection(styled_collection, client):
    tid = template_gen.sync_template_for_collection(styled_collection)
    r = client.put(f"/api/studio/templates/{tid}", json={
        "name": "My tweaked template",
        "template_schema": {"slots": [{"key": "subject", "label": "Subject",
                                   "type": "text", "required": True}]},
        "text_template": "{subject} in neon noir style",
    })
    body = r.json()
    assert body["user_edited"] is True and body["name"] == "My tweaked template"
    # engine sync respects user edits
    template_gen.sync_template_for_collection(styled_collection)
    with db_mod.session_scope() as s:
        t = s.get(Template, tid)
        assert t.text_template == "{subject} in neon noir style"
    # regenerate endpoint explicitly rebuilds
    r = client.post(f"/api/studio/templates/{tid}/regenerate")
    assert r.json()["user_edited"] is False
    assert "{subject}" in r.json()["text_template"]


def test_template_export_import_round_trip(styled_collection, client):
    tid = template_gen.sync_template_for_collection(styled_collection)
    with db_mod.session_scope() as s:
        t = s.get(Template, tid)
        as_json = template_gen.export_json(t)
        as_text = template_gen.export_text(t)
        original_schema = json.loads(json.dumps(t.schema_json))
        original_text_template = t.text_template
        original_refs = json.loads(json.dumps(t.ref_slots))

    # JSON round trip → identical template
    new_id = template_gen.import_json(as_json, collection_id=None)
    with db_mod.session_scope() as s:
        t2 = s.get(Template, new_id)
        assert t2.schema_json.get("slots") == original_schema.get("slots")
        assert t2.text_template == original_text_template
        assert t2.ref_slots == original_refs

    # text round trip → same slots/refs/template line
    text_id = template_gen.import_text(as_text, collection_id=None)
    with db_mod.session_scope() as s:
        t3 = s.get(Template, text_id)
        assert t3.text_template == original_text_template
        assert [r["key"] for r in t3.ref_slots] == [r["key"] for r in original_refs]
        keys = [sl["key"] for sl in t3.schema_json["slots"]]
        assert keys == [sl["key"] for sl in original_schema["slots"]]
        by_key = {sl["key"]: sl for sl in t3.schema_json["slots"]}
        orig_by_key = {sl["key"]: sl for sl in original_schema["slots"]}
        assert by_key["lighting"]["options"] == orig_by_key["lighting"]["options"]
        assert by_key["subject"].get("required") is True
    # upload endpoint accepts both formats
    r = client.post("/api/studio/templates/import",
                    files={"file": ("t.json", json.dumps(as_json), "application/json")})
    assert r.status_code == 200
    r = client.post("/api/studio/templates/import",
                    files={"file": ("t.txt", as_text, "text/plain")})
    assert r.status_code == 200
    # garbage rejected cleanly
    r = client.post("/api/studio/templates/import",
                    files={"file": ("bad.txt", "not a template", "text/plain")})
    assert r.status_code == 400


def test_enhance_with_mock_and_409_without(client, mock_llm):
    seed_post(model_family="flux", prompt="seed so model file exists")
    from promptforge.knowledge import files as kfiles
    kfiles.ensure_model_file("flux")
    mock_llm.responses = [json.dumps({
        "enhanced": "a lone lighthouse keeper, 85mm portrait, golden-hour rim light",
        "negative": "",
        "notes": [{"change": "added lens + light", "why": "flux rewards camera language"}],
    })]
    r = client.post("/api/studio/enhance",
                    json={"prompt": "lighthouse keeper", "model_family": "Flux Dev"})
    assert r.status_code == 200
    body = r.json()
    assert body["before"] == "lighthouse keeper"
    assert "85mm" in body["enhanced"]
    assert body["notes"][0]["why"].startswith("flux rewards")
    # model knowledge went into the LLM context
    assert "Deterministic stats" in mock_llm.calls[0][1]
    # no provider configured → 409 with guidance (D41)
    with db_mod.session_scope() as s:
        settings_store.put(s, "llm_provider", "")
    r = client.post("/api/studio/enhance", json={"prompt": "x"})
    assert r.status_code == 409
    assert "Settings" in r.json()["detail"]


def test_saved_prompts_and_unified_search(client):
    scraped = seed_post(model_family="flux", prompt="a scraped glass cathedral")
    r = client.post("/api/studio/prompts", json={
        "text": "a saved crystal cathedral, dawn light",
        "model_family": "flux", "origin": "manual", "starred": True})
    sid = r.json()["id"]
    assert r.json()["model_family"] == "flux"
    # unified search hits both saved and scraped
    r = client.get("/api/studio/prompts?q=cathedral")
    kinds = {(it["kind"], it["id"]) for it in r.json()["items"]}
    assert ("saved", sid) in kinds and ("post", scraped) in kinds
    # starred filter
    r = client.get("/api/studio/prompts?q=cathedral&starred=true")
    assert all(it["starred"] for it in r.json()["items"])
    # origin filter isolates saved
    r = client.get("/api/studio/prompts?origin=manual")
    assert all(it["kind"] == "saved" for it in r.json()["items"])
    # star toggle + patch + delete
    assert client.post(f"/api/studio/prompts/{sid}/star").json()["starred"] is False
    assert client.patch(f"/api/studio/prompts/{sid}",
                        json={"text": "renamed text"}).json()["text"] == "renamed text"
    assert client.delete(f"/api/studio/prompts/{sid}").status_code == 200
    assert client.get("/api/studio/prompts?origin=manual").json()["items"] == []


def make_png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 100, 50)).save(buf, "PNG")
    return buf.getvalue()


def test_reference_images_dedupe_and_linking(client, app_env):
    png = make_png_bytes()
    r1 = client.post("/api/studio/refs",
                     files={"file": ("ref.png", png, "image/png")})
    assert r1.status_code == 200
    ref_id = r1.json()["ref_id"]
    assert r1.json()["deduped"] is False
    # same bytes → deduped by sha256
    r2 = client.post("/api/studio/refs",
                     files={"file": ("other-name.png", png, "image/png")})
    assert r2.json()["ref_id"] == ref_id and r2.json()["deduped"] is True
    # file served
    assert client.get(f"/api/studio/refs/{ref_id}/file").status_code == 200
    # wrong type rejected
    r3 = client.post("/api/studio/refs",
                     files={"file": ("x.gif", b"GIF89a", "image/gif")})
    assert r3.status_code == 422
    # linked to a saved prompt with a role
    r4 = client.post("/api/studio/prompts", json={
        "text": "prompt with a style ref", "refs": [{"ref_id": ref_id,
                                                     "role": "style"}]})
    assert r4.json()["refs"][0]["role"] == "style"
    assert r4.json()["refs"][0]["ref_id"] == ref_id


def test_templates_autocreate_for_collections(client, styled_collection):
    r = client.get("/api/studio/templates")
    templates = r.json()["templates"]
    assert any(t["collection_id"] == styled_collection for t in templates)
