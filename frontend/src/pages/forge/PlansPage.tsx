// Creative Plans (spec §8): one brief → an editable multi-asset pipeline
// with locks, dependencies and per-asset regeneration.
import { useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { EmptyState, Modal, SkeletonGrid, Spinner } from '../../components/Primitives'
import { fmtUsd, forge, PlanAssetView, PlanView } from '../../lib/forge'
import { useFetch } from '../../lib/hooks'
import { toastError, toastSuccess } from '../../lib/toast'

const STATUS_DOT: Record<string, string> = {
  planned: 'bg-faint', queued: 'bg-amber-400', running: 'bg-amber-400',
  succeeded: 'bg-emerald-400', failed: 'bg-red-400',
}

function AssetCard({ plan, a, onChanged }: { plan: PlanView; a: PlanAssetView; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [prompt, setPrompt] = useState(a.prompt ?? '')
  const depNames = a.depends_on.map((d) => plan.assets.find((x) => x.id === d)?.purpose ?? `#${d}`)
  return (
    <div className="card p-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${STATUS_DOT[a.status] ?? 'bg-faint'}`} title={a.status} />
        <h3 className="font-display font-medium text-[13.5px] truncate">{a.purpose}</h3>
        <span className="chip !text-[10px]">{a.kind}</span>
        {a.locked && <span title="locked — will not regenerate">🔒</span>}
        <span className="ml-auto text-[11.5px] text-faint tabular-nums">{fmtUsd(a.cost_estimate)}</span>
      </div>
      {a.thumb_url ? (
        <Link to={`/?post=${a.output_post_id}`}>
          <img src={a.thumb_url} alt="" className="rounded-el w-full aspect-video object-cover bg-well" />
        </Link>
      ) : (
        <div className="rounded-el w-full aspect-video bg-well flex items-center justify-center text-[11px] text-faint">
          {a.status === 'failed' ? '✕ failed' : a.status === 'planned' ? 'not generated yet' : a.status}
        </div>
      )}
      {a.error && <p className="text-[11.5px] text-red-300">{a.error}</p>}
      <p className="text-[11.5px] text-mute line-clamp-2" title={a.prompt ?? ''}>{a.prompt}</p>
      <p className="text-[11px] text-faint">
        {a.family} · {a.provider}{depNames.length > 0 && <> · after {depNames.join(', ')}</>}
      </p>
      <div className="flex gap-1.5 flex-wrap">
        <button
          className="btn h-7 py-0 text-[12px]"
          disabled={a.locked}
          onClick={async () => {
            try {
              await forge.runPlanAsset(plan.id, a.id)
              toastSuccess(`${a.purpose} queued`)
              onChanged()
            } catch (e) {
              toastError((e as Error).message)
            }
          }}
        >
          {a.status === 'succeeded' ? '↻ Regenerate' : '▶ Generate'}
        </button>
        <button className="btn h-7 py-0 text-[12px]" onClick={() => setEditing(true)}>Edit…</button>
        <button
          className="btn h-7 py-0 text-[12px] ml-auto"
          onClick={async () => {
            await forge.editPlanAsset(plan.id, a.id, { locked: !a.locked })
            onChanged()
          }}
        >
          {a.locked ? '🔓 Unlock' : '🔒 Lock'}
        </button>
      </div>
      {editing && (
        <Modal title={`Edit — ${a.purpose}`} onClose={() => setEditing(false)}>
          <label className="label">Prompt</label>
          <textarea className="input min-h-[100px] text-[13px]" value={prompt} onChange={(e) => setPrompt(e.target.value)} aria-label="Asset prompt" />
          <div className="flex justify-end gap-2 mt-3">
            <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
            <button
              className="btn-accent"
              onClick={async () => {
                await forge.editPlanAsset(plan.id, a.id, { prompt })
                setEditing(false)
                onChanged()
              }}
            >
              Save
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function PlanDetail() {
  const { id } = useParams()
  const planId = Number(id)
  const { data: plan, loading, reload } = useFetch(() => forge.plan(planId), [planId])
  const navigate = useNavigate()
  const [running, setRunning] = useState(false)
  if (loading || !plan) return <SkeletonGrid count={4} />
  const run = async (onlyFailed = false) => {
    setRunning(true)
    try {
      const out = await forge.runPlan(planId, onlyFailed)
      if (out.queued.length) toastSuccess(`${out.queued.length} asset${out.queued.length === 1 ? '' : 's'} queued`)
      if (out.blocked.length) toastError(out.blocked.map((b) => `${b.purpose}: ${b.reason}`).join(' · '))
      window.setTimeout(reload, 1200)
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }
  const anyFailed = plan.assets.some((a) => a.status === 'failed')
  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h2 className="font-display font-medium text-[16px]">{plan.name}</h2>
        <span className="chip">{plan.status}</span>
        <span className="text-[12.5px] text-faint tabular-nums">est {fmtUsd(plan.estimated_total)}</span>
        <Link to="/forge/plans" className="text-[12.5px] text-mute hover:text-fg ml-auto">← All plans</Link>
      </div>
      <div className="flex gap-2 flex-wrap">
        <button className="btn-accent" disabled={running} onClick={() => run(false)}>
          {running ? <Spinner /> : '▶ Run plan'}
        </button>
        {anyFailed && <button className="btn" onClick={() => run(true)}>↻ Rerun failed only</button>}
        <button className="btn" onClick={reload}>↻ Refresh</button>
        <button
          className="btn ml-auto"
          onClick={async () => {
            const clone = await forge.forkPlan(planId)
            toastSuccess('Plan branched')
            navigate(`/forge/plans/${clone.id}`)
          }}
        >
          ⑂ Fork branch
        </button>
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {plan.assets.map((a) => <AssetCard key={a.id} plan={plan} a={a} onChanged={reload} />)}
      </div>
    </div>
  )
}

function PlansIndex() {
  const { data, loading, reload } = useFetch(() => forge.plans())
  const [creating, setCreating] = useState(false)
  const [brief, setBrief] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  if (loading) return <SkeletonGrid count={4} />
  const plans = data?.plans ?? []
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[12.5px] text-faint max-w-measure">
          One request, a whole asset set — hero, socials, banner, video — planned with dependencies you can edit before anything generates.
        </p>
        <button className="btn-accent" onClick={() => setCreating(true)}>＋ New plan</button>
      </div>
      {plans.length === 0 ? (
        <EmptyState title="No plans yet" hint="Try “Launch campaign for my new music player, warm retro aesthetic”." icon="🗂" />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {plans.map((p) => (
            <Link key={p.id} to={`${p.id}`} className="card p-4 hover:border-mute/50 transition-colors duration-fast">
              <div className="flex items-center gap-2">
                <h3 className="font-display font-medium text-[14.5px] truncate">{p.name}</h3>
                <span className="chip ml-auto">{p.asset_count}</span>
              </div>
              <p className="text-[12px] text-faint mt-1">{p.status}</p>
            </Link>
          ))}
        </div>
      )}
      {creating && (
        <Modal title="New creative plan" onClose={() => setCreating(false)}>
          <label className="label" htmlFor="plan-brief">What are we making?</label>
          <textarea
            id="plan-brief"
            className="input min-h-[90px]"
            autoFocus
            placeholder="Launch campaign for my new music player app, warm retro aesthetic"
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
          />
          <div className="flex justify-end gap-2 mt-4">
            <button className="btn" onClick={() => setCreating(false)}>Cancel</button>
            <button
              className="btn-accent"
              disabled={!brief.trim() || busy}
              onClick={async () => {
                setBusy(true)
                try {
                  const plan = await forge.createPlan(brief.trim())
                  setCreating(false)
                  reload()
                  navigate(`${plan.id}`)
                } catch (e) {
                  toastError((e as Error).message)
                } finally {
                  setBusy(false)
                }
              }}
            >
              {busy ? <Spinner /> : 'Plan it'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}

export function PlansPage() {
  return (
    <Routes>
      <Route path="/" element={<PlansIndex />} />
      <Route path="/:id" element={<PlanDetail />} />
    </Routes>
  )
}
