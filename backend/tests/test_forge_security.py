"""Security posture for the Phase-2 additions (spec §Security):
secret redaction, artifact path containment, subprocess argument safety."""
import pytest

from promptforge import db as db_mod, settings_store
from promptforge.forge import artifacts


def test_muapi_key_is_masked_and_never_echoed(client, app_env):
    saved = client.put("/api/settings", json={"muapi_api_key": "mu-supersecret-1234"})
    assert "muapi_api_key" in saved.json()["applied"], "the key must be a known setting"
    body = client.get("/api/settings").json()["settings"]
    shown = str(body.get("muapi_api_key"))
    assert "supersecret" not in shown and "••" in shown
    assert shown.endswith("1234")                      # last4 only, D23
    # "__unchanged__" keeps the stored value instead of overwriting it
    client.put("/api/settings", json={"muapi_api_key": "__unchanged__"})
    with db_mod.session_scope() as s:
        assert settings_store.get(s, "muapi_api_key") == "mu-supersecret-1234"
    # the whole settings payload never contains the raw key
    assert "mu-supersecret-1234" not in client.get("/api/settings").text


def test_provider_key_never_reaches_tool_or_job_surfaces(client, app_env):
    with db_mod.session_scope() as s:
        settings_store.put(s, "muapi_api_key", "mu-supersecret-1234")
    for path in ("/api/forge/tools", "/api/forge/models", "/api/forge/usage",
                 "/api/forge/evaluators"):
        assert "mu-supersecret-1234" not in client.get(path).text, path


def test_artifact_store_rejects_traversal_and_foreign_paths(app_env):
    for bad in ("../etc/passwd", "forge/artifacts/../../secret",
                "/etc/passwd", "media/x.png", "forge/artifactsevil/x"):
        with pytest.raises(ValueError):
            artifacts.resolve(bad)
    good = artifacts.artifacts_dir() / "ok.txt"
    good.write_text("hi")
    assert artifacts.resolve("forge/artifacts/ok.txt") == good.resolve()


def test_artifact_extensions_are_allowlisted(app_env):
    # a provider-supplied name cannot smuggle an executable extension
    assert artifacts._extension("https://x/y/evil.sh", "audio") == ".mp3"
    assert artifacts._extension("https://x/y/a.mp3?token=1", "audio") == ".mp3"
    assert artifacts._extension("https://x/model.glb", "3d") == ".glb"
    assert artifacts._extension("https://x/../../etc/passwd", "text") == ".txt"


def test_clip_node_passes_paths_as_arguments_not_shell(app_env):
    """ffmpeg is invoked with an argv list — a crafted filename cannot inject
    a second command (no shell=True anywhere in the forge package)."""
    import pathlib
    forge_dir = pathlib.Path("promptforge/forge")
    for path in forge_dir.glob("*.py"):
        assert "shell=True" not in path.read_text(), path
