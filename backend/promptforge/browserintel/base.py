"""BrowserIntelligence facade (Inspiration 2.0, I8/spec §5–§9, §97).

PF2 speaks to ONE abstraction; the engines behind it are interchangeable and
optional:

  Level 0/1  plain HTTP / deterministic adapters (outside this module)
  Level 1    playwright_engine — replay of cached, validated workflows
  Level 2/3  stagehand_engine — observe/act/extract on a real page (AI)
  Level 4    browseruse_engine — short autonomous research runs (AI)

`auto` mode always tries the cheapest thing that can work: an active cached
workflow replays deterministically; only when there is none (or replay
breaks) do the AI engines run — inside the domain allowlist, the read-only
policy, and a daily AI/browser budget. Every engine can be missing or
disabled; callers get honest EngineUnavailable/BudgetExhausted errors (or a
degraded no-op) rather than crashes."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import settings_store
from ..db import session_scope
from ..logbus import bus
from . import diagnostics, playwright_engine, policy, workflows

ENGINES = ("playwright", "stagehand", "browser_use")
MODES = ("auto", "deterministic", "stagehand", "browser_use", "playwright", "off")


class BudgetExhausted(RuntimeError):
    pass


class EngineUnavailable(RuntimeError):
    pass


# ------------------------------------------------------------------ budget --
def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_usage(s: Session) -> dict:
    usage = settings_store.get(s, "browser_intel_usage", None) or {}
    if usage.get("date") != _today():
        return {"date": _today(), "ai_calls": 0, "browser_seconds": 0.0, "by_purpose": {}}
    return usage


def check_ai_budget(s: Session) -> None:
    budget = int(settings_store.get(s, "browser_intel_daily_ai_calls") or 0)
    if budget <= 0:
        return
    if int(get_usage(s).get("ai_calls", 0)) >= budget:
        raise BudgetExhausted(
            f"Daily browser-AI budget reached ({budget} calls) — raise it under "
            "Settings → Inspiration → Browser intelligence, or wait for the UTC reset.")
    max_minutes = float(settings_store.get(s, "browser_intel_max_minutes") or 0)
    if max_minutes > 0 and float(get_usage(s).get("browser_seconds", 0)) >= max_minutes * 60:
        raise BudgetExhausted(
            f"Daily AI-browser time budget reached ({max_minutes:.0f} min).")


def bump_usage(purpose: str, ai_calls: int = 1, seconds: float = 0.0) -> None:
    with session_scope() as s:
        usage = get_usage(s)
        usage["ai_calls"] = int(usage.get("ai_calls", 0)) + ai_calls
        usage["browser_seconds"] = round(float(usage.get("browser_seconds", 0)) + seconds, 1)
        usage.setdefault("by_purpose", {})
        usage["by_purpose"][purpose] = int(usage["by_purpose"].get(purpose, 0)) + max(1, ai_calls)
        settings_store.put(s, "browser_intel_usage", usage)


# ------------------------------------------------------------ availability --
def _engine_module(name: str):
    if name == "playwright":
        return playwright_engine
    if name == "stagehand":
        from . import stagehand_engine
        return stagehand_engine
    if name == "browser_use":
        from . import browseruse_engine
        return browseruse_engine
    raise ValueError(name)


def availability() -> dict:
    """Truthful per-engine state for /api/health and the settings card."""
    with session_scope() as s:
        mode = str(settings_store.get(s, "browser_intel_mode") or "auto")
        flags = {"stagehand": bool(settings_store.get(s, "browser_intel_stagehand_enabled")),
                 "browser_use": bool(settings_store.get(s, "browser_intel_browser_use_enabled")),
                 "playwright": True}
    out: dict = {"mode": mode if mode in MODES else "auto", "engines": {}}
    for name in ENGINES:
        entry = {"enabled": flags.get(name, True), "available": False, "detail": None}
        try:
            mod = _engine_module(name)
            entry["available"] = bool(mod.available())
            if not entry["available"]:
                entry["detail"] = getattr(mod, "unavailable_reason", lambda: "not installed")()
        except ImportError as e:
            entry["detail"] = f"not installed ({e.name})"
        except Exception as e:  # noqa: BLE001 — availability must never raise
            entry["detail"] = str(e)[:200]
        out["engines"][name] = entry
    return out


def _enabled(s: Session, engine: str) -> bool:
    mode = str(settings_store.get(s, "browser_intel_mode") or "auto")
    if mode == "off":
        return False
    if mode == "deterministic":
        return engine == "playwright"
    if mode in ENGINES:            # a specific engine pinned
        return engine == mode or engine == "playwright"
    if engine == "stagehand":
        return bool(settings_store.get(s, "browser_intel_stagehand_enabled"))
    if engine == "browser_use":
        return bool(settings_store.get(s, "browser_intel_browser_use_enabled"))
    return True


def _ai_engines(s: Session) -> list[str]:
    """AI engines to try, best-first, honouring mode/flags/installation."""
    if not bool(settings_store.get(s, "browser_intel_ai_discovery")):
        return []
    order = []
    for name in ("stagehand", "browser_use"):
        if _enabled(s, name):
            try:
                if _engine_module(name).available():
                    order.append(name)
            except Exception:  # noqa: BLE001
                continue
    return order


# ------------------------------------------------------------- operations --
def run_workflow(source: str, task: str, params: dict | None = None,
                 repair: bool = True) -> dict:
    """The main entry: replay the cached workflow; when replay breaks and AI
    repair is allowed/available, repair → verify → replay the new version.
    Raises EngineUnavailable when there's no workflow and no way to make one."""
    with session_scope() as s:
        wf = workflows.get_active(s, source, task)
        wf_id = wf.id if wf else None
    storage = playwright_engine.session_path(source)
    if wf_id is not None:
        try:
            return workflows.replay(wf_id, params, storage)
        except policy.PolicyViolation:
            raise
        except Exception as e:
            bus.warn("browserintel", f"{source}/{task}: replay failed ({e}) — "
                                     f"{'trying repair' if repair else 'repair disabled'}")
            if not repair:
                raise
            repaired = repair_workflow(source, task, params)
            return workflows.replay(repaired["id"], params, storage)
    raise EngineUnavailable(
        f"No cached workflow for {source}/{task}. Discover one with "
        "discover_workflow() (needs an AI engine + budget) or save one by hand.")


