"""Provider-neutral creator + source discovery (Inspiration 2.0, I10;
spec §29–§30, §60, §165–§166).

Until now, "find me creators worth following" was a Grok-only feature. This
module does it from PF2's OWN sources: run the query against every capable
source, look at who actually posted the matching work, and rank the people
behind it on EVIDENCE we collected ourselves — AI-content ratio, whether
they publish prompts, engagement, recency, cross-source presence.

No LLM is required anywhere in here. Grok (or any other configured provider)
can still contribute candidates, but they arrive as unverified CLAIMS with
evidence attached (D71) and are ranked below creators PF2 has actually seen.
Nothing is ever auto-followed: discovery returns candidates, the user adds.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..logbus import bus
from ..models import Creator, MonitoredAccount, Post
from ..scrapers import all_adapters, get_adapter
from . import creators as creator_intel
from . import handles

# sources that can answer a keyword query with real posts
SEARCHABLE = ("search",)


def searchable_sources(s: Session, only: list[str] | None = None) -> list[str]:
    """Configured sources that can run a query right now (§128: an
    unconfigured or browser-gated source is skipped, never fatal)."""
    out = []
    for name, adapter in all_adapters().items():
        if only and name not in only:
            continue
        if not hasattr(adapter, "search"):
            continue
        try:
            if not adapter.is_configured(s):
                continue
        except Exception:  # noqa: BLE001 — a broken adapter never blocks discovery
            continue
        out.append(name)
    return out


def _score_creator(rows: list[dict]) -> tuple[float, list[str]]:
    """Deterministic relevance for a discovered creator + why (§64)."""
    reasons: list[str] = []
    posts = len(rows)
    with_prompt = sum(1 for r in rows if r.get("has_prompt"))
    explicit = sum(1 for r in rows if r.get("prompt_explicit"))
    models = {r["model"] for r in rows if r.get("model")}
    engagement = [r.get("engagement") or 0 for r in rows]
    avg_eng = sum(engagement) / posts if posts else 0

    score = min(1.0, posts / 5) * 25
    reasons.append(f"{posts} matching post{'s' if posts != 1 else ''}")
    if with_prompt:
        ratio = with_prompt / posts
        score += ratio * 35
        reasons.append(f"{with_prompt}/{posts} carry a prompt"
                       + (f" ({explicit} labelled)" if explicit else ""))
    if models:
        score += min(15, 5 * len(models))
        reasons.append("models seen: " + ", ".join(sorted(models)[:3]))
    if avg_eng:
        import math
        score += min(15, math.log10(avg_eng + 1) * 5)
        reasons.append(f"avg engagement {int(avg_eng)}")
    platforms = {r["platform"] for r in rows}
    if len(platforms) > 1:
        score += 10
        reasons.append("posts on " + ", ".join(sorted(platforms)))
    return round(min(100.0, score), 1), reasons


def discover_creators(s: Session, query: str, *, sources: list[str] | None = None,
                      limit: int = 20, per_source: int = 40,
                      include_stored: bool = True) -> dict:
    """Run `query` across the capable sources and rank the creators behind
    the results. Returns candidates with the evidence that produced them —
    never a follow, never an LLM guess."""
    chosen = searchable_sources(s, sources)
    by_creator: dict[tuple[str, str], list[dict]] = defaultdict(list)
    per_source_status: dict[str, dict] = {}
    seen_posts = 0

    for name in chosen:
        adapter = get_adapter(name)
        client = None
        try:
            client = adapter.make_client(s)
            posts = adapter.search(s, client, query, limit=per_source)
            per_source_status[name] = {"state": "ok", "found": len(posts)}
            seen_posts += len(posts)
            for sp in posts:
                author = (sp.author or "").lstrip("@").strip()
                if not author:
                    continue
                params = sp.params or {}
                by_creator[(name, author)].append({
                    "platform": name, "author": author,
                    "post_id": str(sp.platform_post_id),
                    "url": sp.source_url,
                    "title": ((sp.observed or {}).get("text") or {}).get("title"),
                    "has_prompt": bool(sp.prompt),
                    "prompt_explicit": str(params.get("prompt_source", "")).startswith(
                        ("explicit", "embedded", "structured")),
                    "model": sp.model_name,
                    "engagement": _engagement_of(sp),
                    "posted_at": sp.posted_at.isoformat() if sp.posted_at else None,
                })
        except Exception as e:  # noqa: BLE001 — one bad source never kills discovery
            per_source_status[name] = {"state": "failed",
                                       "error": f"{type(e).__name__}: {e}"[:200]}
            bus.warn("discovery", f"{name}: search failed — {e}")
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass

    monitored = {(a.platform, a.handle.lower())
                 for a in s.execute(select(MonitoredAccount)).scalars()}
    candidates = []
    for (platform, author), rows in by_creator.items():
        score, reasons = _score_creator(rows)
        stored = creator_intel.find(s, platform, author) if include_stored else None
        stats = creator_intel.stats_for(s, stored) if stored else {}
        candidates.append({
            "platform": platform, "handle": author,
            "profile_url": handles.profile_url(author, platform),
            "relevance": score, "why": reasons,
            "verified": True,          # PF2 saw these posts itself
            "source": "search",
            "evidence": {"query": query, "matched_posts": rows[:6],
                         "observed_at": datetime.now(timezone.utc).isoformat()},
            "monitored": (platform, author.lower()) in monitored,
            "creator_id": stored.id if stored else None,
            "known_stats": {k: stats.get(k) for k in
                            ("posts", "ai_ratio", "prompt_availability",
                             "avg_engagement", "trend")} if stats else None,
        })
    candidates.sort(key=lambda c: -c["relevance"])
    return {"query": query, "sources": per_source_status,
            "searched": chosen, "posts_seen": seen_posts,
            "candidates": candidates[:limit],
            "grok_used": False,
            "note": ("Ranked from posts PF2 fetched itself — no AI provider was "
                     "involved. Adding a creator to monitoring is always your "
                     "choice.")}


def _engagement_of(sp: Any) -> int:
    from . import scoring
    eng = (sp.observed or {}).get("engagement") or (sp.params or {}).get("engagement") or {}
    return scoring.engagement_total(eng) or 0


def similar_creators(s: Session, creator_id: int, limit: int = 12) -> dict:
    """Creators whose work overlaps this one's — deterministic overlap of
    models, techniques and platforms over stored posts (§59)."""
    target = s.get(Creator, creator_id)
    if target is None:
        return {"creator_id": creator_id, "similar": []}
    t_stats = creator_intel.stats_for(s, target)
    t_models = {m["family"] for m in (t_stats.get("models") or []) if m.get("family")}
    t_tech = {t["slug"] if isinstance(t, dict) else t
              for t in (t_stats.get("techniques") or [])}
    out = []
    for other in s.execute(select(Creator).where(Creator.id != creator_id)).scalars():
        o_stats = creator_intel.stats_for(s, other)
        o_models = {m["family"] for m in (o_stats.get("models") or []) if m.get("family")}
        o_tech = {t["slug"] if isinstance(t, dict) else t
                  for t in (o_stats.get("techniques") or [])}
        shared_models = t_models & o_models
        shared_tech = t_tech & o_tech
        if not shared_models and not shared_tech:
            continue
        score = round(len(shared_models) * 12 + len(shared_tech) * 6
                      + (5 if other.platform != target.platform else 0), 1)
        out.append({"creator_id": other.id, "platform": other.platform,
                    "handle": other.handle, "score": score,
                    "shared_models": sorted(shared_models),
                    "shared_techniques": sorted(shared_tech)[:6],
                    "posts": o_stats.get("posts")})
    out.sort(key=lambda c: -c["score"])
    return {"creator_id": creator_id, "platform": target.platform,
            "handle": target.handle, "similar": out[:limit],
            "basis": "shared models and techniques across stored posts (deterministic)"}


def discovery_status(s: Session) -> dict:
    """What discovery can do right now, and with what (§29/§190)."""
    from ..integrations import grok as grok_int
    searchable = searchable_sources(s)
    return {
        "searchable_sources": searchable,
        "usable": bool(searchable),
        "requires_grok": False,
        "grok_available": grok_int.is_configured(s),
        "detail": (f"{len(searchable)} source(s) can answer a research query "
                   "without any AI provider."
                   if searchable else
                   "No source can run a search yet — connect at least one "
                   "(Reddit and Bluesky need no login)."),
    }
