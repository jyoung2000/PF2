"""Creator intelligence (I5.1): the reusable layer on top of the X follow
list — per (platform, handle) aggregates computed deterministically from the
posts PF2 actually stored: cadence, engagement, AI-content ratio, prompt
availability, models, techniques, styles, top/recent posts, engagement
trajectory, metadata richness. Stored in creators.stats; refreshed lazily."""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ..models import Creator, MonitoredAccount, Post
from . import provenance

STALE_AFTER = timedelta(hours=1)


def _week(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%G-W%V")


def compute_stats(s, creator: Creator) -> dict:
    posts = s.execute(select(Post).where(Post.creator_id == creator.id)
                      .order_by(Post.id.desc()).limit(500)).scalars().all()
    n = len(posts)
    if not n:
        return {"posts": 0, "computed_at": datetime.now(timezone.utc).isoformat()}
    eng = [p.engagement_total for p in posts if p.engagement_total is not None]
    ai = sum(1 for p in posts if p.ai_status in ("definitely_ai", "probably_ai"))
    prompts = sum(1 for p in posts if p.prompt and provenance.is_high_confidence(p.assertions, "prompt"))
    any_prompt = sum(1 for p in posts if p.prompt)
    models = Counter(p.model_family for p in posts if p.model_family and p.model_source in ("explicit", "metadata"))
    techniques = Counter(t for p in posts for t in (p.technique_tags or []))
    styles = Counter()
    for p in posts:
        d = (p.analysis or {}).get("descriptors") or {}
        if d.get("style"):
            styles[str(d["style"]).lower()[:40]] += 1
    meta = [((p.analysis or {}).get("inspiration") or {}).get("metadata_richness", {}).get("value", 0) for p in posts]
    insp = [p.inspiration_score for p in posts if p.inspiration_score is not None]
    dates = sorted(p.posted_at.replace(tzinfo=timezone.utc) if p.posted_at and p.posted_at.tzinfo is None
                   else p.posted_at for p in posts if p.posted_at)
    cadence = None
    if len(dates) >= 2:
        span_days = max(1.0, (dates[-1] - dates[0]).total_seconds() / 86400)
        cadence = round(len(dates) / (span_days / 7), 2)          # posts per week
    weekly: dict[str, list[int]] = {}
    for p in posts:
        w = _week(p.posted_at)
        if w and p.engagement_total is not None:
            weekly.setdefault(w, []).append(p.engagement_total)
    trajectory = [{"week": w, "posts": len(v), "avg_engagement": round(sum(v) / len(v))}
                  for w, v in sorted(weekly.items())[-8:]]
    trend = None
    if len(trajectory) >= 2:
        first, last = trajectory[0]["avg_engagement"], trajectory[-1]["avg_engagement"]
        trend = "rising" if last > first * 1.25 else ("falling" if last < first * 0.75 else "flat")
    top = sorted((p for p in posts if p.inspiration_score is not None),
                 key=lambda p: -p.inspiration_score)[:6]
    return {
        "posts": n,
        "images": sum(1 for p in posts if p.media_type == "image"),
        "videos": sum(1 for p in posts if p.media_type == "video"),
        "followers": creator.followers,
        "avg_engagement": round(sum(eng) / len(eng)) if eng else None,
        "median_engagement": round(statistics.median(eng)) if eng else None,
        "posts_per_week": cadence,
        "ai_ratio": round(ai / n, 3),
        "prompt_availability": round(prompts / n, 3),
        "any_prompt_ratio": round(any_prompt / n, 3),
        "models": [{"family": k, "count": v} for k, v in models.most_common(8)],
        "techniques": [{"slug": k, "count": v} for k, v in techniques.most_common(12)],
        "styles": [{"style": k, "count": v} for k, v in styles.most_common(6)],
        "top_post_ids": [p.id for p in top],
        "recent_post_ids": [p.id for p in posts[:6]],
        "engagement_trajectory": trajectory,
        "trend": trend,
        "metadata_richness": round(sum(meta) / len(meta), 3) if meta else 0.0,
        "avg_inspiration": round(sum(insp) / len(insp), 1) if insp else None,
        "first_seen": creator.first_seen.isoformat() if creator.first_seen else None,
        "last_seen": creator.last_seen.isoformat() if creator.last_seen else None,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def refresh(s, creator: Creator) -> dict:
    creator.stats = compute_stats(s, creator)
    creator.updated_at = datetime.now(timezone.utc)
    s.flush()
    return creator.stats


def _stale(creator: Creator) -> bool:
    computed = (creator.stats or {}).get("computed_at")
    if not computed:
        return True
    try:
        at = datetime.fromisoformat(computed)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - at > STALE_AFTER


def stats_for(s, creator: Creator, force: bool = False) -> dict:
    if force or _stale(creator):
        return refresh(s, creator)
    return creator.stats or {}


def find(s, platform: str, handle: str) -> Creator | None:
    return s.execute(select(Creator).where(
        Creator.platform == platform,
        Creator.handle == str(handle).lstrip("@").strip().lower())).scalars().first()


def creator_dict(s, creator: Creator, force: bool = False) -> dict:
    st = stats_for(s, creator, force)
    monitored = s.execute(select(MonitoredAccount.id).where(
        MonitoredAccount.platform == creator.platform,
        MonitoredAccount.handle == creator.handle)).scalar()
    return {
        "id": creator.id, "platform": creator.platform, "handle": creator.handle,
        "display_name": creator.display_name, "profile_url": creator.profile_url,
        "avatar_url": creator.avatar_url, "verified": creator.verified,
        "followers": creator.followers, "following": creator.following, "bio": creator.bio,
        "monitored_account_id": monitored, "stats": st,
    }


def list_creators(s, platform: str | None = None, sort: str = "posts", limit: int = 60,
                  q: str | None = None) -> list[dict]:
    stmt = select(Creator)
    if platform:
        stmt = stmt.where(Creator.platform == platform)
    if q:
        stmt = stmt.where(func.lower(Creator.handle).like(f"%{q.lower()}%"))
    rows = s.execute(stmt).scalars().all()
    out = [creator_dict(s, c) for c in rows]
    keyfn = {
        "posts": lambda d: -(d["stats"].get("posts") or 0),
        "followers": lambda d: -(d["followers"] or 0),
        "engagement": lambda d: -(d["stats"].get("avg_engagement") or 0),
        "ai_ratio": lambda d: -(d["stats"].get("ai_ratio") or 0),
        "prompts": lambda d: -(d["stats"].get("prompt_availability") or 0),
        "inspiration": lambda d: -(d["stats"].get("avg_inspiration") or 0),
        "recent": lambda d: (d["stats"].get("last_seen") or ""),
    }.get(sort, lambda d: -(d["stats"].get("posts") or 0))
    out.sort(key=keyfn)
    return out[:limit]
