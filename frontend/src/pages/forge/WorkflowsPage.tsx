// Workflows (spec §9, §17): a node-graph editor over the serialized JSON the
// engine executes. Auto-layout by topology, click-to-connect, per-node
// availability badges, runs with live states and human approval.
import { useEffect, useRef, useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { EmptyState, Modal, SkeletonGrid, Spinner } from '../../components/Primitives'
import { forge, layoutColumns, WfGraph, WfNode, WorkflowRunView, WorkflowView } from '../../lib/forge'
import { useFetch } from '../../lib/hooks'
import { toastError, toastSuccess } from '../../lib/toast'

const NODE_TYPES = [
  'input', 'prompt', 'compile', 'generate_image', 'edit_image', 'generate_video',
  'image_to_video', 'upscale_image', 'remove_background', 'generate_speech',
  'transcribe_audio', 'clip_video', 'evaluate', 'condition', 'approval', 'export',
]
const NODE_W = 190
const NODE_H = 76
const GAP_X = 70
const GAP_Y = 28

function nodePositions(graph: WfGraph): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>()
  layoutColumns(graph).forEach((col, ci) =>
    col.forEach((id, ri) => pos.set(id, { x: ci * (NODE_W + GAP_X), y: ri * (NODE_H + GAP_Y) })))
  graph.nodes.forEach((n, i) => {
    if (!pos.has(n.id)) pos.set(n.id, { x: 0, y: i * (NODE_H + GAP_Y) }) // cycle fallback
  })
  return pos
}

function configSummary(n: WfNode): string {
  const c = n.config ?? {}
  if (n.type === 'input') return `run input “${c.key ?? '?'}”`
  if (n.type === 'prompt') return String(c.text ?? '').slice(0, 40) || 'empty'
  if (c.family) return `model: ${c.family}`
  if (n.type === 'clip_video') return `${c.count ?? 3} clips ≤ ${c.max_clip_s ?? 15}s`
  return ''
}

const RUN_DOT: Record<string, string> = {
  succeeded: 'bg-emerald-400', failed: 'bg-red-400', skipped: 'bg-faint',
  running: 'bg-amber-400', waiting_approval: 'bg-ember',
}

