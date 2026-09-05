"""ContinuityService (spec AF, AG): deterministic, explainable checks between
adjacent shots — character/outfit/location/lighting/style/prop/camera/timing.
Every check here is implementable from stored structure; visual checks that
would need a model are NOT faked. Modes: flexible (everything informational),
balanced (warnings), strict (canonical violations block generation until the
shot carries an explicit `continuity_override`)."""
from __future__ import annotations

import statistics

from sqlalchemy.orm import Session

from . import events
from . import projects as proj_svc
from . import shotctx
from .models import FilmProject, FilmShot

CANONICAL_KINDS = {"character_version", "outfit_change", "location_mismatch", "style_change",
                   "prop_disappearance"}
_SEV = {"info": 0, "warn": 1, "block": 2}


def _w(kind: str, severity: str, message: str, shot_ids: list[int], heuristic: bool = False,
       fix: str | None = None) -> dict:
    return {"kind": kind, "severity": severity, "message": message, "shot_ids": shot_ids,
            "heuristic": heuristic, "fix": fix}


def _by_type(ctx: dict, t: str) -> dict[int, dict]:
    return {c["asset_id"]: c for c in ctx["assets"] if c["type"] == t and c.get("present", True)}


def check_pair(a: dict, b: dict, same_scene: bool) -> list[dict]:
    out: list[dict] = []
    la, lb = a["shot_id"], b["shot_id"]
    # character version drift
    ca, cb = _by_type(a, "character"), _by_type(b, "character")
    for aid in ca.keys() & cb.keys():
        if ca[aid]["version_id"] != cb[aid]["version_id"]:
            out.append(_w("character_version", "warn",
                          f"{ca[aid]['name']} changes from v{ca[aid]['version']} to v{cb[aid]['version']} "
                          f"between shots — identity references differ.", [la, lb],
                          fix="Pin the same version on both shots (Assets → Update selected shots)."))
    if same_scene:
        oa, ob = _by_type(a, "outfit"), _by_type(b, "outfit")
        if oa and ob and set(oa) != set(ob):
            out.append(_w("outfit_change", "warn",
                          f"Outfit changes within the scene: {', '.join(x['name'] for x in oa.values())} → "
                          f"{', '.join(x['name'] for x in ob.values())}.", [la, lb]))
        loc_a, loc_b = _by_type(a, "location"), _by_type(b, "location")
        if loc_a and loc_b and set(loc_a) != set(loc_b):
            out.append(_w("location_mismatch", "warn",
                          f"Location changes within the scene: {next(iter(loc_a.values()))['name']} → "
                          f"{next(iter(loc_b.values()))['name']}.", [la, lb]))
        elif (not loc_a and not loc_b and a["scene"].get("location_name") and b["scene"].get("location_name")
              and a["scene"]["location_name"] != b["scene"]["location_name"]):
            out.append(_w("location_mismatch", "warn", "Location name differs within the scene.", [la, lb]))
        ea, eb = a.get("environment") or {}, b.get("environment") or {}
        for key, label in (("time_of_day", "Time of day"), ("weather", "Weather")):
            if ea.get(key) and eb.get(key) and ea[key] != eb[key]:
                out.append(_w("lighting_jump", "warn", f"{label} jumps {ea[key]} → {eb[key]} within the scene.",
                              [la, lb]))
        lta, ltb = a.get("lighting") or {}, b.get("lighting") or {}
        if lta.get("mood") and ltb.get("mood") and lta["mood"] != ltb["mood"]:
            out.append(_w("lighting_jump", "warn",
                          f"Lighting mood changes {lta['mood']} → {ltb['mood']} without a scene change.",
                          [la, lb], heuristic=True))
        cam_a, cam_b = a.get("camera") or {}, b.get("camera") or {}
        if (cam_a.get("shot_size") and cam_a.get("shot_size") == cam_b.get("shot_size")
                and cam_a.get("angle") == cam_b.get("angle")
                and abs(float(cam_a.get("lens_mm") or 0) - float(cam_b.get("lens_mm") or 0)) < 1
                and set(ca) == set(cb) and ca):
            out.append(_w("jump_cut", "info",
                          "Same framing back-to-back on the same subject (jump cut). Intentional?",
                          [la, lb], heuristic=True, fix="Change shot size or angle by at least one step."))
    sa, sb = _by_type(a, "style"), _by_type(b, "style")
    if sa and sb and set(sa) != set(sb):
        out.append(_w("style_change", "warn",
                      f"Style bible changes: {next(iter(sa.values()))['name']} → {next(iter(sb.values()))['name']}.",
                      [la, lb]))
    return out


