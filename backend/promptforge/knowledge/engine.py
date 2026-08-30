"""Knowledge engine orchestrator (6.5, 6.7): deterministic layer on every
ingest, batched+budgeted LLM analysis on a schedule and after generation
sessions, style profiles per collection, prompt-cluster distillation."""
from __future__ import annotations

import json
import re
import threading
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import session_scope
from ..logbus import bus
from ..models import Collection, CollectionPost, Post
from ..pipeline import hooks
from . import files, stats, techniques

ANALYSIS_BATCH = 50
_dirty_collections: set[int] = set()
_dirty_lock = threading.Lock()

SYSTEM_PROMPT = (
    "You are the knowledge engine of PromptForge, a self-hosted library of AI "
    "image/video prompts. You study real prompts for one generation model and "
    "maintain a compact, practical knowledge file about how to prompt it well. "
    "Be concrete and terse; no filler; every sentence must help someone write "
    "a better prompt for THIS model. Reply ONLY with valid JSON."
)


# ------------------------------------------------------------ ingest hook ---
def _on_post_ingested(post_id: int) -> None:
    with session_scope() as s:
        post = s.get(Post, post_id)
        if post is None:
            return
        detected = techniques.detect_techniques(
            " ".join(x for x in (post.prompt, post.negative_prompt) if x))
        if detected:
            post.technique_tags = sorted(set((post.technique_tags or []) + detected))
        family = post.model_family
        prompt, params, media_type = post.prompt, dict(post.params or {}), post.media_type
    if family:
        data = stats.update_family_stats(family, prompt, params, media_type, post_id)
        files.update_stats_block(family, stats.render_stats_section(data))


def register_hooks() -> None:
    hooks.register("knowledge", _on_post_ingested)


# ------------------------------------------------------------- LLM helpers --
def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, dict) else None
    except ValueError:
        return None


def _llm(purpose: str, system: str, user: str, max_tokens: int = 1800) -> str | None:
    """Budgeted call; returns None when unconfigured/over budget/offline —
    the deterministic layer keeps working regardless."""
    from ..llm.client import BudgetExceeded, LLMError, LLMNotConfigured, run_llm
    try:
        return run_llm(purpose, system, user, max_tokens=max_tokens)
    except LLMNotConfigured:
        return None
    except BudgetExceeded as e:
        bus.warn("knowledge", str(e))
        return None
    except LLMError as e:
        # companion offline → queue the job for later drain (D30)
        if "companion" in str(e).lower() and "offline" in str(e).lower():
            _queue_job(purpose, system, user)
        bus.error("knowledge", f"LLM call failed ({purpose}): {e}")
        return None


def _queue_job(purpose: str, system: str, user: str) -> None:
    from ..models import LlmJob
    with session_scope() as s:
        s.add(LlmJob(kind=purpose,
                     payload={"system": system, "user": user}))
    bus.info("knowledge", f"queued {purpose} job until the companion is back online")


# ------------------------------------------------------ scheduled learning --
def scheduled_learning_pass() -> dict:
    """Hourly: per family, analyze up to ANALYSIS_BATCH new prompts; refresh
    dirty style profiles. Free deterministic stats are already current."""
    summary = {"families": 0, "analyzed": 0, "profiles": 0}
    with session_scope() as s:
        families = [r[0] for r in s.execute(
            select(Post.model_family).where(Post.model_family.is_not(None))
            .group_by(Post.model_family))]
    for family in families:
        analyzed = analyze_family(family)
        if analyzed:
            summary["families"] += 1
            summary["analyzed"] += analyzed
    with _dirty_lock:
        dirty = list(_dirty_collections)
        _dirty_collections.clear()
    for cid in dirty:
        refresh_style_profile(cid)
        summary["profiles"] += 1
    return summary


