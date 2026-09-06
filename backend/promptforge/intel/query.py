"""Advanced search syntax (I6.1) — deterministic parser + SQL filters.

Existing qualifiers stay (tag: model: platform:); new ones:
  has:prompt|workflow|video|image|metadata|comments   creator:name
  technique:slug   camera:35mm|close-up|low-angle      after:YYYY-MM-DD
  before:YYYY-MM-DD   engagement:>1000   inspiration:>80   ai:true|false|uncertain
  model_source:explicit|metadata|inferred|ai   sort:inspiration|engagement|newest|oldest
  prompt_source:<ladder value>|observed|metadata|extracted|ai|explicit   (I11, §20)
Values may be quoted. Unknown operators are ignored, never errors."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, or_, select

from ..aliases import normalize_model
from ..models import Creator, Post, PostTag, Tag
from . import prompt_parser

QUALIFIERS = ("tag", "model", "platform", "has", "creator", "technique", "camera", "after",
              "before", "engagement", "inspiration", "ai", "model_source", "prompt_source",
              "sort")
_QUAL_RE = re.compile(r'(?<!\S)(' + "|".join(QUALIFIERS) + r'):("([^"]*)"|(\S+))', re.I)
_NUM_RE = re.compile(r"^(>=|<=|>|<|=)?\s*(\d+(?:\.\d+)?)$")
HAS_VALUES = {"prompt", "workflow", "video", "image", "metadata", "comments"}
AI_TRUE = ("definitely_ai", "probably_ai")
AI_FALSE = ("probably_not_ai", "definitely_not_ai")
SORTS = {"inspiration", "engagement", "newest", "oldest", "relevance"}


def _prompt_sources(value: str) -> list[str]:
    """`prompt_source:` accepts a ladder value, a coarse provenance rank, or
    the shorthand `explicit` — and matches rows written in EITHER vocabulary
    (pre-I11 rows carry the coarse rank in the column)."""
    if value in prompt_parser.PROMPT_SOURCES:
        return [value]
    if value == "explicit":
        return [n for n in prompt_parser.PROMPT_SOURCES
                if prompt_parser.is_explicit_source(n)]
    fine = prompt_parser.FINE_BY_COARSE.get(value)
    return [*fine, value] if fine else []


@dataclass
class ParsedQuery:
    free_text: str = ""
    tags: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    has: set[str] = field(default_factory=set)
    creators: list[str] = field(default_factory=list)
    techniques: list[str] = field(default_factory=list)
    cameras: list[str] = field(default_factory=list)
    after: datetime | None = None
    before: datetime | None = None
    engagement: tuple[str, float] | None = None
    inspiration: tuple[str, float] | None = None
    ai: str | None = None                 # "true" | "false" | "uncertain"
    model_source: str | None = None
    prompt_sources: list[str] = field(default_factory=list)
    sort: str | None = None
    ignored: list[str] = field(default_factory=list)

    def legacy(self) -> dict[str, list[str]]:
        return {"tag": list(self.tags), "model": list(self.models), "platform": list(self.platforms)}


def _date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _num(value: str) -> tuple[str, float] | None:
    m = _NUM_RE.match(value.strip())
    if not m:
        return None
    return (m.group(1) or ">="), float(m.group(2))


def parse(q: str) -> ParsedQuery:
    pq = ParsedQuery()

    def _collect(m: re.Match) -> str:
        key = m.group(1).lower()
        value = (m.group(3) if m.group(3) is not None else m.group(4) or "").strip()
        if not value:
            return " "
        low = value.lower()
        if key == "tag":
            pq.tags.append(value)
        elif key == "model":
            pq.models.append(value)
        elif key == "platform":
            pq.platforms.append(low)
        elif key == "has":
            (pq.has.add(low) if low in HAS_VALUES else pq.ignored.append(f"has:{value}"))
        elif key == "creator":
            pq.creators.append(low.lstrip("@"))
        elif key == "technique":
            pq.techniques.append(low)
        elif key == "camera":
            pq.cameras.append(low)
        elif key in ("after", "before"):
            d = _date(value)
            if d is None:
                pq.ignored.append(f"{key}:{value}")
            elif key == "after":
                pq.after = d
            else:
                pq.before = d
        elif key in ("engagement", "inspiration"):
            n = _num(value)
            if n is None:
                pq.ignored.append(f"{key}:{value}")
            elif key == "engagement":
                pq.engagement = n
            else:
                pq.inspiration = n
        elif key == "ai":
            if low in ("true", "false", "uncertain"):
                pq.ai = low
            else:
                pq.ignored.append(f"ai:{value}")
        elif key == "model_source":
            if low in ("explicit", "metadata", "inferred", "ai"):
                pq.model_source = low
            else:
                pq.ignored.append(f"model_source:{value}")
        elif key == "prompt_source":
            values = _prompt_sources(low)
            if values:
                pq.prompt_sources = values
            else:
                pq.ignored.append(f"prompt_source:{value}")
        elif key == "sort":
            if low in SORTS:
                pq.sort = low
            else:
                pq.ignored.append(f"sort:{value}")
        return " "

    pq.free_text = re.sub(r"\s+", " ", _QUAL_RE.sub(_collect, q or "")).strip()
    return pq


def _cmp(column, op: str, n: float):
    return {">": column > n, ">=": column >= n, "<": column < n,
            "<=": column <= n, "=": column == n}[op]


def apply_filters(stmt, pq: ParsedQuery):
    """Everything except tag/model/platform (the existing filter path owns those)."""
    when = func.coalesce(Post.posted_at, Post.scraped_at)
    if "prompt" in pq.has:
        stmt = stmt.where(Post.prompt.is_not(None), Post.prompt != "")
    if "workflow" in pq.has:
        stmt = stmt.where(Post.has_workflow.is_(True))
    if "video" in pq.has:
        stmt = stmt.where(Post.media_type == "video")
    if "image" in pq.has:
        stmt = stmt.where(Post.media_type == "image")
    if "metadata" in pq.has:
        stmt = stmt.where(Post.params.like('%"metadata_format"%'))
    if "comments" in pq.has:
        stmt = stmt.where(Post.enrichment.like('%"comments"%'))
    for name in pq.creators:
        stmt = stmt.where(or_(
            Post.creator_id.in_(select(Creator.id).where(Creator.handle == name)),
            func.lower(Post.author) == f"@{name}", func.lower(Post.author) == name))
    for slug in pq.techniques:
        stmt = stmt.where(Post.technique_tags.like(f'%"{slug}"%'))
    for term in pq.cameras:
        stmt = stmt.where(or_(Post.assertions.like(f"%{term}%"), Post.prompt.like(f"%{term}%")))
    if pq.after:
        stmt = stmt.where(when >= pq.after)
    if pq.before:
        stmt = stmt.where(when <= pq.before)
    if pq.engagement:
        stmt = stmt.where(_cmp(Post.engagement_total, *pq.engagement))
    if pq.inspiration:
        stmt = stmt.where(_cmp(Post.inspiration_score, *pq.inspiration))
    if pq.ai == "true":
        stmt = stmt.where(Post.ai_status.in_(AI_TRUE))
    elif pq.ai == "false":
        stmt = stmt.where(Post.ai_status.in_(AI_FALSE))
    elif pq.ai == "uncertain":
        stmt = stmt.where(Post.ai_status == "uncertain")
    if pq.model_source:
        stmt = stmt.where(Post.model_source == pq.model_source)
    if pq.prompt_sources:
        stmt = stmt.where(Post.prompt_source.in_(pq.prompt_sources))
    return stmt


def apply_tags(stmt, tags: list[str]):
    for tag_name in tags:
        stmt = stmt.where(Post.id.in_(
            select(PostTag.post_id).join(Tag, Tag.id == PostTag.tag_id)
            .where(func.lower(Tag.name) == tag_name.lower())))
    return stmt


def order_for(stmt, sort: str | None):
    if sort == "inspiration":
        return stmt.order_by(Post.inspiration_score.desc().nulls_last(), Post.id.desc())
    if sort == "engagement":
        return stmt.order_by(Post.engagement_total.desc().nulls_last(), Post.id.desc())
    if sort == "oldest":
        return stmt.order_by(Post.id.asc())
    return stmt.order_by(Post.id.desc())


def sort_rows(rows: list, sort: str | None) -> list:
    """Re-rank an FTS-ranked list when a non-relevance sort is requested."""
    if sort == "inspiration":
        return sorted(rows, key=lambda p: (-(p.inspiration_score or 0), -p.id))
    if sort == "engagement":
        return sorted(rows, key=lambda p: (-(p.engagement_total or 0), -p.id))
    if sort == "newest":
        return sorted(rows, key=lambda p: -p.id)
    if sort == "oldest":
        return sorted(rows, key=lambda p: p.id)
    return rows


def normalize_model_filter(models: list[str]) -> str | None:
    if not models:
        return None
    return normalize_model(models[0]) or models[0]
