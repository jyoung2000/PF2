"""Seed the demo library the browsable preview is captured from.

Two phases, because the Film Studio is seeded through the real API:

    backend/.venv/bin/python design/preview_seed.py library <data_dir>
    backend/.venv/bin/python design/preview_seed.py film http://127.0.0.1:5643

Everything here is sample data — abstract placeholder artwork, invented
prompts and creators. No credential is ever written, so the Settings page
captures in its unconfigured state, exactly as a fresh container shows it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from PIL import Image, ImageDraw  # noqa: E402

NOW = datetime.now(timezone.utc)

# --------------------------------------------------------------- artwork ---
BG = [(42, 31, 20), (16, 27, 58), (28, 19, 41), (14, 42, 40), (43, 20, 32),
      (26, 36, 18), (58, 42, 15), (15, 32, 54), (37, 22, 27), (20, 33, 61)]
INK = [(255, 106, 61), (255, 179, 71), (255, 209, 102), (6, 214, 160),
       (76, 201, 240), (247, 37, 133), (114, 9, 183), (67, 97, 238),
       (181, 23, 158), (249, 199, 79), (144, 190, 109), (249, 65, 68),
       (67, 170, 139), (87, 117, 144), (233, 196, 106), (255, 159, 28)]


def _rng(seed: int):
    s = seed & 0xFFFFFFFF or 1

    def nxt() -> float:
        nonlocal s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        s &= 0xFFFFFFFF
        return (s % 10000) / 10000

    return nxt


def artwork(seed: int, w: int, h: int) -> Image.Image:
    """The same deterministic abstract composition the design artboards use."""
    r = _rng(seed * 7919 + 17)
    im = Image.new("RGB", (w, h), BG[int(r() * len(BG))])
    for _ in range(4 + int(r() * 4)):
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        color = INK[int(r() * len(INK))]
        kind, x, y = r(), r() * w, r() * h
        alpha = int(255 * (0.7 + r() * 0.3))
        if kind < 0.4:
            rad = 0.12 * min(w, h) + r() * 0.35 * min(w, h)
            d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(*color, alpha))
        elif kind < 0.75:
            d.rectangle([x, y, x + 0.15 * w + r() * 0.45 * w,
                         y + 0.1 * h + r() * 0.5 * h], fill=(*color, alpha))
        else:
            rx, ry = 0.1 * w + r() * 0.4 * w, 0.06 * h + r() * 0.25 * h
            d.ellipse([x - rx, y - ry, x + rx, y + ry], fill=(*color, alpha))
        im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    return im


# ------------------------------------------------------------- the posts ---
# (prompt, model_name, family, version, platform, w, h, video, techniques, tags)
POSTS = [
    ("cinematic portrait of a woman in a rain-soaked neon alley, 85mm, shallow depth of field, volumetric light, wet asphalt reflections, cyan and magenta signage, film grain",
     "Flux.1 Dev", "flux", "flux.1-dev", "civitai", 832, 1216, False, ["rim-light", "shallow-dof"], ["portrait", "neon", "cyberpunk"]),
    ("isometric cyberpunk city block at midnight, tilt-shift, clean vector shading, warm windows against cold streets",
     "SDXL 1.0", "sdxl", "1.0", "lexica", 1024, 768, False, ["tilt-shift"], ["isometric", "city"]),
    ("drone shot over a fog-covered pine forest at sunrise, slow dolly forward, volumetric god rays",
     "Wan 2.2", "wan", "2.2", "x", 1280, 720, True, ["dolly", "volumetric-light"], ["landscape"]),
    ("editorial fashion portrait, brutalist concrete backdrop, hard noon light, sharp shadows, 50mm",
     "Midjourney v7", "midjourney", "v7", "midjourney", 896, 1344, False, ["high-key"], ["fashion", "portrait"]),
    ("studio product shot of a matte black espresso machine, softbox reflections, seamless grey sweep",
     "TensorArt XL", "sdxl", "turbo", "tensorart", 1024, 1024, False, ["rim-light"], ["product"]),
    ("anime keyframe, girl on a rooftop at blue hour, wind in hair, cel shading, film grain",
     "Illustrious XL", "illustrious", "xl-1.0", "seaart", 768, 1152, False, ["blue-hour"], ["anime"]),
    ("watercolor fox in a birch forest, loose brushwork, visible paper texture, muted palette",
     "Illustrious XL", "illustrious", "xl-2.0", "pixai", 1024, 1280, False, [], ["illustration", "animals"]),
    ("macro shot of ink dispersing in water, 120fps, backlit, black background",
     "Kling 2.1", "kling", "2.1", "civitai", 1216, 832, True, ["macro", "timelapse"], ["abstract"]),
    ("art deco travel poster of a red monorail crossing a desert, flat colors, geometric sun",
     "SDXL 1.0", "sdxl", "1.0", "lexica", 1024, 1024, False, [], ["poster", "retro"]),
    ("street photography, Tokyo crossing at night, rain reflections, 35mm, available light",
     "Flux.1 Dev", "flux", "flux.1-dev", "x", 1080, 1350, False, ["35mm"], ["street", "night"]),
    ("ceramic teapot shaped like a sleeping cat, soft morning window light, shallow depth of field",
     "Midjourney v6.1", "midjourney", "v6.1", "midjourney", 1024, 768, False, ["shallow-dof"], ["product", "cozy"]),
    ("knight in silver armor standing in a wheat field, golden hour, painterly brushwork",
     "Flux.1 Pro", "flux", "flux.1-pro", "tensorart", 832, 1216, False, ["golden-hour"], ["fantasy"]),
    ("timelapse of clouds rolling over mountain ridges, hyperlapse, high contrast",
     "Hunyuan Video 1.5", "hunyuan", "video 1.5", "seaart", 1280, 720, True, ["timelapse", "hyperlapse"], ["landscape"]),
    ("cozy reading nook illustration, warm lamp glow, rain on the window, soft textures",
     "Illustrious XL", "illustrious", "xl-1.0", "pixai", 1024, 1024, False, [], ["illustration", "cozy"]),
    ("noir detective in a smoky office, venetian blind shadows, high contrast black and white",
     "Flux.1 Dev", "flux", "flux.1-dev", "civitai", 896, 1344, False, ["low-key"], ["noir", "portrait"]),
    ("low-poly island floating in a pastel sky, soft gradients, tiny waterfall",
     "SDXL Lightning", "sdxl", "lightning", "lexica", 1024, 768, False, [], ["3d", "stylised"]),
    ("slow orbit around a glass sculpture, caustics dancing on the floor, studio void",
     "Veo 3", "veo", "3", "x", 1280, 720, True, ["orbit"], ["abstract"]),
    ("botanical illustration of a blue poppy, vintage plate style, aged paper",
     "Midjourney v7", "midjourney", "v7", "midjourney", 1024, 1280, False, [], ["illustration", "botanical"]),
    ("wide establishing shot of a lighthouse in a storm, spray across the lens, overcast",
     "Flux.1 Dev", "flux", "flux.1-dev", "civitai", 1344, 896, False, ["wide-angle"], ["landscape", "storm"]),
    ("character sheet turnaround of a desert scavenger, front side back, consistent character",
     "Flux.1 Dev", "flux", "flux.1-dev", "civitai", 1344, 768, False, ["character-consistency"], ["character"]),
    ("handheld push-in through a neon arcade, motion blur, VHS artefacts",
     "Wan 2.1", "wan", "2.1", "x", 1280, 720, True, ["handheld", "push-in", "glitch"], ["neon", "retro"]),
    ("still life of citrus on linen, north window light, medium format look",
     "Stable Diffusion 1.5", "sd15", "1.5", "lexica", 1024, 1024, False, [], ["still-life"]),
    ("brutalist library interior, concrete coffers, one shaft of sunlight, wide angle",
     "SDXL 1.0", "sdxl", "1.0", "tensorart", 1216, 832, False, ["wide-angle"], ["architecture"]),
    ("close-up of frost forming on a window pane, macro, cold blue tones",
     "Kling 1.6", "kling", "1.6", "seaart", 1280, 720, True, ["macro"], ["winter", "abstract"]),
]

COLLECTIONS = [
    ("Moody portraits", "Low-key, single-subject, always Flux — the collection the style profile is learned from.", "flux", [0, 14, 9, 11]),
    ("Isometric cities", "Mixed models on purpose: the geometry survives the swap.", "sdxl", [1, 8, 15, 22]),
    ("Neon noir video", "Motion tests for the film work.", "wan", [2, 20, 16]),
    ("Product hero shots", "Clean studio setups worth re-running.", "sdxl", [4, 10, 21]),
    ("Anime keyframes", "Reference frames for the animation project.", "illustrious", [5, 6, 13]),
]

SAVED = [
    ("Weathered portrait of an elderly fisherman at golden hour, salt-worn skin and deep-set eyes, wind-tousled grey beard, oilskin jacket, harbour bokeh behind him, 85mm lens, shallow depth of field, warm rim light, subtle film grain, cinematic color grading",
     "blurry, low quality, watermark, extra fingers, plastic skin", "flux", "enhanced", True),
    ("Isometric cutaway of a tiny ramen shop at midnight, warm neon spilling onto wet pavement, ultra detailed, tilt-shift",
     "text, signature, distorted perspective", "sdxl", "template", False),
    ("Slow orbit around a brass diving helmet on a workbench, volumetric dust, single practical light",
     None, "wan", "manual", True),
    ("Anime keyframe, courier on a rooftop at blue hour, wind in hair, cel shading, film grain",
     "3d render, photorealistic", "illustrious", "enhanced", False),
]


def seed_library(data_dir: Path) -> None:
    from promptforge import config as cfg_mod, db as db_mod, fts
    from promptforge.intel import clusters, sources
    from promptforge.knowledge import template_gen
    from promptforge.models import (Collection, CollectionPost, Creator, MonitoredAccount,
                                    PipelineJob, Post, PostTag, SavedPrompt, ScraperState, Tag)
    from promptforge.pipeline.ingest import IngestStats

    cfg_mod.set_config(cfg_mod.Config(data_dir=data_dir))
    db_mod.init_db()

    def store(i: int, platform: str, w: int, h: int, video: bool, seconds: float) -> tuple[str, str]:
        """Write the media exactly as the pipeline does: a compressed file plus
        a WebP thumbnail. Video posts get a real (tiny) H.264 clip so the
        drawer and the film pages have something a browser can play."""
        media = data_dir / "media" / platform
        (media / "thumbs").mkdir(parents=True, exist_ok=True)
        im = artwork(i + 1, w, h)
        rel_t = f"media/{platform}/thumbs/preview{i}.webp"
        thumb = im.copy()
        thumb.thumbnail((512, 512))
        thumb.save(data_dir / rel_t, "WEBP", quality=80)
        if not video:
            rel = f"media/{platform}/preview{i}.webp"
            im.save(data_dir / rel, "WEBP", quality=82)
            return rel, rel_t
        rel = f"media/{platform}/preview{i}.mp4"
        still = data_dir / "media" / platform / f"_still{i}.png"
        im.save(still)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(still),
                        "-t", str(seconds), "-r", "24",
                        "-vf", f"scale={w}:{h},zoompan=z='min(zoom+0.0008,1.15)':d={int(seconds * 24)}:s={w}x{h}",
                        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "27",
                        str(data_dir / rel)], check=True)
        still.unlink()
        return rel, rel_t

    with db_mod.session_scope() as s:
        creators = {}
        for handle, platform, followers, verified in (
                ("auroraforge", "x", 12400, True), ("motionmuse", "x", 3300, False),
                ("lumen_ai", "civitai", 8800, False), ("paperfox", "pixai", 1500, False)):
            c = Creator(platform=platform, handle=handle, display_name=handle.replace("_", " ").title(),
                        followers=followers, verified=verified,
                        first_seen=NOW - timedelta(days=90), last_seen=NOW - timedelta(hours=3))
            s.add(c)
            s.flush()
            creators[handle] = c.id

        tags: dict[str, Tag] = {}
        posts: list[Post] = []
        for i, (prompt, model, family, version, platform, w, h, video, techs, tag_names) in enumerate(POSTS):
            seconds = float(5 + i % 8)
            rel, rel_t = store(i, platform, w, h, video, seconds)
            handle = {"x": "auroraforge" if i % 2 == 0 else "motionmuse",
                      "civitai": "lumen_ai", "pixai": "paperfox"}.get(platform)
            engagement = [40, 120, 350, 900, 2400, 8000][i % 6]
            inspiration = round(52 + (i * 37 % 43), 1)
            workflow = i % 5 == 0
            params = {"seed": 918273645 + i * 1117, "steps": 24 + i % 12,
                      "cfg_scale": round(3.0 + (i % 5) * 0.5, 1),
                      "sampler": ["euler", "dpmpp_2m", "heun"][i % 3],
                      "scheduler": ["simple", "karras"][i % 2],
                      "size": f"{w}x{h}", "_original_bytes": 3_100_000 + i * 40_000,
                      "_stored_bytes": 380_000 + i * 9_000}
            if workflow:
                params |= {"workflow": {"3": {"class_type": "KSampler"}},
                           "metadata_format": "comfyui",
                           "loras": [{"name": "filmgrain_v2", "weight": 0.6}],
                           "_raw_metadata": {"comfyui_prompt": "{…}"}}
            if video:
                params |= {"video": {"model": model, "frames": 121, "fps": 24,
                                     "duration_s": seconds, "mode": "text_to_video"}}
            post = Post(
                platform=platform, platform_post_id=f"preview-{i}", prompt=prompt,
                negative_prompt="blurry, low quality, watermark, text, extra fingers, deformed hands" if i % 3 == 0 else None,
                model_name=model, model_family=family, model_version=version,
                params=params, media_type="video" if video else "image",
                media_path=rel, thumb_path=rel_t, media_width=w, media_height=h,
                duration_s=seconds if video else None,
                author=f"@{handle}" if handle else None, creator_id=creators.get(handle),
                source_url=f"https://{platform}.com/preview/{i}",
                posted_at=NOW - timedelta(hours=3 + i * 7), scraped_at=NOW - timedelta(hours=2 + i * 7),
                favorite=i in (0, 14, 5), technique_tags=techs,
                engagement_total=engagement, inspiration_score=inspiration,
                candidate_score=round(inspiration * 0.9, 1),
                ai_status="definitely_ai" if platform != "x" else ["definitely_ai", "probably_ai", "uncertain"][i % 3],
                ai_confidence=0.96 if platform != "x" else 0.7,
                has_workflow=workflow, prompt_source="observed" if platform != "x" else "extracted",
                model_source="explicit" if i % 3 else "metadata",
                pipeline_state="analyzed" if i % 3 == 0 else ("enriched" if platform == "x" else "stored"),
                phash=f"{(0xA53F1C0072B4E900 + i * 977):016x}"[:16],
                content_hash=f"{i:064x}",
                observed={"engagement": {"likes": engagement, "comments": engagement // 20},
                          "text": {"body": prompt, "hashtags": ["aiart", family]},
                          "author": {"handle": handle} if handle else {}},
                assertions={
                    "prompt": {"value": prompt, "source": "observed" if platform != "x" else "extracted",
                               "confidence": 0.95 if platform != "x" else 0.8,
                               "evidence": "structured field" if platform != "x" else "“Prompt:” label in the post text"},
                    "model": {"value": model, "source": "metadata" if i % 3 == 0 else "extracted",
                              "confidence": 0.9, "evidence": f"named {model} in the generation metadata"},
                    "camera": {"value": {"lens_mm": [85] if "85mm" in prompt else ([35] if "35mm" in prompt else []),
                                         "shot_size": [{"value": "close-up"}] if "close-up" in prompt or "macro" in prompt else []},
                               "source": "extracted", "confidence": 0.8, "evidence": "camera vocabulary in the prompt"},
                    "lighting": {"value": ["golden hour"] if "golden hour" in prompt else (["low-key"] if "smoky" in prompt else ["studio"]),
                                 "source": "extracted", "confidence": 0.8, "evidence": prompt[:48]},
                },
                analysis={
                    "inspiration": {k: {"value": round(0.45 + ((i * 13 + n * 29) % 55) / 100, 2), "weight": 1.0,
                                        "contribution": round(4 + ((i * 7 + n * 11) % 16), 1)}
                                    for n, k in enumerate(("visual_quality", "prompt_quality", "technical_detail",
                                                           "novelty", "engagement", "model_relevance", "metadata_richness"))},
                    "ai": {"status": "definitely_ai", "confidence": 0.96,
                           "reason": "embedded generation metadata", "source": "heuristic"},
                    "descriptors": {"subject": prompt.split(",")[0][:48],
                                    "style": "cinematic" if video else "editorial"},
                },
                enrichment={"comments": [
                    {"id": "c1", "author": "@fan", "text": "what seed and cfg did you land on?", "likes": 12, "technical": True},
                    {"id": "c2", "author": "@passerby", "text": "the light on this is unreal", "likes": 4, "technical": False}],
                    "comment_count": 2} if platform == "x" else {},
            )
            s.add(post)
            s.flush()
            for name in tag_names:
                tag = tags.get(name)
                if tag is None:
                    tag = Tag(name=name)
                    s.add(tag)
                    s.flush()
                    tags[name] = tag
                s.add(PostTag(post_id=post.id, tag_id=tag.id))
            fts.index_post(s, post.id, post.prompt, post.model_name, tag_names)
            posts.append(post)

        collection_ids = []
        for name, description, family, members in COLLECTIONS:
            col = Collection(name=name, description=description, model_family=family,
                             allow_mixed_models=name == "Isometric cities",
                             cover_post_id=posts[members[0]].id,
                             created_at=NOW - timedelta(days=len(collection_ids) + 2))
            s.add(col)
            s.flush()
            for m in members:
                s.add(CollectionPost(collection_id=col.id, post_id=posts[m].id))
            collection_ids.append(col.id)

        for text, negative, family, origin, starred in SAVED:
            s.add(SavedPrompt(text=text, negative=negative, model_family=family,
                              origin=origin, starred=starred,
                              collection_id=collection_ids[0] if origin == "enhanced" else None))

        for name, found, new, dupes, minutes in (("civitai", 120, 37, 22, 4), ("lexica", 60, 9, 7, 11),
                                                 ("tensorart", 48, 21, 8, 38), ("seaart", 40, 12, 3, 52),
                                                 ("pixai", 40, 4, 3, 2880), ("x", 84, 26, 11, 1)):
            state = s.get(ScraperState, name) or ScraperState(name=name, state={})
            s.add(state)
            s.flush()
            state.last_run_at = NOW - timedelta(minutes=minutes)
            state.last_status = "ok"
            state.last_found = found
            state.last_new = new
            sources.record_run(s, name, IngestStats(found=found, new=new, duplicates=dupes,
                                                    filtered=found - new - dupes), 12.0)

        s.add(PipelineJob(post_id=posts[0].id, stage="analysis", state="queued", priority=80))
        s.add(PipelineJob(post_id=posts[1].id, stage="enrich", state="retryable", attempts=1,
                          error="TimeoutError: TweetDetail capture took longer than 30s"))
        s.add(PipelineJob(post_id=posts[2].id, stage="analysis", state="complete"))
        s.add(PipelineJob(post_id=posts[3].id, stage="knowledge", state="queued", priority=40))
        s.add(MonitoredAccount(handle="auroraforge", platform="x", added_by="grok", status="ok",
                               last_checked=NOW - timedelta(minutes=12),
                               evidence={"source": "grok", "verified": True,
                                         "detected_models": ["Kling", "Wan"], "confidence": 0.86}))
        print("clusters:", clusters.rebuild(s))

    for cid in collection_ids:
        template_gen.sync_template_for_collection(cid)
    print(f"seeded {len(POSTS)} posts, {len(COLLECTIONS)} collections")


# ------------------------------------------------------------ film studio ---
SCRIPT = """FADE IN:

