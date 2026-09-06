"""Cross-source creator identity (Inspiration 2.0, I12; spec §73).

The same person posts as `@mara` on X, `u/mara_makes` on Reddit and
`mara.bsky.social` on Bluesky. PF2 links those rows — it never MERGES them:
each platform identity keeps its own posts, stats and provenance, and the
link is an evidence-carrying edge in `creator_links` that the user can
confirm or remove.

The rule that makes this safe: **a name match is never evidence.** Two
handles spelled the same on two platforms are two strangers until something
observable ties them together:

  same_media    the identical media (content hash) or a near-duplicate
                (dHash) was posted by both — the strongest signal PF2 can
                observe from its own store
  shared_url    both profiles point at the same off-platform URL (the
                platforms' own domains don't count)
  cross_ref     one profile names the other's handle ON that platform
                ("also @mara on x", "reddit.com/u/mara_makes")
  user          a person said so in the GUI

Handle similarity only ever RAISES the confidence of a link that already has
one of the above; on its own it produces nothing. Suggestions are never
written automatically below `creator_link_min_confidence`, and everything
written records what tied the two rows together.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import settings_store
from ..models import Creator, CreatorLink, Post
from . import dedupe

# evidence kind → base confidence
EVIDENCE_CONFIDENCE = {"user": 1.0, "same_media": 0.9, "shared_url": 0.75,
                       "cross_ref": 0.8, "near_dup_media": 0.6}
EVIDENCE_KINDS = tuple(EVIDENCE_CONFIDENCE)
AUTO_KINDS = ("same_media", "cross_ref", "shared_url")   # never handle-only
MIN_AUTO_CONFIDENCE = 0.75

# platform → the hosts that ARE that platform (so a link to your own profile
# on the same site is not "a shared external site")
PLATFORM_HOSTS = {
    "x": ("x.com", "twitter.com", "t.co"),
    "reddit": ("reddit.com", "redd.it"),
    "bluesky": ("bsky.app", "bsky.social"),
    "youtube": ("youtube.com", "youtu.be"),
    "instagram": ("instagram.com",),
    "tiktok": ("tiktok.com",),
    "pinterest": ("pinterest.com",),
    "threads": ("threads.net",),
    "tumblr": ("tumblr.com",),
    "civitai": ("civitai.com",),
    "lexica": ("lexica.art",),
}
# hosts that link nothing (everyone has one)
GENERIC_HOSTS = {"linktr.ee", "bit.ly", "discord.gg", "patreon.com", "ko-fi.com",
                 "gmail.com", "google.com", "notion.so", "beacons.ai"}

_URL_RE = re.compile(r"https?://[^\s)>\]\"']+|(?<![\w@/])(?:www\.)?[\w-]+\.[a-z]{2,10}(?:/[^\s)>\]\"']*)?",
                     re.I)
_HANDLE_REF_RE = re.compile(r"(?:^|\s|/)@?([A-Za-z0-9_.-]{3,40})", re.I)


def _host_and_path(url: str) -> tuple[str, str]:
    u = re.sub(r"^https?://", "", (url or "").strip(), flags=re.I).rstrip("/")
    u = re.sub(r"^www\.", "", u, flags=re.I)
    host, _, path = u.partition("/")
    return host.lower(), path.lower()


def profile_urls(creator: Creator) -> set[str]:
    """Normalised off-platform URLs a creator's own profile advertises.

    Only the bio and profile_url are read — never anything a stranger wrote."""
    own = set(PLATFORM_HOSTS.get(creator.platform, ()))
    out: set[str] = set()
    for raw in _URL_RE.findall(f"{creator.bio or ''} {creator.profile_url or ''}"):
        host, path = _host_and_path(raw)
        if not host or "." not in host or host in GENERIC_HOSTS:
            continue
        if any(host == h or host.endswith("." + h) for h in own):
            continue          # a link to your own platform is not evidence
        out.add(f"{host}/{path}".rstrip("/"))
    return out


def _platform_of_host(host: str) -> str | None:
    for platform, hosts in PLATFORM_HOSTS.items():
        if any(host == h or host.endswith("." + h) for h in hosts):
            return platform
    return None


def cross_references(creator: Creator) -> set[tuple[str, str]]:
    """(platform, handle) pairs this creator's own profile POINTS AT."""
    text = f"{creator.bio or ''} {creator.profile_url or ''}"
    out: set[tuple[str, str]] = set()
    for raw in _URL_RE.findall(text):
        host, path = _host_and_path(raw)
        platform = _platform_of_host(host)
        if not platform or platform == creator.platform:
            continue
        parts = [p for p in path.split("/") if p and p not in
                 ("u", "user", "users", "profile", "c", "channel", "@")]
        if parts:
            out.add((platform, parts[-1].lstrip("@").lower()))
    # "also @mara on bluesky" — the platform must be NAMED next to the handle
    for platform in PLATFORM_HOSTS:
        if platform == creator.platform:
            continue
        for m in re.finditer(rf"@([A-Za-z0-9_.-]{{3,40}})[^\n]{{0,20}}\b{platform}\b"
                             rf"|\b{platform}\b[^\n]{{0,20}}@([A-Za-z0-9_.-]{{3,40}})",
                             text, re.I):
            handle = (m.group(1) or m.group(2) or "").lower()
            if handle:
                out.add((platform, handle))
    return out


