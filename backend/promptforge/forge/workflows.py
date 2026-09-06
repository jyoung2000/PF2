"""Workflow engine (spec §9, §17): serialized node graphs executed through
the tool layer plus local ffmpeg operations. A run is a stepped state
machine (like film_jobs): `tick` advances every ready node, generation
nodes ride the existing queue, an approval node parks the run in
waiting_approval until a human approves, and every node's status/output/
error is persisted per tick — so runs survive restarts and the scheduler
can drive them."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..config import get_config
from ..models import Generation, Post, utcnow
from . import compiler, evaluate as evaluate_mod, tools
from .models import Workflow, WorkflowRun

TOOL_NODES = set(tools.TOOLS)
LOCAL_NODES = {"input", "prompt", "compile", "evaluate", "condition",
               "approval", "clip_video", "export"}
NODE_TYPES = TOOL_NODES | LOCAL_NODES

GENERATION_TIMEOUT_TICKS = 240   # scheduler ticks ≈ minutes


class WorkflowError(Exception):
    pass


# ------------------------------------------------------------- validation ---
def validate_graph(graph: dict) -> dict:
    """→ {ok, errors, warnings, order}. Errors block saving; warnings (e.g.
    a tool nobody declares yet) do not — availability is re-checked at run."""
    errors: list[str] = []
    warnings: list[str] = []
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    ids = [n.get("id") for n in nodes]
    if not nodes:
        errors.append("the workflow has no nodes")
    if len(set(ids)) != len(ids):
        errors.append("node ids must be unique")
    for n in nodes:
        if n.get("type") not in NODE_TYPES:
            errors.append(f"unknown node type '{n.get('type')}' ({n.get('id')})")
        if n.get("type") == "prompt" and not (n.get("config") or {}).get("text"):
            errors.append(f"prompt node '{n.get('id')}' needs config.text")
        if n.get("type") == "input" and not (n.get("config") or {}).get("key"):
            errors.append(f"input node '{n.get('id')}' needs config.key")
    known = set(ids)
    for e in edges:
        if e.get("from") not in known or e.get("to") not in known:
            errors.append(f"edge {e.get('from')}→{e.get('to')} references a missing node")
    # topological order (DAG check)
    incoming = {i: set() for i in known}
    for e in edges:
        if e.get("to") in incoming:
            incoming[e["to"]].add(e["from"])
    order, ready = [], [i for i in ids if not incoming.get(i)]
    pending = dict(incoming)
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for e in edges:
            if e.get("from") == nid and nid in pending.get(e["to"], set()):
                pending[e["to"]].discard(nid)
                if not pending[e["to"]]:
                    ready.append(e["to"])
    if len(order) != len(ids):
        errors.append("the graph has a cycle — workflows are DAGs")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "order": order}


def availability_report(s: Session, graph: dict) -> list[dict]:
    """Which nodes can actually execute right now (honest per-node)."""
    avail = {t["name"]: t for t in tools.availability(s)}
    report = []
    for n in graph.get("nodes") or []:
        t = n.get("type")
        if t in TOOL_NODES:
            a = avail.get(t, {})
            report.append({"id": n.get("id"), "type": t,
                           "supported": bool(a.get("supported")),
                           "reason": a.get("reason")})
        elif t == "clip_video":
            ok = shutil.which("ffmpeg") is not None
            report.append({"id": n.get("id"), "type": t, "supported": ok,
                           "reason": None if ok else "ffmpeg is not installed"})
        else:
            report.append({"id": n.get("id"), "type": t, "supported": True, "reason": None})
    return report


# --------------------------------------------------------------- execution ---
def _upstream(graph: dict, nid: str) -> list[dict]:
    return [e for e in (graph.get("edges") or []) if e.get("to") == nid]


def _gate_open(edge: dict, states: dict) -> bool:
    """Edges may carry when: "true"/"false" from a condition node."""
    src = states.get(edge["from"]) or {}
    if edge.get("when") in ("true", "false"):
        return str(bool((src.get("output") or {}).get("result"))).lower() == edge["when"]
    return True


def _incoming_output(graph: dict, states: dict, nid: str, want: str | None = None) -> dict:
    """Merged upstream outputs; `want` picks the first with that key."""
    merged: dict = {}
    for e in _upstream(graph, nid):
        out = (states.get(e["from"]) or {}).get("output") or {}
        if want and out.get(want) is not None:
            return out
        merged = {**merged, **out}
    return merged


def _media_path(s: Session, output: dict) -> str | None:
    if output.get("path"):
        return output["path"]
    if output.get("post_id"):
        post = s.get(Post, output["post_id"])
        if post and post.media_path:
            return str(get_config().data_dir / post.media_path)
    return None


def _exec_local(s: Session, run: WorkflowRun, node: dict, state: dict, graph: dict) -> dict:
    t, cfg = node["type"], node.get("config") or {}
    states = run.node_states or {}
    if t == "input":
        val = (run.inputs or {}).get(cfg["key"])
        if val is None:
            raise WorkflowError(f"run input '{cfg['key']}' was not provided")
        key = "path" if isinstance(val, str) and ("/" in val or "\\" in val) else "text"
        return {"status": "succeeded", "output": {key: val}}
    if t == "prompt":
        return {"status": "succeeded", "output": {"text": cfg["text"]}}
    if t == "compile":
        idea = _incoming_output(graph, states, node["id"], "text").get("text") or cfg.get("idea")
        if not idea:
            raise WorkflowError("compile node has no incoming text")
        pkg = compiler.compile_package(s, idea, family=cfg.get("family"),
                                       provider=cfg.get("provider"))
        if pkg.get("error"):
            raise WorkflowError(pkg["error"])
        return {"status": "succeeded",
                "output": {"text": pkg["optimized_prompt"], "package": pkg}}
    if t == "evaluate":
        inc = _incoming_output(graph, states, node["id"])
        pkg = inc.get("package") or {}
        findings = []
        prompt = inc.get("text") or pkg.get("optimized_prompt") or ""
        intent = pkg.get("intent") or {}
        for st in intent.get("styles", []):
            if st.lower() not in prompt.lower():
                findings.append(f"style '{st}' missing from the prompt")
        verdict = "pass" if not findings else "warn"
        return {"status": "succeeded",
                "output": {"result": verdict == "pass", "verdict": verdict,
                           "findings": findings, "text": prompt, "package": pkg}}
    if t == "condition":
        inc = _incoming_output(graph, states, node["id"])
        left = inc.get(cfg.get("key") or "verdict")
        result = str(left) == str(cfg.get("equals"))
        return {"status": "succeeded", "output": {"result": result, **inc}}
    if t == "approval":
        if state.get("approved"):
            inc = _incoming_output(graph, states, node["id"])
            return {"status": "succeeded", "output": inc}
        return {"status": "waiting_approval", "output": None}
    if t == "clip_video":
        inc = _incoming_output(graph, states, node["id"], "path")
        src = _media_path(s, inc)
        if not src or not Path(src).exists():
            raise WorkflowError("clip_video has no incoming video file")
        from ..film import footage
        cuts = footage.detect_cuts(Path(src), threshold=float(cfg.get("threshold", 0.35)))
        max_clip = float(cfg.get("max_clip_s", 15))
        n_clips = int(cfg.get("count", 3))
        out_dir = get_config().data_dir / "forge" / "clips"
        out_dir.mkdir(parents=True, exist_ok=True)
        bounds = [0.0] + cuts
        clips = []
        for i, start in enumerate(bounds[:n_clips]):
            dest = out_dir / f"run{run.id}-{node['id']}-{i}.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-i", src,
                            "-t", str(max_clip), "-c:v", "libx264", "-preset", "ultrafast",
                            "-pix_fmt", "yuv420p", "-an", str(dest)], check=True, timeout=600)
            clips.append(str(dest))
        return {"status": "succeeded",
                "output": {"clips": clips, "path": clips[0] if clips else None,
                           "cuts_detected": len(cuts)}}
    if t == "export":
        inc = _incoming_output(graph, states, node["id"])
        src = _media_path(s, inc)
        if not src:
            raise WorkflowError("export has nothing upstream to export")
        out_dir = get_config().data_dir / "forge" / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"run{run.id}-{Path(src).name}"
        shutil.copyfile(src, dest)
        return {"status": "succeeded", "output": {"path": str(dest), "exported": True}}
    raise WorkflowError(f"unhandled node type {t}")


def _exec_tool(s: Session, run: WorkflowRun, node: dict, state: dict, graph: dict) -> dict:
    """Tool nodes are two-phase: queue once, then watch the generation."""
    if state.get("job_id"):
        g = s.get(Generation, state["job_id"])
        if g is None or g.status == "failed":
            return {"status": "failed", "job_id": state["job_id"],
                    "error": (g.error if g else "generation row vanished")}
        if g.status == "succeeded":
            # echo the prompt so downstream nodes (image→video after an
            # approval, say) still know what this media is of
            return {"status": "succeeded", "job_id": g.id,
                    "output": {"post_id": g.output_post_id, "job_id": g.id,
                               "text": g.prompt or None,
                               "cost": g.cost_actual or g.cost_estimate}}
        ticks = int(state.get("ticks") or 0) + 1
        if ticks > GENERATION_TIMEOUT_TICKS:
            return {"status": "failed", "job_id": g.id, "error": "generation timed out"}
        return {"status": "running", "job_id": g.id, "ticks": ticks}
    cfg = node.get("config") or {}
    states = run.node_states or {}
    inc = _incoming_output(graph, states, node["id"])
    args: dict = {"family": cfg.get("family"), "provider": cfg.get("provider"),
                  "params": dict(cfg.get("params") or {})}
    spec = tools.TOOLS[node["type"]]
    if "prompt" in spec["required"]:
        args["prompt"] = cfg.get("prompt") or inc.get("text") or ""
    for media_key in ("image", "audio", "video"):
        if media_key in spec["required"]:
            args[media_key] = cfg.get(media_key) or _media_path(s, inc) or ""
    job = tools.invoke(s, node["type"], {k: v for k, v in args.items() if v not in (None, "")},
                       allow_fallback=bool(cfg.get("allow_fallback")))
    return {"status": "running", "job_id": job["job_id"]}


def tick_run(s: Session, run_id: int) -> dict:
    """Advance every ready node one step. Safe to call repeatedly (the
    scheduler does, every minute, for unfinished runs)."""
    run = s.get(WorkflowRun, run_id)
    if run is None:
        raise WorkflowError(f"run {run_id} not found")
    if run.status in ("succeeded", "failed", "cancelled"):
        return run_view(s, run)
    wf = s.get(Workflow, run.workflow_id)
    graph = wf.graph or {}
    order = validate_graph(graph)["order"]
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    states = dict(run.node_states or {})
    waiting = False

    for nid in order:
        node = nodes[nid]
        state = dict(states.get(nid) or {})
        if state.get("status") in ("succeeded", "skipped", "failed"):
            continue
        ups = _upstream(graph, nid)
        up_states = [states.get(e["from"]) or {} for e in ups]
        if any(u.get("status") == "failed" for u in up_states):
            states[nid] = {"status": "skipped", "error": "an upstream node failed"}
            continue
        if ups and all(u.get("status") in ("succeeded", "skipped") for u in up_states):
            open_edges = [e for e in ups if (states.get(e["from"]) or {}).get("status") == "succeeded"
                          and _gate_open(e, states)]
            if not open_edges:
                states[nid] = {"status": "skipped", "error": "no open branch led here"}
                continue
        elif ups:
            continue  # upstream still running
        try:
            if node["type"] in TOOL_NODES:
                new = _exec_tool(s, run, node, state, graph)
            else:
                new = _exec_local(s, run, node, state, graph)
        except (WorkflowError, tools.ToolError) as e:
            detail = getattr(e, "detail", None)
            new = {"status": "failed",
                   "error": detail["message"] if detail else str(e),
                   "next_action": (detail or {}).get("next_action")}
        states[nid] = {**state, **new}
        if new["status"] == "waiting_approval":
            waiting = True
        run.node_states = states
        flag_modified(run, "node_states")   # in-place JSON edits need the flag
        s.flush()

    statuses = [(states.get(n) or {}).get("status") for n in order]
    if any(st == "failed" for st in statuses):
        run.status = "failed"
        run.error = "; ".join(f"{n}: {(states[n] or {}).get('error')}"
                              for n in order if (states.get(n) or {}).get("status") == "failed")
        run.finished_at = utcnow()
    elif all(st in ("succeeded", "skipped") for st in statuses):
        run.status = "succeeded"
        run.finished_at = utcnow()
    elif waiting:
        run.status = "waiting_approval"
    else:
        run.status = "running"
    run.node_states = states
    flag_modified(run, "node_states")
    s.flush()
    return run_view(s, run)


def start_run(s: Session, workflow_id: int, inputs: dict | None = None) -> WorkflowRun:
    wf = s.get(Workflow, workflow_id)
    if wf is None:
        raise WorkflowError(f"workflow {workflow_id} not found")
    v = validate_graph(wf.graph or {})
    if not v["ok"]:
        raise WorkflowError("invalid workflow: " + "; ".join(v["errors"]))
    run = WorkflowRun(workflow_id=workflow_id, inputs=inputs or {}, status="running")
    s.add(run)
    s.flush()
    return run


def approve(s: Session, run_id: int, node_id: str) -> dict:
    run = s.get(WorkflowRun, run_id)
    if run is None:
        raise WorkflowError(f"run {run_id} not found")
    states = dict(run.node_states or {})
    state = dict(states.get(node_id) or {})
    if state.get("status") != "waiting_approval":
        raise WorkflowError(f"node '{node_id}' is not waiting for approval")
    state["approved"] = True
    state["status"] = "pending"
    states[node_id] = state
    run.node_states = states
    flag_modified(run, "node_states")
    run.status = "running"
    s.flush()
    return tick_run(s, run_id)


def run_view(s: Session, run: WorkflowRun) -> dict:
    return {"id": run.id, "workflow_id": run.workflow_id, "status": run.status,
            "inputs": run.inputs, "node_states": run.node_states, "error": run.error,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None}


def tick_unfinished(limit: int = 10) -> int:
    """Scheduler entry point: advance every live run."""
    from sqlalchemy import select

    from ..db import session_scope
    n = 0
    with session_scope() as s:
        ids = [i for (i,) in s.execute(select(WorkflowRun.id).where(
            WorkflowRun.status.in_(["running"])).limit(limit))]
    for rid in ids:
        with session_scope() as s:
            try:
                tick_run(s, rid)
                n += 1
            except WorkflowError:
                pass
    return n


# ---------------------------------------------------------------- templates ---
TEMPLATES: dict[str, dict] = {
    "idea_to_image": {
        "name": "Idea → optimized image",
        "description": "Compile a brief for the best model, generate, evaluate, export.",
        "graph": {"nodes": [
            {"id": "in", "type": "input", "config": {"key": "idea"}},
            {"id": "compile", "type": "compile", "config": {}},
            {"id": "gen", "type": "generate_image", "config": {}},
            {"id": "export", "type": "export", "config": {}},
        ], "edges": [{"from": "in", "to": "compile"}, {"from": "compile", "to": "gen"},
                     {"from": "gen", "to": "export"}]}},
    "image_to_video": {
        "name": "Still → motion",
        "description": "Generate a keyframe, get approval, animate it, export.",
        "graph": {"nodes": [
            {"id": "in", "type": "input", "config": {"key": "idea"}},
            {"id": "compile", "type": "compile", "config": {}},
            {"id": "frame", "type": "generate_image", "config": {}},
            {"id": "ok", "type": "approval", "config": {"label": "Approve the keyframe"}},
            {"id": "motion", "type": "image_to_video", "config": {}},
            {"id": "export", "type": "export", "config": {}},
        ], "edges": [{"from": "in", "to": "compile"}, {"from": "compile", "to": "frame"},
                     {"from": "frame", "to": "ok"}, {"from": "ok", "to": "motion"},
                     {"from": "motion", "to": "export"}]}},
    "shorts_pipeline": {
        "name": "Long video → shorts",
        "description": "Transcribe (needs a provider that declares transcription), "
                       "cut highlight clips at scene changes, export. The transcription "
                       "node reports honestly when no provider declares it.",
        "graph": {"nodes": [
            {"id": "in", "type": "input", "config": {"key": "video"}},
            {"id": "stt", "type": "transcribe_audio", "config": {}},
            {"id": "clips", "type": "clip_video", "config": {"count": 3, "max_clip_s": 15}},
            {"id": "export", "type": "export", "config": {}},
        ], "edges": [{"from": "in", "to": "stt"}, {"from": "in", "to": "clips"},
                     {"from": "clips", "to": "export"}]}},
}


def instantiate_template(s: Session, key: str) -> Workflow:
    t = TEMPLATES.get(key)
    if t is None:
        raise WorkflowError(f"unknown template '{key}' — one of {', '.join(TEMPLATES)}")
    wf = Workflow(name=t["name"], description=t["description"],
                  graph=t["graph"], is_template=False)
    s.add(wf)
    s.flush()
    return wf