def check_sequence(ctxs: list[tuple[dict, FilmShot, int]]) -> list[dict]:
    """Checks needing more than two shots: prop disappearance inside a scene
    and timing anomalies."""
    out: list[dict] = []
    by_scene: dict[int, list[tuple[dict, FilmShot]]] = {}
    for ctx, sh, scene_id in ctxs:
        by_scene.setdefault(scene_id, []).append((ctx, sh))
    for scene_id, items in by_scene.items():
        props = [(_by_type(c, "prop"), sh) for c, sh in items]
        for i in range(1, len(props) - 1):
            prev, cur, nxt = props[i - 1][0], props[i][0], props[i + 1][0]
            for pid in (set(prev) & set(nxt)) - set(cur):
                out.append(_w("prop_disappearance", "warn",
                              f"{prev[pid]['name']} vanishes in shot {items[i][1].position + 1} and returns "
                              "in the next — impossible prop continuity.",
                              [props[i - 1][1].id, props[i][1].id, props[i + 1][1].id]))
        durations = [float(sh.duration_s or 0) for _, sh in items]
        if len(durations) >= 3:
            med = statistics.median(durations)
            for c, sh in items:
                d = float(sh.duration_s or 0)
                if d < 0.5:
                    out.append(_w("timing", "info", f"Shot {sh.position + 1} is only {d}s long.", [sh.id]))
                elif med and d > 3 * med:
                    out.append(_w("timing", "info",
                                  f"Shot {sh.position + 1} ({d}s) is over 3× the scene's median ({med}s).",
                                  [sh.id], heuristic=True))
    return out


def apply_mode(warnings: list[dict], mode: str, overrides: dict[int, bool]) -> list[dict]:
    """flexible ⇒ info only; balanced ⇒ as computed; strict ⇒ canonical
    kinds become blocking unless every affected shot carries an override."""
    out = []
    for w in warnings:
        w = dict(w)
        if mode == "flexible":
            w["severity"] = "info"
        elif mode == "strict" and w["kind"] in CANONICAL_KINDS and w["severity"] != "info":
            if all(overrides.get(sid) for sid in w["shot_ids"]):
                w["severity"] = "info"
                w["overridden"] = True
            else:
                w["severity"] = "block"
        out.append(w)
    return out


def validate_project(s: Session, project: FilmProject, log: bool = True) -> dict:
    settings = proj_svc.merge_settings(project.settings, None)
    mode = settings.get("continuity_mode", "balanced")
    ordered = proj_svc.ordered_shots(s, project.id)
    ctxs = [(shotctx.effective_context(s, sh, sc, project), sh, sc.id) for sh, sc in ordered]
    warnings: list[dict] = []
    for i in range(1, len(ctxs)):
        (a, sha, sca), (b, shb, scb) = ctxs[i - 1], ctxs[i]
        warnings += check_pair(a, b, sca == scb)
    warnings += check_sequence(ctxs)
    overrides = {sh.id: bool((sh.overrides or {}).get("continuity_override")) for _, sh, _ in ctxs}
    warnings = apply_mode(warnings, mode, overrides)
    by_shot: dict[int, list[dict]] = {sh.id: [] for _, sh, _ in ctxs}
    for w in warnings:
        for sid in w["shot_ids"]:
            by_shot.setdefault(sid, []).append(w)
    for _, sh, _ in ctxs:
        sh.warnings = by_shot.get(sh.id, [])
    s.flush()
    counts = {k: sum(1 for w in warnings if w["severity"] == k) for k in ("info", "warn", "block")}
    if log:
        events.log(s, project.id, f"Continuity check: {counts['block']} blocking, {counts['warn']} warnings",
                   kind="qa", stage="storyboard", actor="system", entity=("project", project.id),
                   data={"mode": mode, "counts": counts})
    return {"mode": mode, "counts": counts, "blocking": counts["block"] > 0,
            "warnings": warnings, "by_shot": {str(k): v for k, v in by_shot.items()}}


def can_generate(s: Session, shot: FilmShot) -> tuple[bool, list[str]]:
    """Strict mode gate: blocking warnings on this shot stop generation."""
    blocks = [w["message"] for w in (shot.warnings or []) if w.get("severity") == "block"]
    return (not blocks), blocks
