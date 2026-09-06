// Prompt Test Lab (spec §5–§6): versioned variants side by side, runs with
// scores, evaluation findings and diffed refinements.
import { useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { EmptyState, Modal, SkeletonGrid, Spinner } from '../../components/Primitives'
import { ExperimentView, fmtUsd, forge, VariantRunView, VariantView } from '../../lib/forge'
import { useFetch } from '../../lib/hooks'
import { toastError, toastSuccess } from '../../lib/toast'

function Stars({ value, onSet }: { value: number | null; onSet: (n: number) => void }) {
  return (
    <span className="inline-flex gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} aria-label={`score ${n}`} className={`text-[13px] ${value != null && n <= value ? 'text-ember' : 'text-faint hover:text-mute'}`} onClick={() => onSet(n)}>
          ★
        </button>
      ))}
    </span>
  )
}

function RunRow({ run, onChanged }: { run: VariantRunView; onChanged: () => void }) {
  const [refining, setRefining] = useState(false)
  const [refinement, setRefinement] = useState<Awaited<ReturnType<typeof forge.refineRun>> | null>(null)
  const refine = async () => {
    setRefining(true)
    try {
      setRefinement(await forge.refineRun(run.id))
      onChanged()
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setRefining(false)
    }
  }
  return (
    <div className="rounded-el border border-line/70 p-2 space-y-1.5">
      <div className="flex items-center gap-2 text-[12px]">
        <span className={`w-1.5 h-1.5 rounded-full ${run.status === 'succeeded' ? 'bg-emerald-400' : run.status === 'failed' ? 'bg-red-400' : 'bg-amber-400'}`} />
        <span className="text-mute">{run.provider} · {run.family}</span>
        <span className="ml-auto text-faint tabular-nums">{fmtUsd(run.cost)}{run.latency_s != null ? ` · ${run.latency_s}s` : ''}</span>
      </div>
      {run.thumb_url && (
        <Link to={`/?post=${run.output_post_id}`}>
          <img src={run.thumb_url} alt="" className="rounded-el w-full aspect-video object-cover bg-well" />
        </Link>
      )}
      {run.error && <p className="text-[11.5px] text-red-300">{run.error}</p>}
      <div className="flex items-center gap-2">
        <Stars value={run.user_score} onSet={async (n) => { await forge.scoreRun(run.id, { score: n }); onChanged() }} />
        {run.status === 'succeeded' && (
          <button className="btn-ghost text-[11.5px] px-1.5 py-0.5 ml-auto" onClick={refine} disabled={refining}>
            {refining ? <Spinner /> : 'Evaluate & refine'}
          </button>
        )}
      </div>
      {(refinement || (run.evaluation?.findings?.length ?? 0) > 0) && (
        <div className="text-[11.5px] space-y-1 border-t border-line/60 pt-1.5">
          {(refinement?.evaluation.findings ?? run.evaluation.findings ?? []).map((f, i) => (
            <p key={i} className={f.severity === 'error' ? 'text-red-300' : f.severity === 'warn' ? 'text-amber-300' : 'text-faint'}>
              {f.message}
            </p>
          ))}
          {refinement && !refinement.proposal.unchanged && (
            <div className="rounded-el bg-well/70 p-2">
              <p className="text-faint mb-1">Proposed revision (saved as v{refinement.new_variant_id ? 'next' : '—'} — your prompt is untouched):</p>
              <p className="leading-relaxed">
                {refinement.proposal.diff.map((d, i) =>
                  d.op === 'same' ? <span key={i}>{d.text} </span>
                    : d.op === 'add' ? <span key={i} className="text-emerald-300 bg-emerald-400/10 rounded px-0.5">{d.text} </span>
                      : <span key={i} className="text-red-300/80 line-through">{d.text} </span>)}
              </p>
            </div>
          )}
          {refinement?.proposal.unchanged && <p className="text-faint">Nothing to change deterministically.</p>}
        </div>
      )}
    </div>
  )
}

