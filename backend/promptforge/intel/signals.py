"""Cross-source signals (Inspiration 2.0, I14; spec §40–§46, §71–§72).

`trends.py` answers "what is happening on PF2's shelf". This module answers
the sharper questions Inspiration 2.0 asks:

  velocity          how fast a signal is growing right now, and whether the
                    growth itself is speeding up or already fading
  platform spread   a look that shows up on FOUR platforms is a movement; the
                    same count on one platform is that platform's fashion
  prompt patterns   which PHRASES keep travelling together, mined only from
                    prompts the creators actually published (§21/§93)
  engagement growth how fast a stored post is still gaining, from the
                    engagement_snapshots PF2 already appends per re-scrape
  discovery modes   trending / best-prompts / latest / hidden-gems /
                    workflows / cross-platform, each result carrying the
                    reasons it is there (§46)

Everything here is arithmetic over stored rows. No LLM is involved, none is
required, and no result is invented: a signal PF2 cannot see simply is not
reported.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..knowledge import stats as kstats
from ..models import Creator, EngagementSnapshot, Post
from . import prompt_parser, provenance, scoring, trends

MODES = ("trending", "best_prompts", "latest", "hidden_gems", "workflows",
         "cross_platform")
MIN_PATTERN_SUPPORT = 3          # a "pattern" seen twice is a coincidence


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------- velocity ----
def velocity(series: list[int], window: int = 2) -> dict:
    """Growth of the last `window` buckets against the ones before them, plus
    whether that growth is accelerating.

    Deliberately smoothed (+1 on both sides): a jump from 0 to 3 is real but
    it is not "infinite growth", and reporting it that way would drown the
    signals that matter."""
    if len(series) < window * 2:
        return {"recent": sum(series[-window:]) if series else 0, "prior": 0,
                "velocity": 0.0, "acceleration": 0.0, "direction": "unknown",
                "detail": "not enough history yet"}
    recent = sum(series[-window:])
    prior = sum(series[-window * 2:-window])
    older = sum(series[-window * 3:-window * 2]) if len(series) >= window * 3 else None
    vel = round((recent + 1) / (prior + 1), 2)
    prev_vel = round((prior + 1) / (older + 1), 2) if older is not None else None
    accel = round(vel - prev_vel, 2) if prev_vel is not None else 0.0
    direction = ("rising" if vel >= 1.5 else "falling" if vel <= 0.67 else "steady")
    if direction == "rising" and accel < -0.3:
        direction = "cooling"          # still up on the window, but slowing
    return {"recent": recent, "prior": prior, "velocity": vel,
            "acceleration": accel, "direction": direction,
            "detail": f"{recent} in the last {window} week(s) vs {prior} before"}


def _post_rows(s: Session, weeks: int, now: datetime) -> list[Post]:
    since = now - timedelta(weeks=weeks)
    when = func.coalesce(Post.posted_at, Post.scraped_at)
    return list(s.execute(select(Post).where(when >= since)
                          .order_by(Post.id.desc()).limit(20_000)).scalars())


def cross_platform_signals(s: Session, weeks: int = 8, now: datetime | None = None,
                           limit: int = 25) -> dict:
    """Signals ranked by how WIDELY they travel, not just how often they
    appear (§72). A model or look on several platforms is the real trend."""
    now = now or datetime.now(timezone.utc)
    posts = _post_rows(s, weeks, now)
    labels = trends._weeks_back(weeks, now)
    creators = {c.id: c.handle for c in s.execute(select(Creator)).scalars()}

    # kind → key → {platform → count} and week → count
    spread: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    weekly: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    examples: dict[tuple[str, str], list[int]] = defaultdict(list)

    def note(kind: str, key: str, post: Post) -> None:
        dt = _aware(post.posted_at or post.scraped_at)
        week = trends._week(dt) if dt else None
        spread[kind][key][post.platform] += 1
        if week in labels:
            weekly[kind][key][week] += 1
        if len(examples[(kind, key)]) < 4:
            examples[(kind, key)].append(post.id)

    for p in posts:
        if p.model_family and p.model_source in ("explicit", "metadata"):
            note("model", p.model_family, p)
        for t in p.technique_tags or []:
            note("technique", t, p)
        assigned = trends.clusters.assign(trends.clusters._view(p, creators))
        for key, _ in assigned.get("style", []):
            note("style", key, p)
        for key, _ in assigned.get("topic", []):
            note("topic", key, p)

    out = []
    for kind, table in spread.items():
        for key, platforms in table.items():
            total = sum(platforms.values())
            if total < MIN_PATTERN_SUPPORT:
                continue
            series = [weekly[kind][key].get(w, 0) for w in labels]
            vel = velocity(series)
            n_platforms = len(platforms)
            # a signal on 3 platforms outranks a bigger one on a single site
            score = round(total * (1 + 0.6 * (n_platforms - 1)) * min(2.0, vel["velocity"]), 1)
            out.append({
                "kind": kind, "key": key, "total": total,
                "platforms": dict(sorted(platforms.items(), key=lambda kv: -kv[1])),
                "platform_count": n_platforms, "series": series,
                **{k: vel[k] for k in ("velocity", "acceleration", "direction")},
                "score": score, "example_post_ids": examples[(kind, key)],
                "why": (f"seen {total}× across {n_platforms} platform"
                        f"{'s' if n_platforms != 1 else ''}; {vel['detail']}"),
            })
    out.sort(key=lambda r: (-r["platform_count"], -r["score"]))
    return {"weeks": labels, "signals": out[:limit],
            "posts_considered": len(posts),
            "cross_platform_count": sum(1 for r in out if r["platform_count"] > 1),
            "computed_at": now.isoformat()}


# ------------------------------------------------------- prompt patterns ---
def prompt_patterns(s: Session, weeks: int = 12, now: datetime | None = None,
                    limit: int = 30, min_support: int = MIN_PATTERN_SUPPORT) -> dict:
    """Phrase SETS that keep appearing together in published prompts (§45).

    Only high-confidence, creator-published prompts are mined — a prompt PF2
    reconstructed or a model guessed is not evidence of what works (§93)."""
    now = now or datetime.now(timezone.utc)
    posts = _post_rows(s, weeks, now)
    pairs: Counter = Counter()
    pair_platforms: dict[tuple[str, str], set[str]] = defaultdict(set)
    pair_posts: dict[tuple[str, str], list[int]] = defaultdict(list)
    pair_engagement: dict[tuple[str, str], list[int]] = defaultdict(list)
    singles: Counter = Counter()
    considered = 0

    for p in posts:
        if not p.prompt or not prompt_parser.is_explicit_source(p.prompt_source):
            continue
        if p.assertions and not provenance.is_high_confidence(p.assertions, "prompt"):
            continue
        considered += 1
        phrases = sorted({ph for ph in kstats.extract_phrases(p.prompt)
                          if len(ph) > 3})[:24]
        singles.update(phrases)
        for combo in combinations(phrases, 2):
            pairs[combo] += 1
            pair_platforms[combo].add(p.platform)
            if len(pair_posts[combo]) < 4:
                pair_posts[combo].append(p.id)
            if p.engagement_total:
                pair_engagement[combo].append(p.engagement_total)

    out = []
    for combo, count in pairs.most_common(limit * 8):
        if count < min_support:
            continue
        # lift: do these two travel together more OFTEN than chance predicts?
        # (1.0 = exactly as often; below 1.0 they actively avoid each other and
        # are not a pattern at all. A pair that always co-occurs in a small,
        # uniform corpus sits AT 1.0 — recurring, but not yet surprising.)
        expected = (singles[combo[0]] * singles[combo[1]]) / max(1, considered)
        lift = round(count / max(0.5, expected), 2)
        if lift < 1.0:
            continue
        eng = pair_engagement[combo]
        notable = lift >= 1.2
        out.append({
            "phrases": list(combo), "posts": count, "lift": lift, "notable": notable,
            "platforms": sorted(pair_platforms[combo]),
            "platform_count": len(pair_platforms[combo]),
            "avg_engagement": round(sum(eng) / len(eng)) if eng else None,
            "example_post_ids": pair_posts[combo],
            "why": (f"appear together in {count} published prompts across "
                    f"{len(pair_platforms[combo])} platform(s)"
                    + (f", {lift}× more often than chance" if notable
                       else " (as often as chance predicts — recurring, not surprising)")),
        })
    out.sort(key=lambda r: (-r["platform_count"], -r["lift"], -r["posts"]))
    return {"patterns": out[:limit], "prompts_considered": considered,
            "notable": sum(1 for r in out if r["notable"]),
            "basis": "published prompts only — reconstructed and AI-written "
                     "prompts are excluded (§21/§93)",
            "computed_at": now.isoformat()}


# ---------------------------------------------------- engagement growth ----
def _snapshot_total(snap: EngagementSnapshot) -> int:
    """One snapshot's engagement, summed the same way scoring does."""
    return scoring.engagement_total(
        {k: getattr(snap, k, None) for k in scoring._ENGAGEMENT_KEYS}) or 0


