"""Template generation (7.1, 7.3): each collection's style profile distills
into a visual prompt template — schema_json (form definition), text_template
(assembly skeleton), ref_slots, recommended model. Exports/imports in both
JSON and written-text formats, round-trip identical."""
from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import select

from ..db import session_scope
from ..models import Collection, CollectionPost, Post, Template
from . import stats

VIDEO_FAMILIES = {"sora", "veo", "kling", "runway", "pika", "hunyuan", "wan",
                  "luma", "hailuo", "mochi", "ltx-video", "cogvideo", "svd",
                  "seedance"}


# --------------------------------------------------------------- assembly ---
def assemble(text_template: str, values: dict) -> str:
    """Fill {slot} placeholders; unfilled slots vanish cleanly (commas tidied)."""
    def sub(m: re.Match) -> str:
        val = values.get(m.group(1))
        if val is None:
            return ""
        if isinstance(val, list):
            return ", ".join(str(v) for v in val if str(v).strip())
        return str(val).strip()

    out = re.sub(r"\{(\w+)\}", sub, text_template)
    out = re.sub(r"\s*,\s*(?:,\s*)+", ", ", out)          # collapse ", , ,"
    out = re.sub(r"(?:^|\n)\s*,\s*", lambda m: m.group(0).replace(",", ""), out)
    out = re.sub(r",\s*$", "", out.strip())
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+,", ",", out)
    return out.strip(" ,\n")


# ------------------------------------------------------------- generation ---
def build_schema_for_collection(collection_id: int) -> tuple[dict, str, list, str | None]:
    """Deterministic template build from member-prompt vocabulary.
    → (schema_json, text_template, ref_slots, recommended_model)."""
    with session_scope() as s:
        collection = s.get(Collection, collection_id)
        if collection is None:
            raise ValueError(f"Collection {collection_id} not found")
        family = collection.model_family
        rows = s.execute(
            select(Post.prompt).join(CollectionPost,
                                     CollectionPost.post_id == Post.id)
            .where(CollectionPost.collection_id == collection_id,
                   Post.prompt.is_not(None))
            .order_by(CollectionPost.added_at.desc()).limit(120)).all()

    cats: dict[str, Counter] = {c: Counter() for c in stats.CATEGORY_LEXICON}
    for (prompt,) in rows:
        for phrase in stats.extract_phrases(prompt or ""):
            cats[stats.categorize(phrase)][phrase] += 1

    def opts(cat: str, n: int, fallback: list[str]) -> list[str]:
        found = [p for p, _ in cats[cat].most_common(n)]
        return found if len(found) >= 3 else list(dict.fromkeys(found + fallback))[:n]

    is_video = family in VIDEO_FAMILIES

    slots = [
        {"key": "subject", "label": "Subject", "type": "text",
         "placeholder": "what the image is of — the one thing that must be right",
         "required": True},
        {"key": "style", "label": "Style", "type": "chips",
         "options": opts("style", 10, ["cinematic", "photorealistic",
                                       "illustration", "film still"]),
         "default": opts("style", 1, ["cinematic"])[:1]},
        {"key": "lighting", "label": "Lighting", "type": "select",
         "options": opts("lighting", 10, ["golden hour", "soft window light",
                                          "neon glow", "hard rim light"]),
         "default": ""},
        {"key": "palette", "label": "Palette / grade", "type": "select",
         "options": opts("palette", 10, ["muted earth tones", "teal and orange",
                                         "pastel", "high-contrast monochrome"]),
         "default": ""},
        {"key": "camera", "label": "Camera", "type": "select",
         "options": opts("camera", 10, ["85mm portrait", "wide establishing shot",
                                        "macro detail", "top-down"]),
         "default": ""},
        {"key": "mood", "label": "Mood", "type": "select",
         "options": opts("mood", 8, ["serene", "dramatic", "mysterious"]),
         "default": ""},
    ]
    if is_video:
        slots.append({"key": "motion", "label": "Camera motion", "type": "select",
                      "options": opts("motion", 10, ["slow dolly-in", "orbit",
                                                     "handheld follow",
                                                     "static locked shot"]),
                      "default": ""})
    slots.append({"key": "detail", "label": "Extra details", "type": "text",
                  "placeholder": "anything else — wardrobe, props, era",
                  "required": False})

    parts = ["{subject}", "{style}", "{lighting}", "{palette}", "{camera}"]
    if is_video:
        parts.append("{motion}")
    parts += ["{mood}", "{detail}"]
    text_template = ", ".join(parts)

    ref_slots = [
        {"key": "style_ref", "label": "Style reference", "role": "style",
         "required": False},
        {"key": "character_ref", "label": "Character reference",
         "role": "character", "required": False},
    ]
    schema = {"slots": slots, "video": is_video}
    return schema, text_template, ref_slots, family


def sync_template_for_collection(collection_id: int) -> int | None:
    """Create/refresh the collection's template from its (updated) style
    profile. User-edited templates are left alone (D: user edits win)."""
    with session_scope() as s:
        collection = s.get(Collection, collection_id)
        if collection is None:
            return None
        existing = s.execute(select(Template).where(
            Template.collection_id == collection_id)).scalar_one_or_none()
        if existing is not None and (existing.schema_json or {}).get("user_edited"):
            return existing.id
        name = f"{collection.name} style"
    schema, text_template, ref_slots, family = build_schema_for_collection(collection_id)
    with session_scope() as s:
        existing = s.execute(select(Template).where(
            Template.collection_id == collection_id)).scalar_one_or_none()
        if existing is None:
            t = Template(collection_id=collection_id, name=name,
                         schema_json=schema, text_template=text_template,
                         ref_slots=ref_slots, recommended_model=family)
            s.add(t)
            s.flush()
            return t.id
        existing.schema_json = schema
        existing.text_template = text_template
        existing.ref_slots = ref_slots
        existing.recommended_model = family
        existing.version = (existing.version or 1) + 1
        s.flush()
        return existing.id