function VariantColumn({ v, onChanged }: { v: VariantView; onChanged: () => void }) {
  const [forking, setForking] = useState(false)
  const [text, setText] = useState(v.prompt)
  return (
    <div className={`card p-3 w-[300px] shrink-0 space-y-2 ${v.winner ? 'border-ember' : ''}`}>
      <div className="flex items-center gap-1.5 text-[12px]">
        <span className="font-mono text-faint">v{v.version}</span>
        <span className="font-medium truncate">{v.label ?? v.origin}</span>
        {v.parent_id && <span className="chip !text-[10px]">← v{v.parent_id}</span>}
        <button
          className={`ml-auto text-[13px] ${v.winner ? 'text-ember' : 'text-faint hover:text-ember'}`}
          title="Keep as winner"
          onClick={async () => {
            const run = v.runs[0]
            if (run) { await forge.scoreRun(run.id, { winner: !v.winner }); onChanged() }
          }}
        >
          {v.winner ? '♛' : '♚'}
        </button>
      </div>
      <p className="text-[12px] leading-relaxed bg-well/60 border border-line rounded-el p-2 max-h-32 overflow-y-auto whitespace-pre-wrap">{v.prompt}</p>
      {v.negative && <p className="text-[11px] text-mute font-mono truncate" title={v.negative}>neg: {v.negative}</p>}
      <p className="text-[11px] text-faint">{v.family} · {v.provider ?? 'auto provider'}</p>
      <div className="flex gap-1.5">
        <button
          className="btn h-7 py-0 text-[12px]"
          onClick={async () => {
            try {
              await forge.runVariant(v.id)
              toastSuccess(`v${v.version} queued`)
              onChanged()
            } catch (e) {
              toastError((e as Error).message)
            }
          }}
        >
          ▶ Run
        </button>
        <button className="btn h-7 py-0 text-[12px]" onClick={() => setForking(true)}>Fork…</button>
      </div>
      <div className="space-y-2">
        {v.runs.map((r) => <RunRow key={r.id} run={r} onChanged={onChanged} />)}
      </div>
      {forking && (
        <Modal title={`Fork v${v.version}`} onClose={() => setForking(false)}>
          <textarea className="input min-h-[120px] text-[13px]" value={text} onChange={(e) => setText(e.target.value)} aria-label="Forked prompt" />
          <div className="flex justify-end gap-2 mt-3">
            <button className="btn" onClick={() => setForking(false)}>Cancel</button>
            <button
              className="btn-accent"
              onClick={async () => {
                try {
                  await forge.forkVariant(v.id, { prompt: text })
                  setForking(false)
                  onChanged()
                } catch (e) {
                  toastError((e as Error).message)
                }
              }}
            >
              Create fork
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function ExperimentDetail() {
  const { id } = useParams()
  const expId = Number(id)
  const { data, loading, reload } = useFetch(() => forge.experiment(expId), [expId])
  const [family, setFamily] = useState('')
  const { data: models } = useFetch(() => forge.models())
  if (loading || !data) return <SkeletonGrid count={3} />
  const exp = data as ExperimentView
  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h2 className="font-display font-medium text-[16px]">{exp.name}</h2>
        {exp.brief && <span className="text-[12.5px] text-faint max-w-xl truncate">{exp.brief}</span>}
        <Link to="/forge/lab" className="text-[12.5px] text-mute hover:text-fg ml-auto">← All experiments</Link>
      </div>
      <div className="flex items-center gap-2">
        <select className="input !w-auto h-8 py-0 text-[12.5px] pr-7" value={family} aria-label="Compile for model" onChange={(e) => setFamily(e.target.value)}>
          <option value="">Compile for model…</option>
          {(models?.models ?? []).map((m) => <option key={m.family} value={m.family}>{m.display_name ?? m.family}</option>)}
        </select>
        <button
          className="btn h-8 py-0 text-[12.5px]"
          disabled={!family || !exp.brief}
          onClick={async () => {
            try {
              await forge.addVariant(expId, { compile_family: family })
              reload()
            } catch (e) {
              toastError((e as Error).message)
            }
          }}
        >
          + Add compiled variant
        </button>
        <button className="btn h-8 py-0 text-[12.5px]" onClick={reload}>↻ Refresh</button>
      </div>
      {exp.variants.length === 0 ? (
        <EmptyState title="No variants yet" hint="Compile the brief for a model, or send a package here from Compose." icon="⚗" />
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {exp.variants.map((v) => <VariantColumn key={v.id} v={v} onChanged={reload} />)}
        </div>
      )}
    </div>
  )
}

function LabIndex() {
  const { data, loading, reload } = useFetch(() => forge.experiments())
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [brief, setBrief] = useState('')
  const navigate = useNavigate()
  if (loading) return <SkeletonGrid count={4} />
  const experiments = data?.experiments ?? []
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[12.5px] text-faint max-w-measure">Compare prompt versions, models and settings side by side; score results, keep winners, refine with visible diffs.</p>
        <button className="btn-accent" onClick={() => setCreating(true)}>＋ New experiment</button>
      </div>
      {experiments.length === 0 ? (
        <EmptyState title="No experiments yet" hint="Start one here, or hit “Send to Lab” on a compiled prompt in Compose." icon="⚗" />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {experiments.map((e) => (
            <Link key={e.id} to={`${e.id}`} className="card p-4 hover:border-mute/50 transition-colors duration-fast">
              <div className="flex items-center gap-2">
                <h3 className="font-display font-medium text-[14.5px] truncate">{e.name}</h3>
                <span className="chip ml-auto">{e.variant_count} v</span>
              </div>
              {e.brief && <p className="text-[12px] text-faint mt-1 line-clamp-2">{e.brief}</p>}
            </Link>
          ))}
        </div>
      )}
      {creating && (
        <Modal title="New experiment" onClose={() => setCreating(false)}>
          <label className="label" htmlFor="exp-name">Name</label>
          <input id="exp-name" className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
          <label className="label mt-3" htmlFor="exp-brief">Brief (the idea being tested)</label>
          <textarea id="exp-brief" className="input min-h-[80px]" value={brief} onChange={(e) => setBrief(e.target.value)} />
          <div className="flex justify-end gap-2 mt-4">
            <button className="btn" onClick={() => setCreating(false)}>Cancel</button>
            <button
              className="btn-accent"
              disabled={!name.trim()}
              onClick={async () => {
                try {
                  const exp = await forge.createExperiment(name.trim(), brief.trim() || undefined)
                  setCreating(false)
                  reload()
                  navigate(`${exp.id}`)
                } catch (e) {
                  toastError((e as Error).message)
                }
              }}
            >
              Create
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}

export function LabPage() {
  return (
    <Routes>
      <Route path="/" element={<LabIndex />} />
      <Route path="/:id" element={<ExperimentDetail />} />
    </Routes>
  )
}