def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


def _handle_affinity(a: Creator, b: Creator) -> float:
    """A corroborator only: it can lift an existing link's confidence, it can
    never create one."""
    ha, hb = a.handle or "", b.handle or ""
    if not ha or not hb:
        return 0.0
    norm = lambda h: re.sub(r"[^a-z0-9]", "", h.lower())  # noqa: E731
    na, nb = norm(ha), norm(hb)
    if na == nb:
        return 0.1
    if na and nb and (na in nb or nb in na):
        return 0.05
    return 0.0


# ------------------------------------------------------------- suggestions --
def _media_evidence(s: Session) -> dict[tuple[int, int], dict]:
    """Creators who published the SAME bytes, or a near-duplicate image.

    This is PF2's own observation, not a claim from a profile — the strongest
    thing it can know without the user telling it."""
    out: dict[tuple[int, int], dict] = {}
    by_hash: dict[str, set[int]] = defaultdict(set)
    rows = s.execute(select(Post.creator_id, Post.content_hash, Post.phash, Post.id,
                            Post.platform)
                     .where(Post.creator_id.is_not(None))).all()
    by_phash: list[tuple[int, str, int, str]] = []
    for creator_id, chash, phash, post_id, platform in rows:
        if chash:
            by_hash[chash].add(creator_id)
        if phash:
            by_phash.append((creator_id, phash, post_id, platform))

    creators = {c.id: c for c in s.execute(select(Creator)).scalars()}
    for chash, ids in by_hash.items():
        if len(ids) < 2:
            continue
        ordered = sorted(ids)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                if not _different_platforms(creators, a, b):
                    continue
                out[_pair(a, b)] = {
                    "kind": "same_media", "detail": "identical media published by both",
                    "content_hash": chash[:16]}

    distance = int(settings_store.get(s, "intel_near_dup_distance") or 6)
    for i, (ca, pa, post_a, _) in enumerate(by_phash):
        for cb, pb, post_b, _ in by_phash[i + 1:]:
            if ca == cb or not _different_platforms(creators, ca, cb):
                continue
            key = _pair(ca, cb)
            if key in out and out[key]["kind"] == "same_media":
                continue
            if dedupe.hamming(pa, pb) <= distance:
                out[key] = {"kind": "near_dup_media",
                            "detail": "near-duplicate media published by both",
                            "post_ids": [post_a, post_b]}
    return out


def _different_platforms(creators: dict[int, Creator], a: int, b: int) -> bool:
    ca, cb = creators.get(a), creators.get(b)
    return bool(ca and cb and ca.platform != cb.platform)