INT. WAREHOUSE - NIGHT

Rain hammers the skylights. JACK (34) crouches by a crate, a brass lantern beside him. SARAH watches the door.

JACK
We don't have long.

SARAH
Then stop talking and open it.

Jack pries the lid. Light spills out.

EXT. DOCKS - DAWN

Fog. A container ship groans against the pier. Jack walks alone, the lantern dark in his hand.

JACK
(quietly)
It was never about the money.
"""


def seed_film(base_url: str) -> None:
    import httpx

    c = httpx.Client(base_url=base_url, timeout=180)
    tmp = Path(tempfile.mkdtemp())

    def png(name: str, seed: int, text: str) -> Path:
        im = artwork(seed, 768, 960)
        d = ImageDraw.Draw(im)
        d.text((32, 32), text, fill=(255, 255, 255))
        p = tmp / name
        im.save(p)
        return p

    def clip(name: str, secs: float, seed: int) -> Path:
        """A tiny clip built from the same placeholder artwork, so imported
        takes look like footage instead of a test pattern."""
        still = tmp / f"{name}.png"
        artwork(seed, 640, 360).save(still)
        p = tmp / name
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(still),
                        "-t", str(secs), "-r", "24",
                        "-vf", f"zoompan=z='min(zoom+0.0012,1.2)':d={int(secs * 24)}:s=640x360",
                        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34",
                        str(p)], check=True)
        return p

    jack = c.post("/api/film/assets", json={
        "type": "character", "name": "Jack", "description": "Courier who owes everyone.",
        "data": {"age": "34", "role": "courier", "personality": "wry, exhausted, loyal",
                 "face_shape": "sharp jaw", "eyes": "deep-set", "eye_color": "green",
                 "hair": "black, short, wet", "facial_hair": "two-day stubble", "skin": "olive, tired",
                 "distinctive_features": "thin scar through left eyebrow", "height": "1.83m",
                 "body_type": "lean", "posture": "hunched"},
        "continuity_rules": ["scar always through the LEFT eyebrow"],
        "negative_constraints": ["no beard", "no glasses"], "tags": ["lead"]}).json()
    sarah = c.post("/api/film/assets", json={
        "type": "character", "name": "Sarah",
        "data": {"age": "31", "role": "fixer", "hair": "auburn, tied back", "eye_color": "grey",
                 "distinctive_features": "silver ring on right thumb"}, "tags": ["lead"]}).json()
    warehouse = c.post("/api/film/assets", json={
        "type": "location", "name": "Warehouse", "description": "Brick industrial hall on the wet side of town.",
        "data": {"architecture": "brick industrial hall, steel trusses",
                 "layout": "open floor, mezzanine on the left, loading bay at the back",
                 "materials": "wet concrete, rusted steel, brick", "furniture": "stacked crates, one work bench",
                 "windows": "high skylights, rain-streaked", "lighting": "sodium practicals, one flickering tube",
                 "time_of_day": "night", "weather": "rain", "atmosphere": "haze",
                 "color_palette": "amber and teal", "zones": ["loading bay", "mezzanine", "crate stack"],
                 "entrances": ["roller door (back)", "side door (left)"], "landmarks": ["the crate"],
                 "camera_areas": ["mezzanine overlook", "floor level by the crate"]},
        "continuity_rules": ["mezzanine stairs stay on the left"]}).json()
    docks = c.post("/api/film/assets", json={
        "type": "location", "name": "Docks",
        "data": {"architecture": "container terminal", "layout": "long pier, cranes to the right",
                 "time_of_day": "dawn", "weather": "fog", "lighting": "flat grey",
                 "color_palette": "desaturated blue"}}).json()
    lantern = c.post("/api/film/assets", json={
        "type": "prop", "name": "Brass lantern",
        "data": {"description": "old brass storm lantern", "material": "brass, glass", "condition": "dented"}}).json()
    style = c.post("/api/film/assets", json={
        "type": "style", "name": "Neon noir",
        "data": {"medium": "live action", "rendering_style": "photoreal 35mm film",
                 "palette": "teal and magenta over amber practicals", "film_grain": "coarse",
                 "contrast": "high", "lighting_style": "low key, practical-motivated",
                 "negative_style": "no cartoon, no anime"}}).json()
    c.post("/api/film/assets", json={
        "type": "outfit", "name": "Rain coat", "owner_asset_id": jack["id"],
        "data": {"is_default": True, "garments": ["olive rain coat", "grey hoodie", "black jeans"],
                 "colors": "olive, grey"}})

    for asset, seed, kinds in ((jack, 31, ["portrait", "three_quarter"]), (sarah, 32, ["portrait"]),
                               (warehouse, 33, ["interior", "wide"]), (docks, 34, ["exterior"]),
                               (lantern, 35, ["main"]), (style, 36, ["mood"])):
        for k in kinds:
            p = png(f"{asset['name']}-{k}.png", seed + len(k), f"{asset['name']} {k}")
            with open(p, "rb") as fh:
                c.post(f"/api/film/assets/{asset['id']}/refs", files={"file": (p.name, fh, "image/png")},
                       data={"kind": k, "label": f"{asset['name']} {k}"})
    c.patch(f"/api/film/assets/{jack['id']}", json={"approved": True, "favorite": True})
    c.patch(f"/api/film/assets/{warehouse['id']}", json={"approved": True})
    c.post(f"/api/film/assets/{jack['id']}/versions",
           json={"changes": {"hair": "black, short, wet, pushed back"}, "new_version": True, "label": "after the rain"})

    project = c.post("/api/film/projects", json={
        "title": "Rainy City", "logline": "A courier loses a package in a city that never dries.",
        "settings": {"visual_style": "gritty 35mm neon noir", "tone": "tense, intimate",
                     "target_runtime_s": 45, "default_scene_gap_s": 0.5, "pacing_profile": "normal",
                     "budget": {"mode": "warn", "threshold_usd": 5.0}}}).json()
    pid = project["id"]
    c.post(f"/api/film/projects/{pid}/story/import", json={"text": SCRIPT})
    proposal = c.post(f"/api/film/projects/{pid}/director/story", json={"use_llm": False}).json()
    c.post(f"/api/film/proposals/{proposal['id']}/accept", json={"mode": "replace"})
    plan = c.post(f"/api/film/projects/{pid}/director/plan", json={"use_llm": False}).json()
    c.post(f"/api/film/proposals/{plan['id']}/accept")
    c.post(f"/api/film/projects/{pid}/gates/plan", json={"status": "approved"})

    proj = c.get(f"/api/film/projects/{pid}").json()
    shots = [sh for sc in proj["scenes"] for sh in sc["shots"]]
    for sc in proj["scenes"]:
        assets = ([{"asset_id": a["asset_id"], "version_id": a["version_id"]} for a in sc["shots"][0]["assets"]]
                  if sc["shots"] else [])
        c.patch(f"/api/film/scenes/{sc['id']}", json={
            "defaults": {"assets": assets + [{"asset_id": style["id"]}]
                         + ([{"asset_id": lantern["id"]}] if sc["number"] == 1 else []),
                         "lighting_preset": "neon_night" if sc["number"] == 1 else "blue_hour"}})
    c.patch(f"/api/film/shots/{shots[1]['id']}", json={"chain_from_previous": True, "locks": ["camera", "lighting"]})
    c.patch(f"/api/film/shots/{shots[2]['id']}", json={"overrides": {
        **shots[2]["overrides"],
        "camera": {"lens_mm": 85, "movement": "push_in", "movement_speed": "slow", "depth_of_field": "shallow"},
        "color": {"contrast": "high", "film_grain": "coarse"}}})
    c.post(f"/api/film/shots/{shots[1]['id']}/director",
           json={"instruction": "make it tense and intimate, keep the warehouse layout", "use_llm": False})

    for i, sh in enumerate(shots[:5]):
        cp = clip(f"take{i}.mp4", max(1.0, float(sh["duration_s"])), 51 + i)
        with open(cp, "rb") as fh:
            c.post(f"/api/film/shots/{sh['id']}/takes/import", files={"file": (cp.name, fh, "video/mp4")},
                   data={"kind": "footage"})
    frame = png("frame.png", 41, "start frame")
    with open(frame, "rb") as fh:
        c.post(f"/api/film/shots/{shots[5]['id']}/frames/start_frame/upload",
               files={"file": ("frame.png", fh, "image/png")})
    c.post(f"/api/film/shots/{shots[5]['id']}/still", json={"source": "start_frame"})
    c.post(f"/api/film/shots/{shots[6]['id']}/card",
           json={"text": "RAINY CITY", "subtitle": "a PromptForge film", "style": "title"})
    c.post(f"/api/film/shots/{shots[1]['id']}/frames/start_frame", json={"kind": "previous_shot"})

    wav = tmp / "tone.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=220:sample_rate=48000:duration=6", "-ac", "2", str(wav)], check=True)
    with open(wav, "rb") as fh:
        c.post(f"/api/film/projects/{pid}/audio", files={"file": ("bed.wav", fh, "audio/wav")},
               data={"kind": "music", "label": "synth bed", "gain_db": "-8"})
    c.post(f"/api/film/projects/{pid}/subtitles/from-script")
    c.post(f"/api/film/projects/{pid}/continuity")
    c.post(f"/api/film/projects/{pid}/gates/assets", json={"status": "approved"})
    c.post(f"/api/film/projects/{pid}/gates/storyboard", json={"status": "approved"})

    # Forge demo content: an experiment with model-specific variants, a
    # creative plan and a workflow from a template (all sample data)
    exp = c.post("/api/forge/experiments", json={
        "name": "Violinist noir",
        "brief": "A noir portrait of a violinist under a streetlight, no rain, square"}).json()
    for fam in ("sdxl", "flux", "seedream"):
        c.post(f"/api/forge/experiments/{exp['id']}/variants", json={"compile_family": fam})
    c.post("/api/forge/plans", json={
        "brief": "Launch campaign for my new music player app, warm retro aesthetic"})
    c.post("/api/forge/workflows/from-template/image_to_video")
    print(json.dumps({"project": pid, "shots": len(shots),
                      "qa": c.get(f"/api/film/projects/{pid}/qa").json()["verdict"]}))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    if sys.argv[1] == "library":
        seed_library(Path(sys.argv[2]).resolve())
    elif sys.argv[1] == "film":
        seed_film(sys.argv[2])
    else:
        raise SystemExit(__doc__)
