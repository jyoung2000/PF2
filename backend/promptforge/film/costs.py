"""Cost control (spec S): estimate → reserve → execute → reconcile with
project budget modes observe | warn | approve | cap. Figures are sums of
take estimates/actuals (catalog-based); nothing is ever invented — an
unknown price is reported as unknown."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events
from . import projects as proj_svc
from .models import FilmProject, FilmScene, FilmShot, FilmTake


class BudgetBlocked(ValueError):
    def __init__(self, message: str, check: dict):
        super().__init__(message)
        self.check = check


def spend(s: Session, project: FilmProject) -> dict:
    takes = list(s.execute(select(FilmTake).where(FilmTake.project_id == project.id)).scalars())
    shots = {sh.id: sh for sh in s.execute(select(FilmShot).where(FilmShot.project_id == project.id)).scalars()}
    scenes = {sc.id: sc for sc in s.execute(select(FilmScene).where(FilmScene.project_id == project.id)).scalars()}
    out = {"estimated_usd": 0.0, "actual_usd": 0.0, "reserved_usd": 0.0, "spent_usd": 0.0,
           "unknown_takes": 0, "by_scene": {}, "by_shot": {}, "by_provider": {}}
    for t in takes:
        est = t.cost_estimate
        if t.status in ("failed", "cancelled") and t.cost_actual is None:
            continue
        if est is None and t.cost_actual is None:
            if t.status not in ("imported",):
                out["unknown_takes"] += 1
            continue
        if t.status in ("queued", "running"):
            out["reserved_usd"] += float(est or 0)
        elif t.status == "succeeded":
            actual = float(t.cost_actual if t.cost_actual is not None else (est or 0))
            out["spent_usd"] += actual
            out["actual_usd"] += float(t.cost_actual or 0)
        out["estimated_usd"] += float(est or 0)
        amount = float(t.cost_actual if t.cost_actual is not None else (est or 0))
        sh = shots.get(t.shot_id)
        if sh is not None:
            out["by_shot"][str(sh.id)] = round(out["by_shot"].get(str(sh.id), 0.0) + amount, 4)
            sc = scenes.get(sh.scene_id)
            if sc is not None:
                out["by_scene"][str(sc.id)] = round(out["by_scene"].get(str(sc.id), 0.0) + amount, 4)
        if t.provider:
            out["by_provider"][t.provider] = round(out["by_provider"].get(t.provider, 0.0) + amount, 4)
    for k in ("estimated_usd", "actual_usd", "reserved_usd", "spent_usd"):
        out[k] = round(out[k], 4)
    budget = proj_svc.merge_settings(project.settings, None).get("budget") or {}
    cap = budget.get("cap_usd")
    out["budget"] = budget
    out["committed_usd"] = round(out["spent_usd"] + out["reserved_usd"], 4)
    out["remaining_usd"] = (round(float(cap) - out["committed_usd"], 4) if cap not in (None, "", 0) else None)
    return out


def check(s: Session, project: FilmProject, amount_usd: float | None, approve: bool = False) -> dict:
    """Can `amount_usd` more be committed right now under the project's
    budget mode? Never raises — the caller decides."""
    sp = spend(s, project)
    budget = sp["budget"]
    mode = budget.get("mode", "warn")
    threshold = budget.get("threshold_usd")
    cap = budget.get("cap_usd")
    amount = float(amount_usd or 0)
    projected = round(sp["committed_usd"] + amount, 4)
    out = {"mode": mode, "amount_usd": amount, "projected_usd": projected, "committed_usd": sp["committed_usd"],
           "threshold_usd": threshold, "cap_usd": cap, "remaining_usd": sp["remaining_usd"],
           "allowed": True, "requires_approval": False, "warning": None, "reason": None,
           "unknown_price": amount_usd is None}
    if amount_usd is None and mode in ("approve", "cap"):
        out["requires_approval"] = not approve
        out["allowed"] = approve
        out["reason"] = "Price unknown for this provider/mode — approve explicitly to run it."
        return out
    if mode == "observe":
        return out
    over_threshold = threshold not in (None, "") and projected > float(threshold)
    if mode == "warn":
        if over_threshold:
            out["warning"] = f"Projected spend ${projected:.2f} exceeds the warn threshold ${float(threshold):.2f}."
        return out
    if mode == "approve":
        if over_threshold and not approve:
            out["allowed"] = False
            out["requires_approval"] = True
            out["reason"] = (f"Projected spend ${projected:.2f} exceeds ${float(threshold):.2f} — "
                             "approve this cost to continue.")
        return out
    if mode == "cap":
        if cap not in (None, "") and projected > float(cap):
            out["allowed"] = False
            out["reason"] = (f"Hard cap ${float(cap):.2f} would be exceeded (projected ${projected:.2f}). "
                             "Raise the cap in project settings to continue.")
        elif over_threshold and not approve:
            out["allowed"] = False
            out["requires_approval"] = True
            out["reason"] = f"Projected spend ${projected:.2f} exceeds ${float(threshold):.2f} — approve to continue."
        return out
    return out


def reserve(s: Session, take: FilmTake, check_result: dict | None = None) -> None:
    events.log(s, take.project_id, f"Reserved ${float(take.cost_estimate or 0):.3f} for take {take.number}",
               kind="cost", stage="shot_generation", actor="system", entity=("take", take.id),
               data={"estimate_usd": take.cost_estimate, "provider": take.provider,
                     "model_family": take.model_family, "check": check_result or {}})


def reconcile(s: Session, take: FilmTake, actual_usd: float | None) -> None:
    take.cost_actual = actual_usd if actual_usd is not None else take.cost_estimate
    s.flush()
    events.log(s, take.project_id,
               f"Take {take.number}: actual ${float(take.cost_actual or 0):.3f} (estimated ${float(take.cost_estimate or 0):.3f})",
               kind="cost", stage="shot_generation", actor="system", entity=("take", take.id),
               data={"estimate_usd": take.cost_estimate, "actual_usd": take.cost_actual,
                     "basis": "provider" if actual_usd is not None else "estimate"})