def suggest_links(s: Session, creator_id: int | None = None,
                  limit: int = 50) -> list[dict]:
    """Evidence-backed candidates. Read-only: nothing is written here."""
    creators = list(s.execute(select(Creator)).scalars())
    by_id = {c.id: c for c in creators}
    by_handle: dict[tuple[str, str], Creator] = {
        (c.platform, (c.handle or "").lower()): c for c in creators}
    found: dict[tuple[int, int], dict] = {}

    def add(a: int, b: int, evidence: dict) -> None:
        if a == b or not _different_platforms(by_id, a, b):
            return
        key = _pair(a, b)
        base = EVIDENCE_CONFIDENCE.get(evidence["kind"], 0.5)
        cur = found.get(key)
        if cur and EVIDENCE_CONFIDENCE.get(cur["evidence"]["kind"], 0) >= base:
            cur.setdefault("also", []).append(evidence["kind"])
            return
        found[key] = {"a": key[0], "b": key[1], "evidence": evidence,
                      "confidence": base, "also": (cur or {}).get("also", [])}

    # 1. observable: the same media on two platforms
    for (a, b), ev in _media_evidence(s).items():
        add(a, b, ev)

    # 2. the creators' own profiles pointing at each other
    urls: dict[int, set[str]] = {c.id: profile_urls(c) for c in creators}
    for creator in creators:
        for platform, handle in cross_references(creator):
            other = by_handle.get((platform, handle))
            if other is not None:
                add(creator.id, other.id,
                    {"kind": "cross_ref",
                     "detail": f"{creator.platform}:@{creator.handle}'s own profile links "
                               f"{platform}:@{handle}"})

    # 3. both profiles advertising the same off-platform site
    by_url: dict[str, set[int]] = defaultdict(set)
    for cid, us in urls.items():
        for u in us:
            by_url[u].add(cid)
    for url, ids in by_url.items():
        if len(ids) < 2 or len(ids) > 6:      # a link 7 people share is a hub
            continue
        ordered = sorted(ids)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                add(a, b, {"kind": "shared_url", "detail": f"both profiles link {url}",
                           "url": url})

    existing = {(_pair(l.creator_a, l.creator_b)) for l in
                s.execute(select(CreatorLink)).scalars()}
    out = []
    for key, row in found.items():
        if key in existing:
            continue
        if creator_id is not None and creator_id not in key:
            continue
        a, b = by_id[key[0]], by_id[key[1]]
        confidence = min(0.99, row["confidence"] + _handle_affinity(a, b))
        out.append({
            "creator_a": {"id": a.id, "platform": a.platform, "handle": a.handle},
            "creator_b": {"id": b.id, "platform": b.platform, "handle": b.handle},
            "kind": row["evidence"]["kind"],
            "confidence": round(confidence, 2),
            "evidence": row["evidence"],
            "corroborated_by": sorted(set(row.get("also") or [])),
            "auto_linkable": (row["evidence"]["kind"] in AUTO_KINDS
                              and confidence >= MIN_AUTO_CONFIDENCE),
        })
    out.sort(key=lambda r: -r["confidence"])
    return out[:limit]


# ------------------------------------------------------------------ writes --
def record_link(s: Session, a: int, b: int, kind: str, detail: str | None = None,
                confidence: float | None = None, created_by: str = "system",
                evidence: dict | None = None) -> CreatorLink | None:
    """Create (or strengthen) an evidence-carrying link. Refuses an unknown
    evidence kind — there is deliberately no "they have the same name" kind."""
    if a == b or kind not in EVIDENCE_CONFIDENCE:
        return None
    if s.get(Creator, a) is None or s.get(Creator, b) is None:
        return None
    lo, hi = _pair(a, b)
    conf = float(confidence if confidence is not None else EVIDENCE_CONFIDENCE[kind])
    row = s.execute(select(CreatorLink).where(CreatorLink.creator_a == lo,
                                              CreatorLink.creator_b == hi)).scalars().first()
    payload = {"kind": kind, "detail": detail, "observed_at": datetime.now(timezone.utc).isoformat(),
               **(evidence or {})}
    if row is None:
        row = CreatorLink(creator_a=lo, creator_b=hi, confidence=round(conf, 3),
                          evidence=payload, created_by=created_by)
        s.add(row)
    elif created_by == "user" or conf > (row.confidence or 0):
        row.confidence = round(max(conf, row.confidence or 0), 3)
        row.evidence = {**(row.evidence or {}), **payload,
                        "previous": (row.evidence or {}).get("kind")}
        row.created_by = created_by if created_by == "user" else row.created_by
    s.flush()
    return row


