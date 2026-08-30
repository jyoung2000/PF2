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