def repair_workflow(source: str, task: str, params: dict | None = None) -> dict:
    """AI repair: an engine observes the live page and proposes a fresh,
    policy-validated action list; ONE successful verification replay is
    required before the new version replaces the old."""
    from sqlalchemy import select

    from ..models import BrowserWorkflow
    with session_scope() as s:
        wf = workflows.get_active(s, source, task)
        broken = wf or s.execute(
            select(BrowserWorkflow).where(BrowserWorkflow.source == source,
                                          BrowserWorkflow.task == task)
            .order_by(BrowserWorkflow.version.desc())).scalars().first()
        if broken is None:
            raise EngineUnavailable(f"No workflow for {source}/{task} to repair.")
        schema = dict(broken.schema or {})
        old_actions = list(broken.actions or [])
        instruction = (broken.notes or f"{task} on {source}")
        engines = _ai_engines(s)
        check_ai_budget(s)
    if not engines:
        raise EngineUnavailable(
            "Workflow repair needs an AI browser engine (Stagehand or Browser "
            "Use) enabled and installed — the workflow stays marked "
            "'needs repair' until then.")
    start_url = next((a.get("url") for a in old_actions if a.get("op") == "goto"), None)
    if not start_url:
        raise EngineUnavailable(f"{source}/{task}: workflow has no start URL to observe.")
    storage = playwright_engine.session_path(source)
    last_err: Exception | None = None
    for engine in engines:
        watch = diagnostics.Stopwatch()
        try:
            mod = _engine_module(engine)
            actions = mod.propose_workflow(start_url=start_url, task=instruction,
                                           schema=schema, params=params or {},
                                           storage_state=storage)
            bump_usage(f"repair:{source}/{task}", ai_calls=1, seconds=watch.seconds)
            policy.check_workflow_actions(actions)
            verify = playwright_engine.run_actions(actions, params, storage)
            if not verify.get("rows") and any(a.get("op") == "extract" for a in actions):
                raise RuntimeError("proposed workflow extracted nothing")
            with session_scope() as s:
                wf = workflows.save_version(s, source, task, actions, engine,
                                            schema=schema, notes=instruction, repaired=True)
                out = workflows.workflow_dict(wf)
            bus.info("browserintel", f"{source}/{task}: workflow repaired automatically ({engine})")
            return out
        except (BudgetExhausted, policy.PolicyViolation):
            raise
        except Exception as e:  # noqa: BLE001 — try the next engine
            last_err = e
            diagnostics.record(source, task, step=f"repair:{engine}", error=str(e))
    raise EngineUnavailable(f"Workflow repair failed on every engine: {last_err}")


