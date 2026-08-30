"""Knowledge file store (6.4, D11): markdown + YAML frontmatter under
DATA_DIR/knowledge/. Hard 16KB cap enforced on write — summarize/merge in
place, never append forever. Exemplars stored as post IDs only."""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..aliases import display_family
from ..config import get_config

SIZE_CAP = 16 * 1024
STATS_BEGIN = "<!-- stats:begin -->"
STATS_END = "<!-- stats:end -->"

_PACKAGED_FOUNDATION = Path(__file__).parent / "foundation.md"


def foundation_path() -> Path:
    return get_config().knowledge_dir / "foundation.md"


def model_file_path(family: str) -> Path:
    return get_config().knowledge_dir / "models" / f"{family}.md"


def style_file_path(collection_id: int) -> Path:
    return get_config().knowledge_dir / "styles" / f"collection-{collection_id}.md"


def install_foundation() -> None:
    """Copy the packaged foundation into DATA_DIR on boot (never overwrite a
    newer user-edited copy unless the packaged version bumped)."""
    dest = foundation_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copyfile(_PACKAGED_FOUNDATION, dest)
        return
    try:
        packaged_fm, _ = read_md(_PACKAGED_FOUNDATION)
        local_fm, _ = read_md(dest)
        if int(packaged_fm.get("version", 1)) > int(local_fm.get("version", 0)):
            shutil.copyfile(_PACKAGED_FOUNDATION, dest)
    except Exception:
        pass


def read_md_bytes(raw: bytes) -> tuple[dict, str]:
    """read_md over in-memory bytes (pack import)."""
    text = raw.decode("utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
                return (fm if isinstance(fm, dict) else {}), parts[2].lstrip("\n")
            except yaml.YAMLError:
                pass
    return {}, text


def read_md(path: Path) -> tuple[dict, str]:
    """→ (frontmatter, body). Tolerates files without frontmatter."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
                return (fm if isinstance(fm, dict) else {}), parts[2].lstrip("\n")
            except yaml.YAMLError:
                pass
    return {}, text


def write_md(path: Path, fm: dict, body: str) -> None:
    fm = dict(fm)
    fm["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    body = enforce_cap(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    front = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{front}\n---\n\n{body.strip()}\n", encoding="utf-8")


def enforce_cap(body: str, cap: int = SIZE_CAP) -> str:
    """Keep the body under the cap: drop oldest Learned-notes bullets first,
    then trim exemplar ids, then hard-truncate as a last resort."""
    if len(body.encode("utf-8")) <= cap:
        return body

    def drop_oldest_bullet(text: str, section: str) -> str | None:
        m = re.search(rf"(## {re.escape(section)}\n)((?:- .*\n?)+)", text)
        if not m:
            return None
        bullets = [b for b in m.group(2).splitlines() if b.strip()]
        if len(bullets) <= 1:
            return None
        newest_last = "\n".join(bullets[1:]) + "\n"
        return text[:m.start(2)] + newest_last + text[m.end(2):]

    for _ in range(200):
        if len(body.encode("utf-8")) <= cap:
            return body
        trimmed = drop_oldest_bullet(body, "Learned notes")
        if trimmed is None:
            break
        body = trimmed
    # trim exemplar id lists
    m = re.search(r"(## Exemplars\n)([^\n#]*(?:\n(?!#).*)*)", body)
    while m and len(body.encode("utf-8")) > cap:
        ids = re.findall(r"\d+", m.group(2))
        if len(ids) <= 4:
            break
        ids = ids[: len(ids) // 2]
        replacement = "post ids: " + ", ".join(ids) + "\n"
        body = body[:m.start(2)] + replacement + body[m.end(2):]
        m = re.search(r"(## Exemplars\n)([^\n#]*(?:\n(?!#).*)*)", body)
    while len(body.encode("utf-8")) > cap:
        body = body[: int(len(body) * 0.9)]
    return body


def replace_section(body: str, section: str, content: str) -> str:
    """Replace the content under `## section` (creating it at the end if
    missing). Content should not include the heading."""
    pattern = rf"(## {re.escape(section)}\n)(.*?)(?=\n## |\Z)"
    m = re.search(pattern, body, flags=re.S)
    block = content.strip() + "\n"
    if m:
        return body[:m.start(2)] + block + "\n" + body[m.end(2):].lstrip("\n")
    sep = "" if body.endswith("\n\n") else "\n"
    return f"{body.rstrip()}\n{sep}\n## {section}\n{block}"


def get_section(body: str, section: str) -> str:
    m = re.search(rf"## {re.escape(section)}\n(.*?)(?=\n## |\Z)", body, flags=re.S)
    return m.group(1).strip() if m else ""


def append_learned_note(body: str, note: str, max_notes: int = 14) -> str:
    """Add a bullet to ## Learned notes, newest last, deduped, capped."""
    note = "- " + note.strip().lstrip("-").strip()
    existing = get_section(body, "Learned notes")
    bullets = [b.strip() for b in existing.splitlines() if b.strip().startswith("-")]
    if any(_similar(note, b) for b in bullets):
        return body
    bullets.append(note)
    bullets = bullets[-max_notes:]
    return replace_section(body, "Learned notes", "\n".join(bullets))


def _similar(a: str, b: str) -> bool:
    wa = set(re.findall(r"\w+", a.lower()))
    wb = set(re.findall(r"\w+", b.lower()))
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) > 0.7


MODEL_TEMPLATE = """# {label} — model knowledge

Inherits `foundation.md`; everything here is specific to {label}.

## Profile
Syntax style, ideal length and parameter sweet spots appear here after the
first analysis pass. Deterministic stats below update on every ingest.

## Deterministic stats
{stats_begin}
- Posts seen: 0
{stats_end}

## Prompting guidance
_Not analyzed yet — the knowledge engine fills this in as prompts arrive._

## Reference images
_How this model consumes style/character refs — learned from usage._

## Exemplars
post ids: none yet

## Failure patterns
_None recorded yet._

## Learned notes
- Model file created automatically on first sighting.
"""


def ensure_model_file(family: str) -> Path:
    path = model_file_path(family)
    if not path.exists():
        body = MODEL_TEMPLATE.format(label=display_family(family),
                                     stats_begin=STATS_BEGIN,
                                     stats_end=STATS_END)
        write_md(path, {"kind": "model", "family": family,
                        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
                 body)
    return path


def update_stats_block(family: str, rendered: str) -> None:
    path = ensure_model_file(family)
    fm, body = read_md(path)
    pattern = re.compile(re.escape(STATS_BEGIN) + r".*?" + re.escape(STATS_END),
                         flags=re.S)
    replacement = f"{STATS_BEGIN}\n{rendered.strip()}\n{STATS_END}"
    if pattern.search(body):
        body = pattern.sub(lambda _: replacement, body)
    else:
        body = replace_section(body, "Deterministic stats", replacement)
    write_md(path, fm, body)