def engagement_growth(s: Session, limit: int = 25, min_snapshots: int = 2,
                      now: datetime | None = None) -> dict:
    """How fast stored posts are still gaining, straight from the snapshots
    each re-scrape appends (D62). Posts PF2 only ever saw once cannot have a
    growth rate, and are reported as such rather than guessed at."""
    now = now or datetime.now(timezone.utc)
    rows = s.execute(select(EngagementSnapshot).order_by(EngagementSnapshot.post_id,
                                                         EngagementSnapshot.at)).scalars()
    by_post: dict[int, list[EngagementSnapshot]] = defaultdict(list)
    for row in rows:
        by_post[row.post_id].append(row)

    out = []
    for post_id, snaps in by_post.items():
        if len(snaps) < min_snapshots:
            continue
        first, last = snaps[0], snaps[-1]
        hours = max(0.5, (_aware(last.at) - _aware(first.at)).total_seconds() / 3600)
        start, end = _snapshot_total(first), _snapshot_total(last)
        delta = end - start
        if delta <= 0:
            continue
        per_day = round(delta / (hours / 24), 1)
        # a post that gained 500 in a day beats one that gained 500 in a month
        out.append({"post_id": post_id, "gain": delta, "per_day": per_day,
                    "hours_observed": round(hours, 1), "snapshots": len(snaps),
                    "from": start, "to": end,
                    "why": f"+{delta} engagement in {round(hours, 1)}h "
                           f"({per_day}/day over {len(snaps)} observations)"})
    out.sort(key=lambda r: -r["per_day"])
    with_history = sum(1 for snaps in by_post.values() if len(snaps) >= min_snapshots)
    total_posts = s.execute(select(func.count()).select_from(Post)).scalar_one()
    return {"growing": out[:limit], "posts_with_history": with_history,
            "posts_seen_once": max(0, total_posts - with_history),
            "note": "growth needs at least two observations of the same post; "
                    "posts seen once have no growth rate (never estimated)",
            "computed_at": now.isoformat()}


