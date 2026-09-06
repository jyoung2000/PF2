"""Deterministic research-query interpretation (Inspiration 2.0, I13;
spec §17, §28, §54, §124).

"Find the best AI video prompts about cinematic camera movement from the
last week" becomes structured filters WITHOUT an LLM: the parse is rules
only, every inference cites the words that produced it, and anything not
understood is reported (never silently dropped). An LLM may later refine a
query, but research never depends on one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..aliases import normalize_model
from ..knowledge import techniques
from . import prompt_parser

MODES = ("search", "topic", "model", "technique", "creator", "trend", "reference")

_MEDIA_RE = re.compile(r"\b(video|videos|animation|clip|clips|footage|motion)\b", re.I)
_IMAGE_RE = re.compile(r"\b(image|images|still|stills|photo|photos|art|artwork|picture)\b", re.I)
_WORKFLOW_RE = re.compile(r"\b(workflow|workflows|comfyui|node graph|pipeline|json)\b", re.I)
_PROMPT_RE = re.compile(r"\b(prompt|prompts|prompting)\b", re.I)
_CREATOR_RE = re.compile(r"\b(creator|creators|artist|artists|account|accounts|people|who)\b", re.I)
_TREND_RE = re.compile(r"\b(trend|trends|trending|emerging|new|latest|rising|right now)\b", re.I)
_BEST_RE = re.compile(r"\b(best|top|greatest|highest quality|strongest)\b", re.I)
_HIDDEN_RE = re.compile(r"\b(hidden gem|hidden gems|underrated|overlooked|undiscovered)\b", re.I)
_PERIODS = [
    (re.compile(r"\b(today|last 24 ?h|past day)\b", re.I), 1, "day"),
    (re.compile(r"\b(this week|last 7 days|past week|last week)\b", re.I), 7, "week"),
    (re.compile(r"\b(this month|last 30 days|past month|last month)\b", re.I), 30, "month"),
    (re.compile(r"\b(this year|last year|past year)\b", re.I), 365, "year"),
]
_NUM_DAYS_RE = re.compile(r"\blast (\d{1,3}) (day|days|week|weeks|month|months)\b", re.I)
_ENGAGEMENT_RE = re.compile(r"\b(viral|highly engaged|popular|high engagement)\b", re.I)


@dataclass
class ResearchIntent:
    query: str
    mode: str = "search"
    keywords: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    techniques: list[str] = field(default_factory=list)
    media_type: str | None = None        # video | image | None (both)
    wants_prompt: bool = False
    wants_workflow: bool = False
    wants_creators: bool = False
    period_days: int | None = None
    period_label: str | None = None
    rank: str = "relevance"              # relevance | best | trending | latest | hidden_gems
    min_engagement: int | None = None
    evidence: list[dict] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"query": self.query, "mode": self.mode, "keywords": self.keywords,
                "models": self.models, "techniques": self.techniques,
                "media_type": self.media_type, "wants_prompt": self.wants_prompt,
                "wants_workflow": self.wants_workflow, "wants_creators": self.wants_creators,
                "period_days": self.period_days, "period_label": self.period_label,
                "rank": self.rank, "min_engagement": self.min_engagement,
                "evidence": self.evidence, "ignored": self.ignored}


def _cite(out: ResearchIntent, field_name: str, value, text: str) -> None:
    out.evidence.append({"field": field_name, "value": value, "because": text})


def interpret(query: str) -> ResearchIntent:
    """Rules-only interpretation. Every conclusion carries its evidence."""
    q = (query or "").strip()
    out = ResearchIntent(query=q)
    if not q:
        return out
    low = q.lower()

    model = prompt_parser.detect_model(q)
    if model:
        out.models = [model]
        _cite(out, "models", [model], f"model name in the query: {model}")

    tech = techniques.detect_techniques(q)
    if tech:
        out.techniques = tech
        _cite(out, "techniques", tech, "technique vocabulary in the query")

    m = _MEDIA_RE.search(q)
    if m:
        out.media_type = "video"
        _cite(out, "media_type", "video", f"“{m.group(0)}”")
    elif _IMAGE_RE.search(q):
        out.media_type = "image"
        _cite(out, "media_type", "image", f"“{_IMAGE_RE.search(q).group(0)}”")

    if _PROMPT_RE.search(q):
        out.wants_prompt = True
        _cite(out, "wants_prompt", True, "the query asks for prompts")
    if _WORKFLOW_RE.search(q):
        out.wants_workflow = True
        _cite(out, "wants_workflow", True, "the query asks for workflows")
    if _CREATOR_RE.search(q):
        out.wants_creators = True
        out.mode = "creator"
        _cite(out, "mode", "creator", "the query asks about people")

    for pat, days, label in _PERIODS:
        m = pat.search(q)
        if m:
            out.period_days, out.period_label = days, label
            _cite(out, "period_days", days, f"“{m.group(0)}”")
            break
    else:
        m = _NUM_DAYS_RE.search(q)
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            days = n * (7 if unit.startswith("week") else 30 if unit.startswith("month") else 1)
            out.period_days, out.period_label = days, m.group(0)
            _cite(out, "period_days", days, f"“{m.group(0)}”")

    if _HIDDEN_RE.search(q):
        out.rank = "hidden_gems"
        _cite(out, "rank", "hidden_gems", "the query asks for overlooked work")
    elif _TREND_RE.search(q):
        out.rank = "trending"
        out.mode = "trend" if not out.wants_creators else out.mode
        _cite(out, "rank", "trending", "the query asks what is emerging")
    elif _BEST_RE.search(q):
        out.rank = "best"
        _cite(out, "rank", "best", "the query asks for the best")

    if _ENGAGEMENT_RE.search(q):
        out.min_engagement = 100
        _cite(out, "min_engagement", 100, "the query asks for popular work")

    if out.mode == "search":
        if out.techniques and not out.wants_prompt:
            out.mode = "technique"
        elif out.models and len(low.split()) <= 4:
            out.mode = "model"

    # keywords = what is left after the consumed vocabulary
    consumed = set()
    for pattern in (_MEDIA_RE, _IMAGE_RE, _WORKFLOW_RE, _PROMPT_RE, _CREATOR_RE,
                    _TREND_RE, _BEST_RE, _HIDDEN_RE, _ENGAGEMENT_RE, _NUM_DAYS_RE):
        for m in pattern.finditer(q):
            consumed.update(m.group(0).lower().split())
    for pat, _d, _l in _PERIODS:
        for m in pat.finditer(q):
            consumed.update(m.group(0).lower().split())
    stop = {"find", "me", "the", "a", "an", "of", "for", "from", "with", "that",
            "and", "or", "in", "on", "about", "some", "show", "get", "please",
            "currently", "being", "shared", "online", "are", "is", "to", "by",
            "social", "media", "posting", "posts", "post", "make", "making"}
    # words already represented as a model or technique are not keywords too
    for model in intent_model_words(out):
        stop.add(model)
    keywords = [w for w in re.findall(r"[\w'-]+", low)
                if w not in consumed and w not in stop and len(w) > 1]
    out.keywords = list(dict.fromkeys(keywords))[:12]
    return out


def intent_model_words(intent: "ResearchIntent") -> set[str]:
    """Every lowercase word already captured as a model or technique."""
    words: set[str] = set()
    for value in list(intent.models) + list(intent.techniques):
        words.update(re.split(r"[\s\-_]+", str(value).lower()))
    return {w for w in words if w}


def search_terms(intent: ResearchIntent, max_terms: int = 3) -> list[str]:
    """Concrete query strings to send to the sources (§28). Deterministic:
    the model/technique/keyword material recombined, most specific first."""
    terms: list[str] = []
    base = " ".join(intent.keywords[:5]).strip()
    if intent.models:
        for model in intent.models[:2]:
            bits = [model.lower()]
            if intent.wants_prompt:
                bits.append("prompt")
            if base:
                bits.append(base)
            terms.append(" ".join(dict.fromkeys(bits)))
    for tech in intent.techniques[:2]:
        pretty = tech.replace("-", " ").replace("_", " ")
        bits = [pretty]
        if intent.media_type == "video":
            bits.append("ai video")
        if intent.wants_prompt:
            bits.append("prompt")
        terms.append(" ".join(dict.fromkeys(bits)))
    if base:
        bits = [base]
        if intent.wants_prompt and "prompt" not in base:
            bits.append("prompt")
        terms.append(" ".join(bits))
    if not terms:
        # nothing specific survived: rebuild from the facets we DID understand
        bits = []
        if intent.media_type == "video":
            bits.append("ai video")
        elif intent.media_type == "image":
            bits.append("ai art")
        else:
            bits.append("ai art")
        if intent.wants_workflow:
            bits.append("workflow")
        elif intent.wants_prompt:
            bits.append("prompt")
        terms.append(" ".join(bits))
    seen, out = set(), []
    for t in terms:
        t = re.sub(r"\s+", " ", t).strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:max_terms]
