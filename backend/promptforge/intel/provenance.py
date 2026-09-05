"""Provenance primitives (D66): every important field carries {value, source,
confidence, evidence}. Sources rank so lower-trust writers (AI inference)
never overwrite what the source/metadata actually said."""
from __future__ import annotations

from typing import Any

# higher wins; equal rank → higher confidence wins
SOURCE_RANK = {"user": 6, "observed": 5, "metadata": 5, "extracted": 4,
               "inferred": 2, "ai": 1}
HIGH_TRUST = {"user", "observed", "metadata", "extracted"}


def assert_field(assertions: dict, field: str, value: Any, source: str,
                 confidence: float = 1.0, evidence: str | None = None,
                 overwrite: bool = False) -> bool:
    """Record a provenance-tagged value. Returns True when it became the
    canonical assertion for `field`; otherwise it is kept under _alternates."""
    if value in (None, "", [], {}):
        return False
    entry = {"value": value, "source": source,
             "confidence": round(float(confidence), 3), "evidence": evidence}
    cur = assertions.get(field)
    if cur and not overwrite:
        cur_rank = SOURCE_RANK.get(cur.get("source"), 0)
        new_rank = SOURCE_RANK.get(source, 0)
        loses = new_rank < cur_rank or (
            new_rank == cur_rank and entry["confidence"] <= cur.get("confidence", 0))
        if loses:
            assertions.setdefault("_alternates", {}).setdefault(field, []).append(entry)
            return False
        assertions.setdefault("_alternates", {}).setdefault(field, []).append(cur)
    assertions[field] = entry
    return True


def canonical(assertions: dict | None, field: str) -> Any:
    return ((assertions or {}).get(field) or {}).get("value")


def source_of(assertions: dict | None, field: str) -> str | None:
    return ((assertions or {}).get(field) or {}).get("source")


def is_high_confidence(assertions: dict | None, field: str,
                       min_conf: float = 0.7) -> bool:
    a = (assertions or {}).get(field) or {}
    return a.get("source") in HIGH_TRUST and float(a.get("confidence", 0)) >= min_conf


def evidence_list(assertions: dict | None) -> list[dict]:
    """Flat, UI-friendly list of {field, value, source, confidence, evidence}."""
    out = []
    for field, a in (assertions or {}).items():
        if field.startswith("_") or not isinstance(a, dict):
            continue
        out.append({"field": field, **a})
    return out
