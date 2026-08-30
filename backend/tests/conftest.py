import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Force env-driven secrets off during tests regardless of the host machine.
for var in ("CIVITAI_API_KEY", "DISCORD_BOT_TOKEN", "BASEROW_TOKEN", "FAL_API_KEY",
            "REPLICATE_API_TOKEN", "WAVESPEED_API_KEY", "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY", "PF_LLM_PROVIDER", "LEXICA_SEARCH_TERMS",
            "BASEROW_URL", "BASEROW_TABLE_ID", "DISCORD_CHANNEL_ID"):
    os.environ.pop(var, None)

from promptforge import config as cfg_mod  # noqa: E402
from promptforge import db as db_mod  # noqa: E402


@pytest.fixture()
def app_env(tmp_path):
    """Fresh DATA_DIR + DB per test."""
    cfg = cfg_mod.Config(data_dir=tmp_path / "data")
    cfg_mod.set_config(cfg)
    db_mod.dispose_db()
    db_mod.init_db()
    yield cfg
    db_mod.dispose_db()
    cfg_mod.set_config(None)


@pytest.fixture()
def db_session(app_env):
    with db_mod.session_scope() as s:
        yield s


@pytest.fixture()
def client(app_env):
    """TestClient over a fresh app bound to this test's DATA_DIR."""
    from fastapi.testclient import TestClient

    from promptforge.main import create_app
    with TestClient(create_app()) as c:
        yield c


def seed_post(**kw):
    """Insert a Post row (+FTS) directly; returns the post id."""
    from promptforge import fts
    from promptforge.models import Post

    defaults = dict(platform="civitai", media_type="image", prompt="a red fox",
                    model_name="flux.1-dev", model_family="flux",
                    media_path="media/civitai/x.webp",
                    thumb_path="media/civitai/thumbs/x.webp",
                    media_width=512, media_height=768, params={})
    defaults.update(kw)
    if "platform_post_id" not in defaults:
        import uuid
        defaults["platform_post_id"] = uuid.uuid4().hex[:12]
    with db_mod.session_scope() as s:
        p = Post(**defaults)
        s.add(p)
        s.flush()
        fts.index_post(s, p.id, p.prompt, p.model_name, [])
        return p.id