def analyze_family(family: str, batch: int = ANALYSIS_BATCH) -> int:
    data = stats.load_stats(family)
    last_id = int(data.get("last_analyzed_post_id", 0))
    with session_scope() as s:
        rows = s.execute(
            select(Post.id, Post.prompt, Post.media_type, Post.favorite)
            .where(Post.model_family == family, Post.id > last_id,
                   Post.prompt.is_not(None))
            .order_by(Post.id).limit(batch)).all()
    if not rows:
        return 0

    prompts_block = "\n".join(
        f"[{pid}]{'[video]' if mt == 'video' else ''} {prompt[:220]}"
        for pid, prompt, mt, _fav in rows)
    file_path = files.ensure_model_file(family)
    _fm, body = files.read_md(file_path)
    current_profile = files.get_section(body, "Profile")[:800]
    stats_digest = stats.render_stats_section(data)

    user = f"""Model family: {family}
Current profile (may be empty/outdated):
{current_profile}

Deterministic stats:
{stats_digest}

{len(rows)} new prompts (id in brackets; [video] marks video posts):
{prompts_block}

Update the model knowledge. Reply with JSON:
{{
 "profile": "2-4 sentences: prompt syntax style (natural language vs tag list), ideal prompt length, parameter sweet spots",
 "guidance": "4-8 short bullet lines (markdown '-') of model-specific prompting advice: strengths, weaknesses, camera/motion/audio handling",
 "reference_images": "1-3 sentences on how refs are best used with this model (roles, weights) or 'unknown'",
 "failure_patterns": "0-4 bullet lines of recurring failure patterns, or ''",
 "notes": ["0-3 one-line reusable workflow notes distilled from recurring prompt patterns"],
 "exemplar_ids": [up to 6 post ids of the strongest, most instructive prompts],
 "video_techniques": {{"<post_id>": ["technique-slug", ...]}}
}}
Allowed technique slugs: {', '.join(techniques.all_slugs())}"""

    raw = _llm("model-analysis", SYSTEM_PROMPT, user)
    max_seen = max(pid for pid, *_ in rows)
    if raw is None:
        # deterministic-only progress: cluster notes still get recorded
        notes = _cluster_notes([p for _, p, _, _ in rows])
        if notes:
            fm2, body2 = files.read_md(file_path)
            for note in notes[:2]:
                body2 = files.append_learned_note(body2, note)
            files.write_md(file_path, fm2, body2)
        data["last_analyzed_post_id"] = max_seen
        stats.save_stats(family, data)
        return 0

    result = _extract_json(raw)
    if result:
        _merge_analysis(family, result, [pid for pid, *_ in rows])
    data = stats.load_stats(family)
    data["last_analyzed_post_id"] = max_seen
    stats.save_stats(family, data)
    return len(rows)