function GraphCanvas({ graph, availability, selected, onSelect, connectFrom, states }: {
  graph: WfGraph
  availability?: WorkflowView['availability']
  selected: string | null
  onSelect: (id: string) => void
  connectFrom: string | null
  states?: WorkflowRunView['node_states']
}) {
  const pos = nodePositions(graph)
  const avail = new Map((availability ?? []).map((a) => [a.id, a]))
  const width = Math.max(...[...pos.values()].map((p) => p.x + NODE_W), NODE_W) + 8
  const height = Math.max(...[...pos.values()].map((p) => p.y + NODE_H), NODE_H) + 8
  return (
    <div className="overflow-x-auto">
      <div className="relative" style={{ width, height }}>
        <svg className="absolute inset-0 pointer-events-none" width={width} height={height} aria-hidden>
          {graph.edges.map((e, i) => {
            const a = pos.get(e.from)
            const b = pos.get(e.to)
            if (!a || !b) return null
            const x1 = a.x + NODE_W
            const y1 = a.y + NODE_H / 2
            const x2 = b.x
            const y2 = b.y + NODE_H / 2
            return (
              <g key={i}>
                <path d={`M ${x1} ${y1} C ${x1 + 32} ${y1}, ${x2 - 32} ${y2}, ${x2} ${y2}`} fill="none" stroke="#272B33" strokeWidth="1.5" />
                <circle cx={x2} cy={y2} r="2.5" fill="#6B7280" />
                {e.when && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 4} fill="#9BA3AF" fontSize="10" textAnchor="middle">{e.when}</text>}
              </g>
            )
          })}
        </svg>
        {graph.nodes.map((n) => {
          const p = pos.get(n.id)!
          const a = avail.get(n.id)
          const st = states?.[n.id]?.status
          return (
            <button
              key={n.id}
              className={`absolute card p-2 text-left transition-colors duration-fast ${selected === n.id ? 'border-ember' : connectFrom === n.id ? 'border-amber-400' : 'hover:border-mute/50'}`}
              style={{ left: p.x, top: p.y, width: NODE_W, height: NODE_H }}
              onClick={() => onSelect(n.id)}
              data-node={n.id}
            >
              <div className="flex items-center gap-1.5 text-[12px]">
                {st && <span className={`w-2 h-2 rounded-full ${RUN_DOT[st] ?? 'bg-faint'}`} title={st} />}
                <span className="font-mono text-faint text-[10.5px]">{n.id}</span>
                <span className="font-medium truncate">{n.type.replace(/_/g, ' ')}</span>
                {a && !a.supported && <span className="ml-auto text-amber-300" title={a.reason ?? ''}>⚠</span>}
              </div>
              <p className="text-[10.5px] text-faint mt-1 line-clamp-2">{configSummary(n)}</p>
              {states?.[n.id]?.error && <p className="text-[10px] text-red-300 truncate">{states[n.id].error}</p>}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function WorkflowEditor() {
  const { id } = useParams()
  const wfId = Number(id)
  const { data: wf, reload } = useFetch(() => forge.workflow(wfId), [wfId])
  const [graph, setGraph] = useState<WfGraph | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [connectFrom, setConnectFrom] = useState<string | null>(null)
  const [addType, setAddType] = useState('generate_image')
  const [run, setRun] = useState<WorkflowRunView | null>(null)
  const [runInputs, setRunInputs] = useState<Record<string, string>>({})
  const [showRunModal, setShowRunModal] = useState(false)
  const poller = useRef<number | null>(null)

  useEffect(() => {
    if (wf && !graph) setGraph(JSON.parse(JSON.stringify(wf.graph)) as WfGraph)
  }, [wf, graph])
  useEffect(() => () => { if (poller.current) window.clearInterval(poller.current) }, [])

  if (!wf || !graph) return <SkeletonGrid count={3} />
  const node = graph.nodes.find((n) => n.id === selected) ?? null
  const inputKeys = graph.nodes.filter((n) => n.type === 'input').map((n) => String(n.config?.key ?? ''))

  const patchNode = (patch: Partial<WfNode> | { config: Record<string, unknown> }) => {
    if (!node) return
    setGraph({
      ...graph,
      nodes: graph.nodes.map((n) => (n.id === node.id ? { ...n, ...patch, config: { ...n.config, ...(patch as { config?: Record<string, unknown> }).config } } : n)),
    })
  }

  const clickNode = (nid: string) => {
    if (connectFrom && connectFrom !== nid) {
      setGraph({ ...graph, edges: [...graph.edges, { from: connectFrom, to: nid }] })
      setConnectFrom(null)
      return
    }
    setSelected(nid)
  }

  const save = async () => {
    try {
      await forge.updateWorkflow(wfId, { graph })
      toastSuccess('Workflow saved')
      reload()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const startRun = async () => {
    try {
      const r = await forge.startRun(wfId, runInputs)
      setShowRunModal(false)
      setRun(r)
      poller.current = window.setInterval(async () => {
        const v = await forge.workflowRun(r.id, true).catch(() => null)
        if (v) setRun(v)
        if (v && ['succeeded', 'failed', 'cancelled'].includes(v.status) && poller.current) {
          window.clearInterval(poller.current)
        }
      }, 2500)
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const waitingNodes = run
    ? Object.entries(run.node_states).filter(([, s]) => s.status === 'waiting_approval').map(([nid]) => nid)
    : []

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="font-display font-medium text-[16px]">{wf.name}</h2>
        {run && <span className={`chip ${run.status === 'waiting_approval' ? '!border-ember text-fg' : ''}`}>run #{run.id}: {run.status}</span>}
        <Link to="/forge/workflows" className="text-[12.5px] text-mute hover:text-fg ml-auto">← All workflows</Link>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        <select className="input !w-auto h-8 py-0 text-[12.5px] pr-7" value={addType} aria-label="Node type" onChange={(e) => setAddType(e.target.value)}>
          {NODE_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
        </select>
        <button
          className="btn h-8 py-0 text-[12.5px]"
          onClick={() => {
            const nid = `n${graph.nodes.length + 1}`
            setGraph({ ...graph, nodes: [...graph.nodes, { id: nid, type: addType, config: addType === 'prompt' ? { text: '' } : addType === 'input' ? { key: 'idea' } : {} }] })
            setSelected(nid)
          }}
        >
          + Add node
        </button>
        <button
          className={`btn h-8 py-0 text-[12.5px] ${connectFrom ? '!border-amber-400/70 text-amber-300' : ''}`}
          disabled={!selected && !connectFrom}
          onClick={() => setConnectFrom(connectFrom ? null : selected)}
        >
          {connectFrom ? `connecting from ${connectFrom} — click a target` : '⤳ Connect from selected'}
        </button>
        <span className="ml-auto flex gap-1.5">
          <button className="btn h-8 py-0 text-[12.5px]" onClick={save}>Save</button>
          <button className="btn-accent h-8 py-0 text-[12.5px]" onClick={() => setShowRunModal(true)}>▶ Run</button>
        </span>
      </div>
      <div className="grid lg:grid-cols-[1fr_280px] gap-3 items-start">
        <div className="card p-4 min-w-0">
          <GraphCanvas graph={graph} availability={wf.availability} selected={selected} onSelect={clickNode} connectFrom={connectFrom} states={run?.node_states} />
          {(wf.availability ?? []).filter((a) => !a.supported).map((a) => (
            <p key={a.id} className="text-[11.5px] text-amber-300 mt-2">⚠ {a.id} ({a.type}): {a.reason}</p>
          ))}
        </div>
        <aside className="card p-3 space-y-2">
          {node ? (
            <>
              <div className="flex items-center gap-2 text-[13px]">
                <span className="font-mono text-faint">{node.id}</span>
                <span className="font-medium">{node.type.replace(/_/g, ' ')}</span>
                <button
                  className="btn-ghost text-[11.5px] px-1.5 py-0.5 ml-auto text-red-300"
                  onClick={() => {
                    setGraph({
                      ...graph,
                      nodes: graph.nodes.filter((n) => n.id !== node.id),
                      edges: graph.edges.filter((e) => e.from !== node.id && e.to !== node.id),
                    })
                    setSelected(null)
                  }}
                >
                  delete
                </button>
              </div>
              {node.type === 'prompt' && (
                <textarea className="input min-h-[80px] text-[12.5px]" value={String(node.config.text ?? '')} aria-label="Prompt text" onChange={(e) => patchNode({ config: { text: e.target.value } })} />
              )}
              {node.type === 'input' && (
                <label className="block text-[12px]">
                  <span className="label">Run input key</span>
                  <input className="input" value={String(node.config.key ?? '')} onChange={(e) => patchNode({ config: { key: e.target.value } })} />
                </label>
              )}
              {['compile', 'generate_image', 'generate_video', 'image_to_video', 'edit_image'].includes(node.type) && (
                <label className="block text-[12px]">
                  <span className="label">Model family (blank = router decides)</span>
                  <input className="input" value={String(node.config.family ?? '')} placeholder="auto" onChange={(e) => patchNode({ config: { family: e.target.value || undefined } })} />
                </label>
              )}
              {node.type === 'clip_video' && (
                <div className="grid grid-cols-2 gap-2 text-[12px]">
                  <label><span className="label">Clips</span><input className="input" type="number" value={Number(node.config.count ?? 3)} onChange={(e) => patchNode({ config: { count: Number(e.target.value) } })} /></label>
                  <label><span className="label">Max s</span><input className="input" type="number" value={Number(node.config.max_clip_s ?? 15)} onChange={(e) => patchNode({ config: { max_clip_s: Number(e.target.value) } })} /></label>
                </div>
              )}
              <div>
                <span className="label">Incoming edges</span>
                {graph.edges.filter((e) => e.to === node.id).map((e, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-[12px]">
                    <span className="chip">{e.from} →{e.when ? ` (${e.when})` : ''}</span>
                    <button className="text-faint hover:text-red-300 text-[11px]" onClick={() => setGraph({ ...graph, edges: graph.edges.filter((x) => x !== e) })}>✕</button>
                  </div>
                ))}
                {graph.edges.filter((e) => e.to === node.id).length === 0 && <p className="text-[11.5px] text-faint">none</p>}
              </div>
              {run?.node_states[node.id]?.output && (
                <details className="text-[11.5px] text-mute">
                  <summary className="cursor-pointer text-faint">Last run output</summary>
                  <pre className="mt-1 bg-well rounded-el p-2 overflow-x-auto text-[10.5px]">{JSON.stringify(run.node_states[node.id].output, null, 1)}</pre>
                </details>
              )}
            </>
          ) : (
            <p className="text-[12.5px] text-faint">Select a node to configure it; use Connect to draw edges. Saved workflows are plain JSON the agent/tool layer can run too.</p>
          )}
        </aside>
      </div>
      {waitingNodes.length > 0 && run && (
        <div className="card !bg-well p-3 flex items-center gap-3 fade-in">
          <span className="text-[13px]">⏸ Waiting for approval: <b>{waitingNodes.join(', ')}</b></span>
          {waitingNodes.map((nid) => (
            <button
              key={nid}
              className="btn-accent h-8 py-0 text-[12.5px]"
              onClick={async () => {
                try {
                  setRun(await forge.approveNode(run.id, nid))
                } catch (e) {
                  toastError((e as Error).message)
                }
              }}
            >
              Approve {nid}
            </button>
          ))}
        </div>
      )}
      {showRunModal && (
        <Modal title="Run workflow" onClose={() => setShowRunModal(false)}>
          {inputKeys.length === 0 && <p className="text-[12.5px] text-faint">No input nodes — the run starts immediately.</p>}
          {inputKeys.map((k) => (
            <label key={k} className="block mb-2">
              <span className="label">{k}</span>
              <input className="input" value={runInputs[k] ?? ''} onChange={(e) => setRunInputs({ ...runInputs, [k]: e.target.value })} placeholder={k === 'video' ? 'path to a video file' : 'your idea'} />
            </label>
          ))}
          <div className="flex justify-end gap-2 mt-3">
            <button className="btn" onClick={() => setShowRunModal(false)}>Cancel</button>
            <button className="btn-accent" onClick={startRun}>Start</button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function WorkflowsIndex() {
  const { data, loading, reload } = useFetch(() => forge.workflows())
  const navigate = useNavigate()
  const [busy, setBusy] = useState<string | null>(null)
  if (loading) return <SkeletonGrid count={4} />
  const workflows = data?.workflows ?? []
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-[12.5px] text-faint max-w-measure">
          Chain operations into reusable pipelines — prompt → optimize → generate → animate → export. Runs pause for approval where you put a checkpoint.
        </p>
        <button
          className="btn-accent"
          onClick={async () => {
            const r = await forge.createWorkflow({
              name: 'New workflow',
              graph: { nodes: [{ id: 'in', type: 'input', config: { key: 'idea' } }], edges: [] },
            })
            navigate(`${r.id}`)
          }}
        >
          ＋ New workflow
        </button>
      </div>
      <section>
        <h2 className="label">Templates</h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {(data?.templates ?? []).map((t) => (
            <div key={t.key} className="card p-4">
              <h3 className="font-display font-medium text-[14px]">{t.name}</h3>
              <p className="text-[12px] text-faint mt-1">{t.description}</p>
              <button
                className="btn h-7 py-0 text-[12px] mt-2"
                disabled={busy === t.key}
                onClick={async () => {
                  setBusy(t.key)
                  try {
                    const w = await forge.fromTemplate(t.key)
                    reload()
                    navigate(`${w.id}`)
                  } finally {
                    setBusy(null)
                  }
                }}
              >
                {busy === t.key ? <Spinner /> : 'Use template'}
              </button>
            </div>
          ))}
        </div>
      </section>
      <section>
        <h2 className="label">Your workflows</h2>
        {workflows.length === 0 ? (
          <EmptyState title="No workflows yet" hint="Start from a template — they open in the editor." icon="⛓" />
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {workflows.map((w) => (
              <Link key={w.id} to={`${w.id}`} className="card p-4 hover:border-mute/50 transition-colors duration-fast">
                <div className="flex items-center gap-2">
                  <h3 className="font-display font-medium text-[14.5px] truncate">{w.name}</h3>
                  <span className="chip ml-auto">{w.node_count} nodes</span>
                </div>
                <p className="text-[12px] text-faint mt-1 line-clamp-2">{w.description ?? `${w.run_count} runs`}</p>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

export function WorkflowsPage() {
  return (
    <Routes>
      <Route path="/" element={<WorkflowsIndex />} />
      <Route path="/:id" element={<WorkflowEditor />} />
    </Routes>
  )
}