# -------------------------------------------------------- discovery modes --
def _why_row(p: Post, mode: str, extra: list[str] | None = None) -> list[str]:
    why = list(extra or [])
    if prompt_parser.is_explicit_source(p.prompt_source):
        why.append("carries a prompt the creator published")
    elif p.prompt_source == "assembled":
        why.append("prompt reconstructed from published fragments")
    elif prompt_parser.is_ai_source(p.prompt_source):
        why.append("prompt written by an AI, not the creator")
    if p.has_workflow:
        why.append("ships a workflow")
    if p.model_name and p.model_source in ("explicit", "metadata"):
        why.append(f"model stated: {p.model_name}")
    if p.inspiration_score:
        why.append(f"inspiration {round(p.inspiration_score)}")
    if p.engagement_total:
        why.append(f"{p.engagement_total} engagement")
    return why[:5]


def discover(s: Session, mode: str = "trending", limit: int = 40,
             platform: str | None = None, media_type: str | None = None,
             query: str | None = None, now: datetime | None = None) -> dict:
    """One ranked shelf per mode, every row carrying WHY it is there (§46).

    Nothing here needs an AI provider; the reasons are the same numbers the
    ranking used, so a user can always check the shelf's reasoning."""
    now = now or datetime.now(timezone.utc)
    if mode not in MODES:
        mode = "trending"
    stmt = select(Post)
    if platform:
        stmt = stmt.where(Post.platform == platform)
    if media_type:
        stmt = stmt.where(Post.media_type == media_type)
    if mode == "best_prompts":
        stmt = stmt.where(Post.prompt.is_not(None),
                          Post.prompt_source.in_(
                              [n for n in prompt_parser.PROMPT_SOURCES
                               if prompt_parser.is_explicit_source(n)]))
    elif mode == "workflows":
        stmt = stmt.where(Post.has_workflow.is_(True))
    posts = list(s.execute(stmt.order_by(Post.id.desc()).limit(4000)).scalars())

    # §42/§124: when the shelf is asked a question, relevance to THAT question
    # is a first-class ranking signal, not a filter bolted on afterwards.
    intent = None
    if query and query.strip():
        from . import query_intent, research
        intent = query_intent.interpret(query.strip())
        relevance_of = research.query_relevance
    growth = {r["post_id"]: r for r in engagement_growth(s, limit=500)["growing"]}
    linked_signals = {}
    if mode == "cross_platform":
        for sig in cross_platform_signals(s, now=now, limit=60)["signals"]:
            if sig["platform_count"] > 1:
                linked_signals[(sig["kind"], sig["key"])] = sig

    rows = []
    for p in posts:
        why: list[str] = []
        score = 0.0
        age_days = max(0.5, (now - (_aware(p.posted_at or p.scraped_at) or now)).days or 0.5)
        if mode == "trending":
            g = growth.get(p.id)
            score = (g["per_day"] if g else 0) * 2 + (p.engagement_total or 0) / age_days
            if g:
                why.append(g["why"])
            else:
                why.append(f"{p.engagement_total or 0} engagement in {round(age_days)}d")
        elif mode == "best_prompts":
            words = len((p.prompt or "").split())
            score = (p.inspiration_score or 0) + min(40, words) + (
                20 if any(k in (p.params or {}) for k in ("seed", "steps", "cfg_scale")) else 0)
            why.append(f"{words}-word published prompt")
        elif mode == "latest":
            score = (p.posted_at or p.scraped_at or datetime.min.replace(
                tzinfo=timezone.utc)).timestamp()
            why.append("newest first")
        elif mode == "hidden_gems":
            # strong work that nobody has noticed yet (§63/§174)
            if (p.inspiration_score or 0) < 50:
                continue
            score = (p.inspiration_score or 0) * 1.5 - min(60, (p.engagement_total or 0) / 50)
            why.append(f"strong post with only {p.engagement_total or 0} engagement")
        elif mode == "workflows":
            score = (p.inspiration_score or 0) + 30
            why.append("reproducible: workflow attached")
        elif mode == "cross_platform":
            hits = [sig for (kind, key), sig in linked_signals.items()
                    if (kind == "model" and p.model_family == key)
                    or (kind == "technique" and key in (p.technique_tags or []))]
            if not hits:
                continue
            best = max(hits, key=lambda h: h["score"])
            score = best["score"] + (p.inspiration_score or 0) / 10
            why.append(f"part of a signal on {best['platform_count']} platforms: {best['key']}")
        relevance = None
        if intent is not None:
            relevance, reasons = relevance_of(p, intent)
            if relevance < 0.4:
                continue                       # not an answer to this question
            why = reasons + why
            # relevance dominates, the mode's own signal breaks the ties
            score = relevance * 100 + score / max(1.0, abs(score) or 1.0) * 10
        rows.append({"post_id": p.id, "platform": p.platform, "score": round(score, 2),
                     "relevance": round(relevance, 3) if relevance is not None else None,
                     "why": _why_row(p, mode, why)})
    rows.sort(key=lambda r: -r["score"])
    return {"mode": mode, "results": rows[:limit], "considered": len(posts),
            "modes": list(MODES), "query": query or None,
            "ranked_by": ("query relevance, then " if intent is not None else "")
                         + DISCOVERY_DETAIL[mode],
            "detail": DISCOVERY_DETAIL[mode], "computed_at": now.isoformat()}


DISCOVERY_DETAIL = {
    "trending": "gaining fastest right now, measured from repeat observations "
                "of the same post (falls back to engagement per day)",
    "best_prompts": "posts whose prompt the creator actually published, richest first",
    "latest": "newest first",
    "hidden_gems": "strong work that has not been noticed yet",
    "workflows": "posts that ship a reproducible workflow",
    "cross_platform": "posts carrying a signal that is showing up on more than "
                      "one platform",
}


def summary(s: Session, weeks: int = 8) -> dict:
    """Everything I14 can say at a glance — used by the Inspiration overview."""
    now = datetime.now(timezone.utc)
    cross = cross_platform_signals(s, weeks=weeks, now=now, limit=12)
    patterns = prompt_patterns(s, weeks=weeks * 2, now=now, limit=12)
    growth = engagement_growth(s, limit=10, now=now)
    return {
        "cross_platform": cross,
        "prompt_patterns": patterns,
        "engagement_growth": growth,
        "rising": [r for r in cross["signals"] if r["direction"] == "rising"][:8],
        "requires_ai": False,
        "computed_at": now.isoformat(),
    }
