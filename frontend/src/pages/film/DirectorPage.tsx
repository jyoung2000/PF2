// AI Director (spec §13, A, B, AE, F, G, X): production plan with approval,
// reference-video analysis → grounded proposal, Direct Story / Scene,
// proposals with Accept / Reject / Edit, sample + batch runs, live board,
// decision log. Every AI output is a proposal until accepted.
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal, Spinner } from '../../components/Primitives'
import { timeAgo } from '../../lib/format'
import { errorMessage, film, fmtTc, fmtUsd, Job, Proposal } from '../../lib/film'
import { useFetch } from '../../lib/hooks'
import { toastError, toastSuccess } from '../../lib/toast'
import { BacklotBoard, DecisionLog, GatesPanel } from './ProjectsPage'
import { useFilm } from './FilmPage'

export function DirectorPage() {
  const { project, reloadProject } = useFilm()
  const [useLlm, setUseLlm] = useState(true)
  const proposals = useFetch(() => (project ? film.proposals(project.id) : Promise.resolve(null)), [project?.id])
  const board = useFetch(() => (project ? film.board(project.id) : Promise.resolve(null)), [project?.id])
  const gates = useFetch(() => (project ? film.gates(project.id) : Promise.resolve(null)), [project?.id])
  const refresh = async () => {
    await reloadProject()
    proposals.reload()
    board.reload()
    gates.reload()
  }
  useEffect(() => {
    const t = window.setInterval(() => board.reload(), 6000)
    return () => window.clearInterval(t)
  }, [project?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!project) return null
  const pending = (proposals.data?.proposals ?? []).filter((p) => !p.applied && !p.rejected)
  const history = (proposals.data?.proposals ?? []).filter((p) => p.applied || p.rejected)
  return (
    <div className="space-y-4" data-testid="director-page">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="flex items-center gap-1.5 text-[12.5px] text-mute"><input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} /> use the configured AI provider <span className="text-faint">(deterministic breakdown when none is set up)</span></label>
      </div>
      {board.data && <BacklotBoard board={board.data} compact />}
      <div className="grid lg:grid-cols-2 gap-3">
        <PlanCard project={project} useLlm={useLlm} gates={gates.data?.gates ?? []} onChanged={refresh} />
        <ReferenceCard project={project} useLlm={useLlm} onChanged={refresh} />
      </div>
      <DirectCard project={project} useLlm={useLlm} onChanged={refresh} />
      <section className="space-y-2">
        <h3 className="font-display text-[15px]">Proposals {pending.length > 0 && <span className="chip text-ember ml-1">{pending.length} awaiting your decision</span>}</h3>
        {proposals.data == null ? <Spinner /> : pending.length === 0 ? <p className="text-[12.5px] text-faint">No pending proposals. Ask the Director above.</p> : pending.map((p) => <ProposalCard key={p.id} p={p} onChanged={refresh} />)}
        {history.length > 0 && (
          <details className="text-[12px]"><summary className="text-faint cursor-pointer">{history.length} decided proposal(s)</summary>
            <div className="space-y-1 mt-1">{history.map((p) => <div key={p.id} className="text-mute">{p.applied ? '✓ accepted' : '✕ rejected'} · {p.kind.replace(/_/g, ' ')} · {p.source} · {timeAgo(p.created_at)}{p.note ? ` — ${p.note}` : ''}</div>)}</div>
          </details>
        )}
      </section>
      <RunsCard project={project} onChanged={refresh} />
      <div className="grid lg:grid-cols-2 gap-3">
        <section className="card p-3.5"><h3 className="font-display text-[14px] mb-2">Approval gates</h3>{gates.data ? <GatesPanel projectId={project.id} gates={gates.data.gates} onChanged={refresh} /> : <Spinner />}</section>
        <section className="card p-3.5"><h3 className="font-display text-[14px] mb-2">Decision log</h3><DecisionLog projectId={project.id} limit={25} /></section>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- plan ----
function PlanCard({ project, useLlm, gates, onChanged }: { project: NonNullable<ReturnType<typeof useFilm>['project']>; useLlm: boolean; gates: { kind: string; status: string; stale: boolean }[]; onChanged: () => void }) {
  const plan = project.plan ?? {}
  const gate = gates.find((g) => g.kind === 'plan')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  const draft = async () => {
    setBusy(true)
    try {
      const p = await film.directPlan(project.id, useLlm)
      toastSuccess(`Plan drafted (${p.source === 'llm' ? 'AI' : 'deterministic'}) — review it below`)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const has = Boolean(plan.objective)
  const est = plan.estimates ?? {}
  return (
    <section className="card p-3.5 space-y-2" data-testid="plan-card">
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="font-display text-[14px]">Production plan</h3>
        {has && <span className={`chip !text-[10px] ${plan.approved ? 'text-emerald-300' : 'text-amber-300'}`}>{plan.approved ? 'approved' : 'not approved'}{gate?.stale ? ' · stale' : ''}</span>}
        <div className="ml-auto flex gap-1.5">
          {has && <button className="btn text-[12px]" onClick={() => setEditing(true)}>Edit</button>}
          <button className="btn-accent text-[12px]" onClick={draft} disabled={busy}>{busy ? <Spinner /> : has ? 'Revise with Director' : 'Draft plan with Director'}</button>
        </div>
      </div>
      {!has ? (
        <p className="text-[12.5px] text-faint">A plan comes before expensive generation: objective, audience, runtime, aspect, style, structure, scene/shot counts, media + audio + provider strategy, estimated cost and render time. Accepting a proposal fills it; approving the gate unlocks bulk generation.</p>
      ) : (
        <dl className="grid sm:grid-cols-2 gap-x-3 gap-y-1 text-[12.5px]">
          <Item k="Objective" v={plan.objective} /><Item k="Audience" v={plan.audience} />
          <Item k="Runtime" v={fmtTc(plan.target_runtime_s)} /><Item k="Aspect" v={plan.aspect_ratio} />
          <Item k="Visual style" v={plan.visual_style} /><Item k="Structure" v={plan.narrative_structure} />
          <Item k="Scenes / shots" v={`${plan.scene_count ?? '—'} / ${plan.shot_count ?? '—'}`} /><Item k="Pacing" v={plan.pacing_profile} />
          <Item k="Media strategy" v={plan.media_strategy?.summary} />
          <Item k="By medium" v={Object.entries(plan.media_strategy?.by_kind ?? {}).map(([k, n]) => `${k.replace(/_/g, ' ')} ×${n}`).join(', ')} />
          <Item k="Audio" v={plan.audio_strategy} /><Item k="Providers" v={plan.provider_strategy} />
          <Item k="Estimated cost" v={est.basis === 'unavailable' ? 'unavailable (no catalog price)' : `${fmtUsd(plan.estimated_cost_usd)} · ${est.basis ?? 'catalog'}${est.providers_connected === false ? ' · no provider connected yet' : ''}`} />
          <Item k="Render time" v={plan.estimated_render_min != null ? `~${plan.estimated_render_min} min` : '—'} />
          {plan.risks?.length > 0 && <Item k="Risks" v={plan.risks.join(' · ')} />}
          {plan.notes && <Item k="Notes" v={plan.notes} />}
        </dl>
      )}
      {editing && <PlanEditor project={project} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); onChanged() }} />}
    </section>
  )
}

function Item({ k, v }: { k: string; v: unknown }) {
  if (v == null || v === '') return null
  return <div className="flex gap-2 min-w-0"><dt className="text-faint w-24 shrink-0">{k}</dt><dd className="text-fg min-w-0">{String(v)}</dd></div>
}

function PlanEditor({ project, onClose, onSaved }: { project: { id: number; plan: Record<string, any> }; onClose: () => void; onSaved: () => void }) {
  const [p, setP] = useState<Record<string, any>>({ objective: '', audience: '', visual_style: '', narrative_structure: '', audio_strategy: '', provider_strategy: '', notes: '', ...project.plan })
  const save = async () => {
    try {
      await film.putPlan(project.id, { objective: p.objective, audience: p.audience, visual_style: p.visual_style, narrative_structure: p.narrative_structure, audio_strategy: p.audio_strategy, provider_strategy: p.provider_strategy, notes: p.notes })
      toastSuccess('Plan saved — approval reset')
      onSaved()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  return (
    <Modal title="Edit production plan" onClose={onClose} wide>
      <div className="grid sm:grid-cols-2 gap-2 text-[12.5px]">
        {['objective', 'audience', 'visual_style', 'narrative_structure', 'audio_strategy', 'provider_strategy'].map((k) => (
          <label key={k} className="text-mute flex flex-col gap-1">{k.replace(/_/g, ' ')}<input className="input" value={p[k] ?? ''} onChange={(e) => setP({ ...p, [k]: e.target.value })} /></label>
        ))}
        <label className="text-mute flex flex-col gap-1 sm:col-span-2">notes<textarea className="input min-h-[60px]" value={p.notes ?? ''} onChange={(e) => setP({ ...p, notes: e.target.value })} /></label>
      </div>
      <div className="flex justify-end gap-2 mt-3"><button className="btn" onClick={onClose}>Cancel</button><button className="btn-accent" onClick={save}>Save</button></div>
    </Modal>
  )
}

// ----------------------------------------------------------- reference ----
function ReferenceCard({ project, useLlm, onChanged }: { project: NonNullable<ReturnType<typeof useFilm>['project']>; useLlm: boolean; onChanged: () => void }) {
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [busy, setBusy] = useState(false)
  const [postId, setPostId] = useState('')
  const [url, setUrl] = useState('')
  const ref = project.reference ?? {}
  const has = Boolean(ref.shot_count)
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    try {
      await fn()
      toastSuccess(ok)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="card p-3.5 space-y-2" data-testid="reference-card">
      <div className="flex items-center gap-2"><h3 className="font-display text-[14px]">Start from a reference video</h3><span className="text-[11px] text-faint">structure + pacing only — never copied</span></div>
      <div className="flex flex-wrap gap-1.5 items-center">
        <button className="btn text-[12px]" onClick={() => fileRef.current?.click()} disabled={busy}>Upload video</button>
        <input ref={fileRef} type="file" accept="video/mp4,video/webm,video/quicktime" hidden onChange={(e) => e.target.files?.[0] && run(() => film.referenceUpload(project.id, e.target.files![0]), 'Reference analysed')} />
        <input className="input !w-28 !h-8 text-[12px]" placeholder="post id" value={postId} onChange={(e) => setPostId(e.target.value)} />
        <button className="btn text-[12px]" disabled={!postId || busy} onClick={() => run(() => film.referenceFrom(project.id, { post_id: Number(postId) }), 'Reference analysed')}>From Gallery</button>
        <input className="input !w-44 !h-8 text-[12px]" placeholder="YouTube / TikTok URL" value={url} onChange={(e) => setUrl(e.target.value)} />
        <button className="btn text-[12px]" disabled={!url || busy} onClick={() => run(() => film.referenceFrom(project.id, { url }), 'Reference analysed')}>From URL</button>
        {busy && <Spinner />}
      </div>
      {has ? (
        <div className="space-y-1.5 text-[12.5px]">
          <div className="flex flex-wrap gap-1">
            <span className="chip">{fmtTc(ref.duration_s)}</span><span className="chip">{ref.shot_count} shots</span>
            {ref.pacing && <span className="chip">median {ref.pacing.median_s}s → {ref.pacing_profile}</span>}
            <span className="chip">{ref.aspect_ratio}</span><span className="chip">{ref.audio ? 'audio' : 'no audio'}</span>
            {ref.style && <span className="chip">{ref.style.look} (heuristic)</span>}
          </div>
          {ref.keyframes?.length > 0 && <div className="flex gap-1 overflow-x-auto">{ref.keyframes.map((k: string) => <img key={k} src={k} alt="" className="h-14 rounded-el border border-line" />)}</div>}
          <p className="text-[11px] text-faint">{ref.transcript_note} {ref.on_screen_text_note} Camera patterns: {ref.camera_patterns}.</p>
          <p className="text-[11px] text-faint">Source: {ref.source?.kind}{ref.source?.name ? ` · ${ref.source.name}` : ref.source?.url ? ` · ${ref.source.url}` : ''}</p>
          <button className="btn-accent text-[12px]" onClick={() => run(() => film.referencePropose(project.id, useLlm), 'Reference-based proposal ready below')} disabled={busy}>Propose a production plan from it</button>
        </div>
      ) : (
        <p className="text-[12px] text-faint">Measured deterministically (ffprobe, scene cuts, keyframes, pacing, aspect). Transcript and on-screen text need providers this build does not declare.</p>
      )}
    </section>
  )
}

// -------------------------------------------------------------- direct ----
function DirectCard({ project, useLlm, onChanged }: { project: NonNullable<ReturnType<typeof useFilm>['project']>; useLlm: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [sceneId, setSceneId] = useState<number | ''>('')
  const scenes = project.scenes ?? []
  const run = async (key: string, fn: () => Promise<Proposal>) => {
    setBusy(key)
    try {
      const p = await fn()
      toastSuccess(`Proposal ready (${p.source === 'llm' ? 'AI' : 'deterministic'}) — review below`)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  return (
    <section className="card p-3.5 flex flex-wrap items-center gap-2" data-testid="direct-card">
      <div className="mr-2"><h3 className="font-display text-[14px]">Direct</h3><p className="text-[11.5px] text-faint">Story → scenes, characters, locations, props, shot list, cinematography.</p></div>
      <button className="btn-accent" onClick={() => run('story', () => film.directStory(project.id, useLlm))} disabled={busy != null || !(project.script || project.synopsis || project.logline)} title={!(project.script || project.synopsis || project.logline) ? 'Write a logline, synopsis or script first' : ''}>{busy === 'story' ? <Spinner /> : 'Direct story'}</button>
      <select className="input !w-48 !h-9" value={sceneId} onChange={(e) => setSceneId(e.target.value ? Number(e.target.value) : '')}><option value="">scene…</option>{scenes.map((s) => <option key={s.id} value={s.id}>{s.number}. {s.title}</option>)}</select>
      <button className="btn" onClick={() => sceneId && run('scene', () => film.directScene(Number(sceneId), useLlm))} disabled={!sceneId || busy != null}>{busy === 'scene' ? <Spinner /> : 'Direct scene'}</button>
      <span className="text-[11.5px] text-faint">Direct a single shot from its inspector in the Storyboard.</span>
    </section>
  )
}

// ----------------------------------------------------------- proposals ----
export function ProposalCard({ p, onChanged, compact = false }: { p: Proposal; onChanged: () => void; compact?: boolean }) {
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<'append' | 'replace'>('append')
  const [editJson, setEditJson] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const navigate = useNavigate()
  const pr = p.proposal ?? {}
  const accept = async () => {
    setBusy(true)
    try {
      let edits: Record<string, unknown> | undefined
      if (editJson != null) {
        try {
          edits = JSON.parse(editJson)
        } catch {
          toastError('Edited JSON is not valid')
          setBusy(false)
          return
        }
      }
      const r = await film.acceptProposal(p.id, { edits, mode })
      const res = r.result as Record<string, any>
      toastSuccess(p.kind === 'director_story' ? `Applied: ${res.scene_ids?.length ?? 0} scenes, ${res.shot_ids?.length ?? 0} shots, ${res.asset_ids?.length ?? 0} assets` : p.kind === 'director_shot' ? `Applied ${res.changed?.length ?? 0} change(s)${res.blocked?.length ? `, ${res.blocked.length} blocked by locks` : ''}` : 'Proposal applied')
      onChanged()
      if (p.kind === 'director_story' || p.kind === 'director_scene') navigate('/film/storyboard')
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const reject = async () => {
    setBusy(true)
    try {
      await film.rejectProposal(p.id, note || undefined)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const est = pr.estimates
  return (
    <div className="card p-3 space-y-2 fade-in" data-proposal-id={p.id} data-proposal-kind={p.kind}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-display text-[13.5px]">{p.kind.replace(/_/g, ' ')}</span>
        <span className={`chip !text-[10px] ${p.source === 'llm' ? 'text-ember' : ''}`}>{p.source === 'llm' ? 'AI' : 'deterministic'}</span>
        <span className="text-[11px] text-faint">{timeAgo(p.created_at)}</span>
        {est?.total_usd != null && <span className="chip !text-[10px]">est {fmtUsd(est.total_usd)}{est.providers_connected === false ? ' · no provider yet' : ''}</span>}
        <div className="ml-auto flex items-center gap-1.5">
          {(p.kind === 'director_story' || p.kind === 'director_scene') && (
            <select className="input !w-28 !h-8 text-[12px]" value={mode} onChange={(e) => setMode(e.target.value as 'append' | 'replace')}><option value="append">append</option><option value="replace">replace</option></select>
          )}
          <button className="btn-ghost text-[12px]" onClick={() => setEditJson(editJson == null ? JSON.stringify(pr, null, 2) : null)}>{editJson == null ? 'Edit' : 'Cancel edit'}</button>
          <button className="btn text-[12px]" onClick={reject} disabled={busy}>Reject</button>
          <button className="btn-accent text-[12px]" onClick={accept} disabled={busy} data-testid="accept-proposal">{busy ? <Spinner /> : 'Accept'}</button>
        </div>
      </div>
      {editJson != null ? (
        <textarea className="input font-mono text-[11.5px] min-h-[220px]" value={editJson} onChange={(e) => setEditJson(e.target.value)} spellCheck={false} />
      ) : !compact ? (
        <ProposalBody p={p} />
      ) : null}
      <input className="input !h-7 text-[12px]" placeholder="note for the decision log (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
    </div>
  )
}

function ProposalBody({ p }: { p: Proposal }) {
  const pr = p.proposal ?? {}
  if (p.kind === 'director_story') {
    const assets = pr.assets ?? {}
    return (
      <div className="text-[12.5px] space-y-1.5">
        <div className="flex flex-wrap gap-1">{(['characters', 'locations', 'props'] as const).map((k) => (assets[k] ?? []).map((a: any) => <span key={k + a.name} className="chip">{k === 'characters' ? '👤' : k === 'locations' ? '📍' : '🔦'} {a.name}</span>))}</div>
        <ol className="space-y-1">
          {(pr.scenes ?? []).map((sc: any, i: number) => (
            <li key={i} className="card !bg-well p-2">
              <div className="font-display">{i + 1}. {sc.title} <span className="text-faint font-body">{sc.location ? `· ${sc.location}` : ''} {sc.time_of_day ?? ''} {sc.weather ?? ''} {sc.lighting_preset ? `· ${sc.lighting_preset.replace(/_/g, ' ')}` : ''}</span></div>
              {sc.intent && <div className="text-mute">{sc.intent}</div>}
              <ul className="mt-1 space-y-0.5">
                {(sc.shots ?? []).map((sh: any, j: number) => (
                  <li key={j} className="flex gap-2 text-[12px]"><span className="text-faint w-8 shrink-0">{i + 1}.{j + 1}</span><span className="chip !text-[10px] shrink-0">{sh.shot_type?.replace(/_/g, ' ')}</span><span className="text-faint shrink-0">{sh.duration_s}s · {sh.media_strategy?.replace(/_/g, ' ')}</span><span className="min-w-0">{sh.action}{sh.reason ? <span className="text-faint"> — {sh.reason}</span> : null}</span></li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
        {pr.notes && <p className="text-faint">{pr.notes}</p>}
        <p className="text-faint">{pr.shot_count} shots · ~{fmtTc(pr.runtime_s)} runtime</p>
      </div>
    )
  }
  if (p.kind === 'director_scene') {
    return (
      <ul className="text-[12.5px] space-y-0.5">
        {(pr.shots ?? []).map((sh: any, j: number) => (
          <li key={j} className="flex gap-2"><span className="chip !text-[10px] shrink-0">{sh.shot_type?.replace(/_/g, ' ')}</span><span className="text-faint shrink-0">{sh.duration_s}s</span><span>{sh.action}{sh.reason ? <span className="text-faint"> — {sh.reason}</span> : null}</span></li>
        ))}
      </ul>
    )
  }
  if (p.kind === 'director_shot') {
    return (
      <div className="text-[12.5px] space-y-1">
        <p className="text-mute">“{pr.instruction}”</p>
        <p>{pr.explanation}</p>
        <ul className="space-y-0.5">
          {Object.entries(pr.changes ?? {}).map(([k, v]) => <li key={k}><span className="text-faint">{k}:</span> {typeof v === 'object' ? JSON.stringify(v) : String(v)}</li>)}
          {(pr.blocked ?? []).map((b: any) => <li key={b.key} className="text-amber-300">🔒 {b.key} not changed — {b.reason}</li>)}
        </ul>
      </div>
    )
  }
  if (p.kind === 'reference_proposal') {
    return (
      <div className="text-[12.5px] space-y-1">
        <div><span className="text-faint">Retained:</span> {(pr.retained ?? []).join(' · ')}</div>
        <div><span className="text-faint">Changed:</span> {(pr.changed ?? []).join(' · ')}</div>
        <div><span className="text-faint">Structure:</span> {pr.structure} · pacing {pr.pacing_profile} · {pr.aspect_ratio} · ~{fmtTc(pr.estimated_duration_s)} · est {fmtUsd(pr.estimated_cost_usd)}</div>
        <ul className="flex flex-wrap gap-1">{(pr.scenes ?? []).map((sc: any, i: number) => <li key={i} className="chip">{sc.title} · {sc.shots} shots · {sc.duration_s}s</li>)}</ul>
        <div className="text-faint">{pr.media_strategy} · {pr.audio_strategy}</div>
      </div>
    )
  }
  return (
    <dl className="grid sm:grid-cols-2 gap-x-3 gap-y-0.5 text-[12.5px]">
      {Object.entries(pr).filter(([k]) => !['estimates', 'shots_basis', 'risks'].includes(k)).map(([k, v]) => <Item key={k} k={k.replace(/_/g, ' ')} v={typeof v === 'object' ? JSON.stringify(v) : v} />)}
    </dl>
  )
}

// ------------------------------------------------------------------ runs --
function RunsCard({ project, onChanged }: { project: NonNullable<ReturnType<typeof useFilm>['project']>; onChanged: () => void }) {
  const jobs = useFetch(() => film.jobs(project.id), [project.id])
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState<{ message: string; missing?: string[]; budget?: any } | null>(null)
  const navigate = useNavigate()
  useEffect(() => {
    const t = window.setInterval(() => jobs.reload(), 4000)
    return () => window.clearInterval(t)
  }, [project.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const start = async (body: Parameters<typeof film.startRun>[1]) => {
    setBusy(true)
    setBlocked(null)
    try {
      const j = await film.startRun(project.id, body)
      toastSuccess(`${body.sample ? 'Sample' : 'Batch'} run started (${j.progress.total} shot(s)${j.payload?.estimate_usd != null ? `, est ${fmtUsd(j.payload.estimate_usd)}` : ''})`)
      jobs.reload()
      onChanged()
    } catch (e) {
      const msg = errorMessage(e)
      const detail = (e as any)?.detail ?? (e as any)?.body?.detail
      setBlocked({ message: msg, missing: detail?.missing_gates, budget: detail?.budget })
    } finally {
      setBusy(false)
    }
  }
  const active = (jobs.data?.jobs ?? []).filter((j) => ['queued', 'running', 'paused'].includes(j.status))
  return (
    <section className="card p-3.5 space-y-2" data-testid="runs-card">
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="font-display text-[14px]">Production runs</h3>
        <button className="btn" onClick={() => start({ sample: true })} disabled={busy}>Run a sample (2–3 shots)</button>
        <button className="btn-accent" onClick={() => start({})} disabled={busy}>Generate all shots</button>
        <button className="btn-ghost text-[12px]" onClick={() => navigate('/film/storyboard')}>or generate shot by shot →</button>
      </div>
      {blocked && (
        <div className="card !bg-well p-2.5 text-[12.5px] fade-in">
          <p className="text-amber-300">{blocked.message}</p>
          {blocked.missing && <p className="text-faint mt-1">Approve the gates first, or <button className="underline" onClick={() => start({ force: true })}>run anyway</button>.</p>}
          {blocked.budget?.requires_approval && <button className="btn mt-1.5" onClick={() => start({ approve_cost: true })}>Approve {fmtUsd(blocked.budget.amount_usd)} and run</button>}
        </div>
      )}
      {active.length > 0 && <div className="space-y-1">{active.map((j) => <JobRow key={j.id} j={j} onChanged={jobs.reload} />)}</div>}
      {(jobs.data?.jobs ?? []).filter((j) => !active.includes(j)).slice(0, 3).map((j) => <JobRow key={j.id} j={j} onChanged={jobs.reload} />)}
    </section>
  )
}

export function JobRow({ j, onChanged }: { j: Job; onChanged: () => void }) {
  const act = async (a: 'pause' | 'resume' | 'cancel') => {
    try {
      await film.jobAction(j.id, a)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const pct = j.progress.total ? Math.round((j.progress.done / j.progress.total) * 100) : j.status === 'done' ? 100 : 0
  return (
    <div className="text-[12px] flex items-center gap-2" data-job-id={j.id}>
      <span className="chip !text-[10px]">{j.kind.replace(/_/g, ' ')}</span>
      <span className={j.status === 'failed' ? 'text-red-300' : j.status === 'done' ? 'text-emerald-300' : j.status === 'paused' ? 'text-amber-300' : 'text-mute'}>{j.status}</span>
      <div className="flex-1 h-1.5 bg-well rounded-full overflow-hidden"><div className="h-full bg-ember" style={{ width: `${pct}%` }} /></div>
      <span className="text-faint tabular-nums">{j.progress.done}/{j.progress.total}{j.progress.current ? ` · ${j.progress.current}` : ''}</span>
      {j.error && <span className="text-red-300 truncate max-w-[240px]" title={j.error}>{j.error}</span>}
      {j.status === 'running' && <button className="btn-ghost text-[11px]" onClick={() => act('pause')}>pause</button>}
      {(j.status === 'paused' || j.status === 'failed') && <button className="btn-ghost text-[11px]" onClick={() => act('resume')}>resume</button>}
      {['queued', 'running', 'paused'].includes(j.status) && <button className="btn-ghost text-[11px] text-red-300" onClick={() => act('cancel')}>cancel</button>}
    </div>
  )
}
