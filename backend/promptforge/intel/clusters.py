"""Inspiration clusters (I6.2): deterministic, rule-based groupings over what
is stored — topic, model, technique, style, creator, media, prompt pattern,
camera, palette, subject, engagement. Rebuilt on a schedule into the
`clusters` / `cluster_posts` tables; membership score = Inspiration Score."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from ..aliases import display_family
from ..db import session_scope
from ..knowledge import stats as kstats
from ..models import Cluster, ClusterPost, Creator, Post
from . import provenance

MIN_MEMBERS = 2
MAX_POSTS = 20_000

TOPICS: dict[str, dict[str, Any]] = {
    "cinematic-ai-video": {"label": "Cinematic AI Video", "video": True,
                           "any": ["cinematic", "film still", "movie", "trailer", "anamorphic", "35mm", "dolly", "tracking shot"]},
    "ai-fashion": {"label": "AI Fashion", "any": ["fashion", "runway", "editorial", "haute couture", "streetwear", "outfit", "vogue", "lookbook"]},
    "anime-action": {"label": "Anime Action", "any": ["anime", "manga", "shonen", "mecha", "fight scene", "action pose", "sakuga"]},
    "product-commercials": {"label": "Product Commercials", "any": ["product shot", "commercial", "advertisement", "product photography", "hero product", "packshot", "perfume bottle", "sneaker ad"]},
    "ai-horror": {"label": "AI Horror", "any": ["horror", "eerie", "creepy", "nightmare", "haunted", "terrifying", "found footage", "monster"]},
    "sci-fi": {"label": "Sci-Fi", "any": ["sci-fi", "science fiction", "spaceship", "cyberpunk", "futuristic", "android", "alien", "dystopian", "space station"]},
    "character-consistency": {"label": "Character Consistency", "any": ["character consistency", "consistent character", "character sheet", "same character", "--cref", "reference sheet", "turnaround", "identity consistent"]},
    "comfyui-workflows": {"label": "ComfyUI Workflows", "workflow": True, "any": ["comfyui", "workflow json", "custom node"]},
    "portraits": {"label": "Portraits", "any": ["portrait", "headshot", "close-up of a", "face of"]},
    "landscapes-nature": {"label": "Landscapes & Nature", "any": ["landscape", "mountain", "forest", "ocean", "valley", "waterfall", "desert", "coastline", "nature"]},
    "architecture-interiors": {"label": "Architecture & Interiors", "any": ["architecture", "interior", "building", "brutalist", "cathedral", "living room", "skyscraper", "facade"]},
    "food-drink": {"label": "Food & Drink", "any": ["food", "dish", "dessert", "cocktail", "coffee", "sushi", "cake", "restaurant"]},
    "vehicles": {"label": "Vehicles", "any": ["car", "supercar", "motorcycle", "spaceship", "vehicle", "truck", "race car", "jet"]},
    "animals-creatures": {"label": "Animals & Creatures", "any": ["cat", "dog", "fox", "owl", "dragon", "creature", "wolf", "horse", "whale", "bird"]},
    "abstract-motion": {"label": "Abstract & Motion Graphics", "any": ["abstract", "particles", "fluid simulation", "motion graphics", "kinetic typography", "geometric", "fractal"]},
}
STYLES = {
    "cyberpunk": ["cyberpunk", "neon-lit", "neon city"], "noir": ["noir", "film noir", "chiaroscuro"],
    "watercolor": ["watercolor", "watercolour"], "anime-style": ["anime style", "anime", "cel shaded", "cel-shaded"],
    "photoreal": ["photorealistic", "photoreal", "hyperrealistic", "realistic photo"],
    "3d-render": ["3d render", "octane", "unreal engine", "blender render", "c4d", "redshift"],
    "pixel-art": ["pixel art", "8-bit", "16-bit"], "vaporwave": ["vaporwave", "synthwave", "retrowave"],
    "minimalist": ["minimalist", "minimal", "clean composition"], "surreal": ["surreal", "surrealist", "dreamlike"],
    "vintage-film": ["vintage", "kodak", "portra", "cinestill", "film grain", "polaroid", "1970s", "1980s"],
    "illustration": ["illustration", "concept art", "digital painting", "storybook"],
}
PALETTES = {
    "teal-orange": ["teal and orange", "teal orange", "orange and teal"], "monochrome": ["monochrome", "black and white", "b&w", "grayscale"],
    "pastel": ["pastel"], "neon": ["neon"], "earth-tones": ["earth tones", "earthy", "ochre", "terracotta"],
    "golden": ["golden", "amber", "warm tones"], "cool-blue": ["cool blue", "blue tones", "icy blue", "cyan"],
    "high-contrast": ["high contrast", "harsh shadows", "chiaroscuro"], "muted": ["muted", "desaturated", "faded"],
}
SUBJECTS = {
    "people": ["woman", "man", "girl", "boy", "person", "people", "portrait", "character", "model"],
    "animals": ["cat", "dog", "fox", "owl", "wolf", "horse", "bird", "whale", "lion", "tiger"],
    "vehicles": ["car", "motorcycle", "spaceship", "truck", "jet", "train", "boat"],
    "architecture": ["building", "city", "street", "interior", "room", "cathedral", "tower", "bridge"],
    "nature": ["forest", "mountain", "ocean", "river", "field", "desert", "sky", "storm", "lighthouse"],
    "food": ["food", "cake", "coffee", "sushi", "dish", "fruit"],
    "objects": ["product", "bottle", "watch", "sneaker", "chair", "lamp"],
    "abstract": ["abstract", "particles", "geometric", "fractal", "texture"],
}
ENGAGEMENT_PERCENTILE = 0.9


def _slug_label(slug: str) -> str:
    """'shallow-dof' → 'Shallow Dof', '35mm' stays '35mm' (digits keep case)."""
    return " ".join(w if w[:1].isdigit() else w.capitalize() for w in slug.split("-"))


def _word_hit(text: str, term: str) -> bool:
    if len(term) <= 3:
        return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text) is not None
    return term in text


def assign(view: dict) -> dict[str, list[tuple[str, str]]]:
    """One post view → {kind: [(key, label), ...]}. Pure; reused by trends."""
    text = " ".join(x for x in (view.get("prompt"), view.get("body"), " ".join(view.get("hashtags") or []),
                                view.get("style_descriptor")) if x).lower()
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key, spec in TOPICS.items():
        if spec.get("workflow") and (view.get("has_workflow") or view.get("metadata_format") == "comfyui"):
            out["topic"].append((key, spec["label"]))
            continue
        if spec.get("video") and view.get("media_type") != "video":
            continue
        if any(_word_hit(text, t) for t in spec.get("any", [])):
            out["topic"].append((key, spec["label"]))
    if view.get("model_family") and view.get("model_source") in ("explicit", "metadata"):
        fam = view["model_family"]
        out["model"].append((fam, display_family(fam)))
    for slug in view.get("technique_tags") or []:
        out["technique"].append((slug, _slug_label(slug)))
    for key, terms in STYLES.items():
        if any(_word_hit(text, t) for t in terms):
            out["style"].append((key, key.replace("-", " ").title()))
    for key, terms in PALETTES.items():
        if any(_word_hit(text, t) for t in terms):
            out["palette"].append((key, key.replace("-", " ").title()))
    for key, terms in SUBJECTS.items():
        if any(_word_hit(text, t) for t in terms):
            out["subject"].append((key, key.title()))
    if view.get("creator"):
        out["creator"].append((view["creator"], f"@{view['creator']}"))
    out["media"].append((view.get("media_type") or "image", (view.get("media_type") or "image").title()))
    if view.get("prompt"):
        st = kstats.prompt_structure(view["prompt"])
        out["prompt"].append((st, {"tag-list": "Tag-list prompts", "natural": "Natural-language prompts",
                                   "mixed": "Mixed prompts"}[st]))
    cam = view.get("camera") or {}
    for entry in cam.get("shot_size") or []:
        v = entry.get("value") if isinstance(entry, dict) else entry
        if v:
            out["camera"].append((re.sub(r"[^a-z0-9]+", "-", v.lower()), v.title()))
    for mm in cam.get("lens_mm") or []:
        out["camera"].append((f"{mm}mm", f"{mm}mm"))
    return dict(out)


def _view(post: Post, creators: dict[int, str]) -> dict:
    observed = post.observed or {}
    params = post.params or {}
    return {
        "prompt": post.prompt, "body": (observed.get("text") or {}).get("body"),
        "hashtags": (observed.get("text") or {}).get("hashtags"),
        "style_descriptor": ((post.analysis or {}).get("descriptors") or {}).get("style"),
        "has_workflow": bool(post.has_workflow), "metadata_format": params.get("metadata_format"),
        "media_type": post.media_type, "model_family": post.model_family,
        "model_source": post.model_source, "technique_tags": post.technique_tags or [],
        "creator": creators.get(post.creator_id) if post.creator_id else None,
        "camera": provenance.canonical(post.assertions, "camera") or {},
    }


def rebuild(s, max_posts: int = MAX_POSTS) -> dict:
    """Recompute every cluster from stored posts. Returns {clusters, members}."""
    creators = {c.id: c.handle for c in s.execute(select(Creator)).scalars()}
    posts = s.execute(select(Post).order_by(Post.id.desc()).limit(max_posts)).scalars().all()
    members: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    labels: dict[tuple[str, str], str] = {}
    eng = sorted(p.engagement_total for p in posts if p.engagement_total)
    viral_floor = None
    if len(eng) >= 5:
        viral_floor = max(100, eng[int(len(eng) * ENGAGEMENT_PERCENTILE) - 1])
    for p in posts:
        score = float(p.inspiration_score or 0)
        for kind, entries in assign(_view(p, creators)).items():
            for key, label in entries:
                members[(kind, key)].append((p.id, score))
                labels[(kind, key)] = label
        if viral_floor and p.engagement_total and p.engagement_total >= viral_floor:
            members[("engagement", "viral")].append((p.id, score))
            labels[("engagement", "viral")] = f"Viral (≥{viral_floor} engagement)"

    by_id = {p.id: p for p in posts}
    existing = {(c.kind, c.key): c for c in s.execute(select(Cluster)).scalars()}
    s.execute(delete(ClusterPost))
    kept = 0
    total_members = 0
    now = datetime.now(timezone.utc)
    for (kind, key), rows in members.items():
        if len(rows) < MIN_MEMBERS:
            continue
        rows.sort(key=lambda r: (-r[1], -r[0]))
        cluster = existing.pop((kind, key), None)
        if cluster is None:
            cluster = Cluster(kind=kind, key=key, label=labels[(kind, key)])
            s.add(cluster)
            s.flush()
        cluster.label = labels[(kind, key)]
        cluster.post_count = len(rows)
        cluster.data = _aggregates(rows, by_id, creators)
        cluster.updated_at = now
        for pid, score in rows:
            s.add(ClusterPost(cluster_id=cluster.id, post_id=pid, score=score))
        kept += 1
        total_members += len(rows)
    for stale in existing.values():
        s.delete(stale)
    s.flush()
    return {"clusters": kept, "members": total_members, "posts": len(posts)}


def _aggregates(rows: list[tuple[int, float]], by_id: dict[int, Post], creators: dict[int, str]) -> dict:
    posts = [by_id[pid] for pid, _ in rows]
    models = Counter(p.model_family for p in posts if p.model_family)
    techniques = Counter(t for p in posts for t in (p.technique_tags or []))
    creator_counts = Counter(creators.get(p.creator_id) for p in posts if p.creator_id and creators.get(p.creator_id))
    strongest = [p for p in posts if p.prompt and provenance.is_high_confidence(p.assertions, "prompt")
                 or (p.prompt and not p.assertions)][:5]
    return {
        "top_post_ids": [pid for pid, _ in rows[:8]],
        "newest_post_ids": [p.id for p in sorted(posts, key=lambda p: -p.id)[:8]],
        "strongest_prompts": [{"post_id": p.id, "prompt": p.prompt[:160], "score": p.inspiration_score}
                              for p in strongest],
        "models": [{"family": k, "label": display_family(k), "count": v} for k, v in models.most_common(6)],
        "techniques": [{"slug": k, "count": v} for k, v in techniques.most_common(8)],
        "creators": [{"handle": k, "count": v} for k, v in creator_counts.most_common(6)],
        "avg_inspiration": round(sum(sc for _, sc in rows) / len(rows), 1) if rows else 0,
        "videos": sum(1 for p in posts if p.media_type == "video"),
    }


def rebuild_job() -> dict:
    with session_scope() as s:
        return rebuild(s)


def list_clusters(s, kind: str | None = None, min_count: int = MIN_MEMBERS) -> list[dict]:
    stmt = select(Cluster).where(Cluster.post_count >= min_count)
    if kind:
        stmt = stmt.where(Cluster.kind == kind)
    rows = s.execute(stmt.order_by(Cluster.post_count.desc(), Cluster.label)).scalars().all()
    return [cluster_dict(c) for c in rows]


def cluster_dict(c: Cluster) -> dict:
    return {"id": c.id, "kind": c.kind, "key": c.key, "label": c.label,
            "description": c.description, "post_count": c.post_count,
            "data": c.data or {}, "updated_at": c.updated_at.isoformat() if c.updated_at else None}


def cluster_post_ids(s, cluster_id: int, order: str = "score", limit: int = 60, offset: int = 0) -> list[int]:
    stmt = select(ClusterPost.post_id).where(ClusterPost.cluster_id == cluster_id)
    stmt = stmt.order_by(ClusterPost.score.desc().nulls_last(), ClusterPost.post_id.desc()) if order == "score" \
        else stmt.order_by(ClusterPost.post_id.desc())
    return [r[0] for r in s.execute(stmt.offset(offset).limit(limit))]


def clusters_for_post(s, post_id: int) -> list[dict]:
    rows = s.execute(select(Cluster).join(ClusterPost, ClusterPost.cluster_id == Cluster.id)
                     .where(ClusterPost.post_id == post_id).order_by(Cluster.post_count.desc())).scalars().all()
    return [{"id": c.id, "kind": c.kind, "key": c.key, "label": c.label, "post_count": c.post_count} for c in rows]
