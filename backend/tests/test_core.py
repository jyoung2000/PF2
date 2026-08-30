"""Tests for config, db (WAL), models schema, FTS, settings store, aliases."""
import json

from promptforge import db as db_mod
from promptforge import fts, settings_store
from promptforge.aliases import display_family, normalize_model
from promptforge.models import Post, SavedPrompt, Setting, Tag


def test_wal_mode_and_schema(app_env, db_session):
    assert db_mod.wal_mode() == "wal"
    p = Post(platform="civitai", platform_post_id="1", prompt="a cat", media_type="image")
    db_session.add(p)
    db_session.flush()
    assert p.id is not None
    assert p.origin == "scraped"
    assert p.params == {} or p.params is None


def test_dedupe_constraint(app_env, db_session):
    from sqlalchemy.exc import IntegrityError
    db_session.add(Post(platform="civitai", platform_post_id="x", media_type="image"))
    db_session.flush()
    db_session.add(Post(platform="civitai", platform_post_id="x", media_type="image"))
    try:
        db_session.flush()
        raise AssertionError("expected IntegrityError")
    except IntegrityError:
        db_session.rollback()


def test_fts_round_trip(app_env):
    with db_mod.session_scope() as s:
        p = Post(platform="civitai", platform_post_id="9",
                 prompt="neon cyberpunk alley at night, cinematic",
                 model_name="FLUX.1 [dev]", media_type="image")
        s.add(p)
        s.flush()
        fts.index_post(s, p.id, p.prompt, p.model_name, ["cyberpunk"])
        pid = p.id
    with db_mod.session_scope() as s:
        assert fts.search_posts(s, "cyberpunk") == [pid]
        assert fts.search_posts(s, "cyberp") == [pid]  # prefix as-you-type
        assert fts.search_posts(s, "flux") == [pid]    # model column matched
        assert fts.search_posts(s, "zebra") == []
        fts.deindex_post(s, pid)
    with db_mod.session_scope() as s:
        assert fts.search_posts(s, "cyberpunk") == []


def test_fts_saved_prompts(app_env):
    with db_mod.session_scope() as s:
        sp = SavedPrompt(text="an isometric diorama of a tokyo street", origin="manual")
        s.add(sp)
        s.flush()
        fts.index_saved_prompt(s, sp.id, sp.text, "flux")
        spid = sp.id
    with db_mod.session_scope() as s:
        assert fts.search_saved_prompts(s, "isometric tokyo") == [spid]


def test_fts_query_is_safe(app_env):
    with db_mod.session_scope() as s:
        # hostile syntax must not raise
        assert fts.search_posts(s, 'AND OR NOT ") ( * :') == []
        assert fts.search_posts(s, "   ") == []


def test_settings_precedence(app_env, monkeypatch):
    with db_mod.session_scope() as s:
        # code default
        assert settings_store.get(s, "image_quality") == 82
        # env default overrides code default
        monkeypatch.setenv("PF_IMAGE_QUALITY", "70")
        assert settings_store.get(s, "image_quality") == 70
        # DB overrides env
        settings_store.put(s, "image_quality", 90)
        assert settings_store.get(s, "image_quality") == 90


def test_settings_secret_masking_and_unchanged(app_env):
    with db_mod.session_scope() as s:
        settings_store.put(s, "civitai_api_key", "supersecret1234")
        masked = settings_store.all_masked(s)
        assert masked["civitai_api_key"] == "••••1234"
        assert "supersecret" not in json.dumps(masked)
        # sentinel write keeps stored secret
        settings_store.put(s, "civitai_api_key", settings_store.UNCHANGED)
        assert settings_store.get(s, "civitai_api_key") == "supersecret1234"


def test_settings_bool_coercion(app_env, monkeypatch):
    monkeypatch.setenv("PF_KEEP_ORIGINALS", "true")
    with db_mod.session_scope() as s:
        assert settings_store.get(s, "keep_originals") is True


def test_setting_row_json(app_env, db_session):
    db_session.add(Setting(key="x", value=json.dumps({"a": 1})))
    db_session.flush()
    assert json.loads(db_session.get(Setting, "x").value) == {"a": 1}


def test_alias_normalization():
    for name in ("flux.1-dev", "Flux Dev", "FLUX.1 [dev]", "Flux Pro 1.1 Ultra"):
        assert normalize_model(name) == "flux", name
    assert normalize_model("SDXL 1.0") == "sdxl"
    assert normalize_model("Stable Diffusion XL Turbo") == "sdxl"
    assert normalize_model("Stable Diffusion 3.5 Large") == "sd3"
    assert normalize_model("majicMIX realistic") == "majicmix-realistic"  # unknown → own family
    assert normalize_model(None) is None
    assert normalize_model("  ") is None
    assert normalize_model("Kling 1.6 Pro") == "kling"


def test_alias_user_rules():
    rules = {"majicmix": "sd15"}
    assert normalize_model("majicMIX realistic", rules) == "sd15"


def test_display_family():
    assert display_family("flux") == "Flux"
    assert display_family("sdxl") == "SDXL"
    assert display_family("some-new-model") == "Some New Model"


def test_tag_case_insensitive_unique(app_env):
    from sqlalchemy.exc import IntegrityError
    with db_mod.session_scope() as s:
        s.add(Tag(name="Cyberpunk"))
        s.flush()
        s.add(Tag(name="cyberpunk"))
        try:
            s.flush()
            raise AssertionError("expected IntegrityError")
        except IntegrityError:
            s.rollback()


def test_logbus_history():
    from promptforge.logbus import LogBus
    b = LogBus(history_size=3)
    for i in range(5):
        b.info("test", f"msg{i}")
    h = b.history()
    assert len(h) == 3
    assert h[-1]["message"] == "msg4"