def unlink(s: Session, link_id: int) -> bool:
    row = s.get(CreatorLink, link_id)
    if row is None:
        return False
    s.delete(row)
    s.flush()
    return True


def scan(s: Session) -> dict:
    """Record the suggestions that clear the bar; report the rest. Never
    links on a name match, and never above what the evidence supports."""
    threshold = float(settings_store.get(s, "creator_link_min_confidence")
                      or MIN_AUTO_CONFIDENCE)
    created, held = 0, 0
    for row in suggest_links(s, limit=500):
        if row["kind"] in AUTO_KINDS and row["confidence"] >= threshold:
            if record_link(s, row["creator_a"]["id"], row["creator_b"]["id"], row["kind"],
                           row["evidence"].get("detail"), row["confidence"],
                           evidence=row["evidence"]) is not None:
                created += 1
        else:
            held += 1
    return {"linked": created, "suggested_only": held, "threshold": threshold}


# ------------------------------------------------------------------ reads --
def links_for(s: Session, creator_id: int) -> list[dict]:
    rows = s.execute(select(CreatorLink).where(
        or_(CreatorLink.creator_a == creator_id,
            CreatorLink.creator_b == creator_id))).scalars().all()
    out = []
    for link in rows:
        other_id = link.creator_b if link.creator_a == creator_id else link.creator_a
        other = s.get(Creator, other_id)
        if other is None:
            continue
        out.append({"link_id": link.id, "creator_id": other.id, "platform": other.platform,
                    "handle": other.handle, "display_name": other.display_name,
                    "profile_url": other.profile_url, "confidence": link.confidence,
                    "kind": (link.evidence or {}).get("kind"),
                    "evidence": link.evidence or {}, "created_by": link.created_by})
    out.sort(key=lambda r: -(r["confidence"] or 0))
    return out


def identity(s: Session, creator_id: int) -> dict:
    """The whole linked identity (transitive closure) — presented together,
    still stored apart. Each platform keeps its own row, posts and stats."""
    seen: set[int] = set()
    frontier = [creator_id]
    edges: list[dict] = []
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for row in links_for(s, cur):
            edges.append({"from": cur, **row})
            if row["creator_id"] not in seen:
                frontier.append(row["creator_id"])
    members = []
    for cid in sorted(seen):
        c = s.get(Creator, cid)
        if c is None:
            continue
        st = c.stats or {}
        # counted from the store, not from possibly-stale cached stats
        posts = s.execute(select(func.count()).select_from(Post)
                          .where(Post.creator_id == c.id)).scalar_one()
        members.append({"creator_id": c.id, "platform": c.platform, "handle": c.handle,
                        "display_name": c.display_name, "posts": posts,
                        "followers": c.followers,
                        "avg_engagement": st.get("avg_engagement"),
                        "prompt_availability": st.get("prompt_availability")})
    return {
        "creator_id": creator_id,
        "platforms": sorted({m["platform"] for m in members}),
        "members": members,
        "total_posts": sum(m["posts"] for m in members),
        "links": edges,
        "merged": False,
        "note": ("Linked identities are shown together but never merged — each "
                 "platform keeps its own posts, stats and provenance."),
    }


def scan_job() -> dict:
    """Scheduler entry (hourly): only runs when the user leaves it on."""
    from ..db import session_scope
    from ..logbus import bus
    with session_scope() as s:
        if not settings_store.get(s, "creator_link_auto_scan"):
            return {"skipped": "creator_link_auto_scan is off"}
        out = scan(s)
    if out.get("linked"):
        bus.info("intel", f"creator identity: linked {out['linked']} cross-source "
                          f"pair(s), {out['suggested_only']} held for review")
    return out
