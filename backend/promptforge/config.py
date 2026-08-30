"""Environment configuration. .env values are DEFAULTS; the settings table
(settings_store) overrides them live from the GUI."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load a .env from the repo root (or cwd) once, without overriding real env.
_here = Path(__file__).resolve()
for candidate in (_here.parents[2] / ".env", Path.cwd() / ".env"):
    if candidate.is_file():
        load_dotenv(candidate, override=False)
        break


def _resolve_data_dir(env: dict) -> Path:
    explicit = env.get("PF_DATA_DIR")
    if explicit:
        return Path(explicit)
    docker_data = Path("/data")
    if docker_data.is_dir() and os.access(docker_data, os.W_OK):
        return docker_data
    return _here.parents[2] / "data"


@dataclass
class Config:
    data_dir: Path
    port: int = 5643
    env: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "promptforge.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def knowledge_dir(self) -> Path:
        return self.data_dir / "knowledge"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def refs_dir(self) -> Path:
        return self.data_dir / "refs"

    @property
    def ffmpeg(self) -> str | None:
        return shutil.which("ffmpeg")

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.media_dir, self.knowledge_dir,
                  self.knowledge_dir / "models", self.knowledge_dir / "styles",
                  self.knowledge_dir / "stats", self.sessions_dir, self.refs_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_config(env: dict | None = None) -> Config:
    env = dict(os.environ if env is None else env)
    cfg = Config(data_dir=_resolve_data_dir(env), env=env)
    return cfg


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
        _config.ensure_dirs()
    return _config


def set_config(cfg: Config | None) -> None:
    """Test hook: swap the active config (pass None to reset to env)."""
    global _config
    _config = cfg
    if cfg is not None:
        cfg.ensure_dirs()