# ---------------------------------------------------------- export/import ---
def export_json(t: Template) -> dict:
    return {
        "format": "promptforge-template/1",
        "name": t.name,
        "version": t.version,
        "recommended_model": t.recommended_model,
        "schema": t.schema_json,
        "text_template": t.text_template,
        "ref_slots": t.ref_slots,
    }


def import_json(data: dict, collection_id: int | None = None) -> int:
    if data.get("format") != "promptforge-template/1":
        raise ValueError("Not a PromptForge template JSON "
                         f"(format={data.get('format')!r})")
    with session_scope() as s:
        existing = None
        if collection_id:
            existing = s.execute(select(Template).where(
                Template.collection_id == collection_id)).scalar_one_or_none()
        if existing is None:
            t = Template(collection_id=collection_id, name=data.get("name", "Imported"),
                         version=int(data.get("version", 1)),
                         schema_json=data.get("schema") or {},
                         text_template=data.get("text_template", ""),
                         ref_slots=data.get("ref_slots") or [],
                         recommended_model=data.get("recommended_model"))
            s.add(t)
            s.flush()
            return t.id
        existing.name = data.get("name", existing.name)
        existing.version = int(data.get("version", existing.version))
        existing.schema_json = data.get("schema") or {}
        existing.text_template = data.get("text_template", "")
        existing.ref_slots = data.get("ref_slots") or []
        existing.recommended_model = data.get("recommended_model")
        s.flush()
        return existing.id


def export_text(t: Template) -> str:
    lines = [f"# PromptForge Template: {t.name}",
             f"version: {t.version}",
             f"recommended-model: {t.recommended_model or ''}",
             "", "## Slots"]
    for slot in (t.schema_json or {}).get("slots", []):
        bits = [f"- {slot['key']} ({slot['type']})"]
        if slot.get("required"):
            bits.append("required")
        line = " ".join(bits)
        if slot.get("options"):
            line += ": " + " | ".join(slot["options"])
        default = slot.get("default")
        if default:
            if isinstance(default, list):
                default = ", ".join(default)
            line += f"  [default: {default}]"
        if slot.get("placeholder"):
            line += f"  (hint: {slot['placeholder']})"
        if slot.get("label"):
            line += f"  {{label: {slot['label']}}}"
        lines.append(line)
    lines += ["", "## Refs"]
    for ref in t.ref_slots or []:
        req = "required" if ref.get("required") else "optional"
        lines.append(f"- {ref['key']} ({ref.get('role', 'other')}) {req}: "
                     f"{ref.get('label', ref['key'])}")
    lines += ["", "## Template", t.text_template, ""]
    return "\n".join(lines)


_slot_re = re.compile(
    r"^- (?P<key>\w+) \((?P<type>\w+)\)(?P<req> required)?"
    r"(?::\s*(?P<options>[^[({\n]*?))?"
    r"(?:\s*\[default:\s*(?P<default>[^\]]*)\])?"
    r"(?:\s*\(hint:\s*(?P<hint>[^)]*)\))?"
    r"(?:\s*\{label:\s*(?P<label>[^}]*)\})?\s*$")
_ref_re = re.compile(
    r"^- (?P<key>\w+) \((?P<role>\w+)\) (?P<req>required|optional): (?P<label>.+)$")


def import_text(text: str, collection_id: int | None = None) -> int:
    m = re.search(r"^# PromptForge Template: (.+)$", text, flags=re.M)
    if not m:
        raise ValueError("Not a PromptForge written template (missing header).")
    name = m.group(1).strip()
    version = 1
    vm = re.search(r"^version:\s*(\d+)", text, flags=re.M)
    if vm:
        version = int(vm.group(1))
    rec = None
    rm = re.search(r"^recommended-model:\s*(.*)$", text, flags=re.M)
    if rm:
        rec = rm.group(1).strip() or None

    def section(title: str) -> str:
        sm = re.search(rf"## {title}\n(.*?)(?=\n## |\Z)", text, flags=re.S)
        return sm.group(1).strip() if sm else ""

    slots = []
    for line in section("Slots").splitlines():
        lm = _slot_re.match(line.strip())
        if not lm:
            continue
        slot: dict = {"key": lm.group("key"), "type": lm.group("type"),
                      "label": (lm.group("label") or lm.group("key").title()).strip()}
        if lm.group("req"):
            slot["required"] = True
        options = (lm.group("options") or "").strip()
        if options:
            slot["options"] = [o.strip() for o in options.split("|") if o.strip()]
        default = (lm.group("default") or "").strip()
        if default:
            slot["default"] = ([d.strip() for d in default.split(",")]
                               if slot["type"] == "chips" else default)
        hint = (lm.group("hint") or "").strip()
        if hint:
            slot["placeholder"] = hint
        slots.append(slot)

    refs = []
    for line in section("Refs").splitlines():
        rm2 = _ref_re.match(line.strip())
        if rm2:
            refs.append({"key": rm2.group("key"), "role": rm2.group("role"),
                         "required": rm2.group("req") == "required",
                         "label": rm2.group("label").strip()})

    return import_json({
        "format": "promptforge-template/1",
        "name": name, "version": version, "recommended_model": rec,
        "schema": {"slots": slots},
        "text_template": section("Template"),
        "ref_slots": refs,
    }, collection_id)