def discover_workflow(source: str, task: str, start_url: str, instruction: str,
                      schema: dict | None = None, params: dict | None = None) -> dict:
    """First-time AI discovery of a workflow for a permitted site (§78)."""
    policy.check_url(start_url)
    with session_scope() as s:
        engines = _ai_engines(s)
        check_ai_budget(s)
    if not engines:
        raise EngineUnavailable("AI-assisted discovery is disabled or no AI engine is installed.")
    storage = playwright_engine.session_path(source)
    last_err: Exception | None = None
    for engine in engines:
        watch = diagnostics.Stopwatch()
        try:
            mod = _engine_module(engine)
            actions = mod.propose_workflow(start_url=start_url, task=instruction,
                                           schema=schema or {}, params=params or {},
                                           storage_state=storage)
            bump_usage(f"discover:{source}/{task}", ai_calls=1, seconds=watch.seconds)
            policy.check_workflow_actions(actions)
            verify = playwright_engine.run_actions(actions, params, storage)
            if not verify.get("rows") and any(a.get("op") == "extract" for a in actions):
                raise RuntimeError("discovered workflow extracted nothing")
            with session_scope() as s:
                wf = workflows.save_version(s, source, task, actions, engine,
                                            schema=schema, notes=instruction)
                return workflows.workflow_dict(wf)
        except (BudgetExhausted, policy.PolicyViolation):
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            diagnostics.record(source, task, step=f"discover:{engine}", error=str(e))
    raise EngineUnavailable(f"Workflow discovery failed on every engine: {last_err}")


def ai_extract(url: str, instruction: str, schema: dict,
               source: str | None = None, purpose: str = "extract") -> dict:
    """One-off AI extraction from a permitted page (Level 3): used only when
    deterministic parsing came up empty. Output is schema-shaped data and is
    labelled ai_extraction by callers — never silently merged as observed."""
    policy.check_url(url)
    with session_scope() as s:
        engines = _ai_engines(s)
        check_ai_budget(s)
    if not engines:
        raise EngineUnavailable("No AI browser engine is enabled/installed.")
    storage = playwright_engine.session_path(source) if source else None
    last_err: Exception | None = None
    for engine in engines:
        watch = diagnostics.Stopwatch()
        try:
            mod = _engine_module(engine)
            data = mod.extract(url=url, instruction=instruction, schema=schema,
                               storage_state=storage)
            bump_usage(f"{purpose}:{source or 'adhoc'}", ai_calls=1, seconds=watch.seconds)
            return {"engine": engine, "data": data}
        except (BudgetExhausted, policy.PolicyViolation):
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            diagnostics.record(source or "adhoc", purpose, step=f"extract:{engine}",
                               error=str(e), extra={"url": url})
    raise EngineUnavailable(f"AI extraction failed on every engine: {last_err}")
