"""Highlight selection for long-video → shorts (Phase 2).

Concept adopted from AI-Youtube-Shorts-Generator's `highlights.py`: rank
candidate segments, then suppress overlapping picks so three "best moments"
are not three cuts of the same thirty seconds. That repository ranks with an
LLM over a transcript; here ranking is deterministic by default (scene-cut
structure and segment length) and an LLM only refines when one is configured
and a transcript exists — so the node works with no provider at all.

No upstream code was copied; the algorithm is re-implemented against our own
ffmpeg helpers.
"""
from __future__ import annotations

import json
import re

TARGET_S = 15.0
MIN_S = 3.0


def score_segments(segments: list[dict], target_s: float = TARGET_S) -> list[dict]:
    """Deterministic prior: prefer segments close to the target length, and
    prefer self-contained ones (a whole scene between two cuts)."""
    scored = []
    for seg in segments:
        dur = float(seg.get("duration_s") or 0)
        if dur < MIN_S:
            continue
        # 1.0 at the target length, falling off either side
        fit = max(0.0, 1.0 - abs(dur - target_s) / max(target_s, 1.0))
        whole = 1.0 if seg.get("scene_bounded", True) else 0.6
        score = round(100 * (0.7 * fit + 0.3 * whole))
        scored.append({**seg, "score": score,
                       "reason": f"{dur:.1f}s segment, {'scene-bounded' if whole == 1.0 else 'mid-scene'}"})
    scored.sort(key=lambda x: (-x["score"], x["start_s"]))
    return scored


def suppress_overlaps(ranked: list[dict], count: int,
                      max_overlap: float = 0.25) -> list[dict]:
    """Greedy non-maximum suppression over time — the upstream idea that keeps
    the top picks from being the same moment three times."""
    kept: list[dict] = []
    for cand in ranked:
        a0, a1 = float(cand["start_s"]), float(cand["end_s"])
        span = max(a1 - a0, 1e-6)
        clash = False
        for k in kept:
            overlap = min(a1, float(k["end_s"])) - max(a0, float(k["start_s"]))
            if overlap > 0 and overlap / span > max_overlap:
                clash = True
                break
        if not clash:
            kept.append(cand)
        if len(kept) >= count:
            break
    return kept


def segments_from_cuts(cuts: list[float], duration: float,
                       max_clip_s: float = TARGET_S) -> list[dict]:
    """Scene-cut times → candidate segments, trimmed to the clip length."""
    bounds = [0.0] + [c for c in cuts if 0 < c < duration] + [duration]
    out = []
    for i in range(len(bounds) - 1):
        start, end = bounds[i], min(bounds[i] + max_clip_s, bounds[i + 1])
        if end - start < MIN_S:
            continue
        out.append({"start_s": round(start, 2), "end_s": round(end, 2),
                    "duration_s": round(end - start, 2),
                    "scene_bounded": (bounds[i + 1] - bounds[i]) <= max_clip_s + 0.5})
    return out


LLM_SYSTEM = (
    "You rank moments in a transcript for short-form video. Reply with JSON "
    "only: {\"highlights\": [{\"start_time\": float, \"end_time\": float, "
    "\"score\": 0-100, \"title\": str, \"reason\": str}]}. Use only timestamps "
    "present in the transcript.")


def refine_with_llm(segments: list[dict], transcript: str,
                    count: int) -> tuple[list[dict], str | None]:
    """Optional: re-score with the configured LLM. Returns (segments, note);
    on any failure the deterministic ranking is kept and the note says why."""
    if not transcript.strip():
        return segments, "no transcript available — ranked structurally"
    try:
        from ..llm.client import run_llm
        raw = run_llm("forge_highlights", LLM_SYSTEM,
                      f"Pick the {count} strongest moments.\n\nTranscript:\n{transcript[:8000]}")
        match = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(match.group(0)) if match else {}
        picks = data.get("highlights") or []
        if not picks:
            return segments, "the model returned no usable highlights — kept the structural ranking"
        out = []
        for p in picks[:count]:
            try:
                start, end = float(p["start_time"]), float(p["end_time"])
            except (KeyError, TypeError, ValueError):
                continue
            if end <= start:
                continue
            out.append({"start_s": round(start, 2), "end_s": round(end, 2),
                        "duration_s": round(end - start, 2),
                        "score": max(0, min(100, int(p.get("score") or 50))),
                        "title": str(p.get("title") or "")[:120],
                        "reason": str(p.get("reason") or "ranked by the model")[:200],
                        "scene_bounded": False})
        return (out or segments), (None if out else "kept the structural ranking")
    except Exception as e:
        return segments, f"LLM ranking unavailable ({type(e).__name__}) — ranked structurally"


def even_chunks(duration: float, count: int, max_clip_s: float) -> list[dict]:
    """Fallback for sources too short to have segments above MIN_S — better a
    sensible even split than no clips at all."""
    if duration <= 0:
        return []
    span = min(max_clip_s, duration / max(1, count))
    out = []
    for i in range(count):
        start = round(i * span, 2)
        end = round(min(start + span, duration), 2)
        if end - start <= 0.05:
            break
        out.append({"start_s": start, "end_s": end,
                    "duration_s": round(end - start, 2), "scene_bounded": False,
                    "score": 50, "reason": "even split — the source is shorter "
                                           "than one highlight"})
    return out


def pick(cuts: list[float], duration: float, count: int = 3,
         max_clip_s: float = TARGET_S, transcript: str = "",
         use_llm: bool = False) -> dict:
    """→ {highlights, basis, note}."""
    segments = segments_from_cuts(cuts, duration, max_clip_s)
    ranked = score_segments(segments, target_s=min(max_clip_s, TARGET_S))
    note = None
    basis = "structure"
    if not ranked:
        ranked = even_chunks(duration, count, max_clip_s)
        basis = "even-split"
        note = ("no scene segment reached the minimum highlight length — "
                "split the source evenly instead")
    if use_llm:
        ranked, note = refine_with_llm(ranked, transcript, count)
        basis = "llm" if note is None else "structure"
    return {"highlights": suppress_overlaps(ranked, count), "basis": basis, "note": note}