def _merge_analysis(family: str, result: dict, batch_ids: list[int]) -> None:
    path = files.ensure_model_file(family)
    fm, body = files.read_md(path)
    if isinstance(result.get("profile"), str) and result["profile"].strip():
        body = files.replace_section(body, "Profile", result["profile"].strip())
    if isinstance(result.get("guidance"), str) and result["guidance"].strip():
        body = files.replace_section(body, "Prompting guidance",
                                     result["guidance"].strip())
    if isinstance(result.get("reference_images"), str) and \
            result["reference_images"].strip().lower() not in ("", "unknown"):
        body = files.replace_section(body, "Reference images",
                                     result["reference_images"].strip())
    if isinstance(result.get("failure_patterns"), str) and \
            result["failure_patterns"].strip():
        body = files.replace_section(body, "Failure patterns",
                                     result["failure_patterns"].strip())
    for note in (result.get("notes") or [])[:3]:
        if isinstance(note, str) and note.strip():
            body = files.append_learned_note(body, note)
    ex_ids = [i for i in (result.get("exemplar_ids") or [])
              if isinstance(i, int) and i in set(batch_ids)][:6]
    if ex_ids:
        existing = re.findall(r"\d+", files.get_section(body, "Exemplars"))
        merged = list(dict.fromkeys([str(i) for i in ex_ids] + existing))[:12]
        body = files.replace_section(body, "Exemplars",
                                     "post ids: " + ", ".join(merged))
    fm["analyzed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    files.write_md(path, fm, body)

    vt = result.get("video_techniques") or {}
    if isinstance(vt, dict) and vt:
        allowed = set(techniques.all_slugs())
        with session_scope() as s:
            for pid_str, tags in vt.items():
                try:
                    pid = int(pid_str)
                except (TypeError, ValueError):
                    continue
                post = s.get(Post, pid)
                if post is None or not isinstance(tags, list):
                    continue
                clean = [t for t in tags if t in allowed]
                if clean:
                    post.technique_tags = sorted(
                        set((post.technique_tags or []) + clean))


def _cluster_notes(prompts: list[str], min_count: int = 3) -> list[str]:
    """Deterministic inspiration-cluster detection: recurring 3-word shingles
    across prompts become reusable workflow notes."""
    shingles: Counter = Counter()
    for prompt in prompts:
        words = [w for w in re.findall(r"[a-z][a-z'-]+", prompt.lower())
                 if w not in stats.STOPWORDS]
        seen = set()
        for i in range(len(words) - 2):
            sh = " ".join(words[i:i + 3])
            if sh not in seen:
                shingles[sh] += 1
                seen.add(sh)
    return [f"Recurring pattern across {n} scraped prompts: “{sh}”"
            for sh, n in shingles.most_common(3) if n >= min_count]


# ------------------------------------------------------------ generations ---
def generation_event(post_id: int | None, family: str | None, prompt: str,
                     outcome: str, collection_id: int | None = None,
                     template_name: str | None = None) -> None:
    """Every in-app generation is a learning event (starred / saved /
    discarded / regenerated)."""
    if family:
        try:
            data = stats.update_family_stats(family, prompt, {}, "image", post_id)
            files.update_stats_block(family, stats.render_stats_section(data))
            path = files.ensure_model_file(family)
            fm, body = files.read_md(path)
            snippet = prompt[:90].replace("\n", " ")
            note = (f"Generation {outcome}"
                    + (f" via template “{template_name}”" if template_name else "")
                    + f": “{snippet}…”")
            body = files.append_learned_note(body, note)
            files.write_md(path, fm, body)
        except Exception as e:
            bus.error("knowledge", f"generation learning failed: {e}")
    if collection_id:
        mark_collection_dirty(collection_id)


# ---------------------------------------------------------- style profiles --
def mark_collection_dirty(collection_id: int) -> None:
    with _dirty_lock:
        _dirty_collections.add(collection_id)


STYLE_SYSTEM = (
    "You distill a cohesive visual style profile from a curated collection of "
    "AI art prompts. Concrete, compact, reusable vocabulary only. Reply ONLY "
    "with valid JSON.")


def refresh_style_profile(collection_id: int, use_llm: bool = True) -> str | None:
    with session_scope() as s:
        collection = s.get(Collection, collection_id)
        if collection is None:
            path = files.style_file_path(collection_id)
            path.unlink(missing_ok=True)
            return None
        rows = s.execute(
            select(Post.id, Post.prompt, Post.model_family, Post.media_type)
            .join(CollectionPost, CollectionPost.post_id == Post.id)
            .where(CollectionPost.collection_id == collection_id,
                   Post.prompt.is_not(None))
            .order_by(CollectionPost.added_at.desc()).limit(80)).all()
        name = collection.name
        family = collection.model_family

    # deterministic distillation (always)
    cat_counters: dict[str, Counter] = {c: Counter() for c in stats.CATEGORY_LEXICON}
    for _pid, prompt, _fam, _mt in rows:
        for phrase in stats.extract_phrases(prompt or ""):
            cat_counters[stats.categorize(phrase)][phrase] += 1

    def top(cat: str, n: int = 10) -> list[str]:
        return [p for p, _ in cat_counters[cat].most_common(n)]

    sections = {
        "Style descriptors": ", ".join(top("style") + top("mood", 6)) or "not enough data yet",
        "Recurring subjects": ", ".join(top("subject", 12)) or "not enough data yet",
        "Palette & lighting": ", ".join(top("palette", 8) + top("lighting", 8)) or "not enough data yet",
        "Camera language": ", ".join(top("camera", 8) + top("motion", 6)) or "not enough data yet",
        "Per-model adaptation": (f"Collection is scoped to **{family}** — see "
                                 f"`models/{family}.md`." if family
                                 else "Mixed-model collection."),
        "Reference image guidance": ("Pick 1–2 exemplar images from this "
                                     "collection as style refs; keep subject "
                                     "prompts clean and let refs carry the look."),
    }

    if use_llm and rows:
        prompts_block = "\n".join(f"- {(p or '')[:200]}" for _i, p, _f, _m in rows[:40])
        user = f"""Collection “{name}” ({len(rows)} prompts, model family: {family or 'mixed'}).
Prompts:
{prompts_block}

Reply with JSON:
{{
 "style_descriptors": "one comma-separated line of the distilled style vocabulary",
 "recurring_subjects": "one comma-separated line",
 "palette_lighting": "one comma-separated line of palette + lighting vocabulary",
 "camera_language": "one comma-separated line (shots, angles, movement)",
 "adaptation": "1-2 sentences on adapting this style to other models",
 "reference_guidance": "1-2 sentences on using reference images to reproduce this style"
}}"""
        raw = _llm("style-profile", STYLE_SYSTEM, user, max_tokens=800)
        result = _extract_json(raw) if raw else None
        if result:
            mapping = {
                "Style descriptors": "style_descriptors",
                "Recurring subjects": "recurring_subjects",
                "Palette & lighting": "palette_lighting",
                "Camera language": "camera_language",
                "Per-model adaptation": "adaptation",
                "Reference image guidance": "reference_guidance",
            }
            for section, key in mapping.items():
                val = result.get(key)
                if isinstance(val, str) and val.strip():
                    sections[section] = val.strip()

    path = files.style_file_path(collection_id)
    body = f"# Style profile — {name}\n"
    for section, content in sections.items():
        body += f"\n## {section}\n{content}\n"
    files.write_md(path, {"kind": "style", "collection_id": collection_id,
                          "collection": name, "family": family,
                          "posts_sampled": len(rows)}, body)
    # keep the collection's template in sync (Phase 7)
    try:
        from . import template_gen
        template_gen.sync_template_for_collection(collection_id)
    except ImportError:
        pass
    return str(path)
