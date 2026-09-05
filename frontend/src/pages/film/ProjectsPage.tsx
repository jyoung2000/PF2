// Projects: create/open, settings (aspect, runtime, gaps, pacing,
// continuity mode, budget, pipeline template), Backlot board, gates,
// decision log, costs — all derived from real project state.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ConfirmModal, EmptyState, Modal, Spinner } from '../../components/Primitives'
import { timeAgo } from '../../lib/format'
import { Board, errorMessage, film, fmtUsd, Gate, Project, ProjectSettings, Spend } from '../../lib/film'
import { useFetch } from '../../lib/hooks'
import { toastError, toastSuccess } from '../../lib/toast'
import { useFilm } from './FilmPage'

const STAGE_COLOR: Record<string, string> = { done: 'bg-emerald-400', in_progress: 'bg-ember', waiting_approval: 'bg-amber-400', failed: 'bg-red-400', todo: 'bg-faint' }

export function BacklotBoard({ board, compact = false }: { board: Board; compact?: boolean }) {
  return (
    <div className={`grid gap-1.5 ${compact ? 'grid-cols-5' : 'grid-cols-2 sm:grid-cols-5'}`} data-testid="backlot">
      {board.stages.map((st) => (
        <div key={st.key} className="card !bg-well p-2 text-[11.5px]" title={st.detail ?? ''}>
          <div className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full ${STAGE_COLOR[st.status] ?? 'bg-faint'}`} />
            <span className="font-medium truncate">{st.label}</span>
          </div>
          <div className="text-faint mt-0.5">{st.status.replace('_', ' ')}{st.progress.total ? ` · ${st.progress.done}/${st.progress.total}` : ''}</div>
          {st.current && <div className="text-mute truncate">▶ {st.current}</div>}
          {st.failures > 0 && <div className="text-red-300">{st.failures} failed</div>}
          {!compact && st.waiting.length > 0 && <div className="text-amber-300 truncate">waiting: {st.waiting[0]}{st.waiting.length > 1 ? ` +${st.waiting.length - 1}` : ''}</div>}
          {!compact && st.cost?.estimated_usd != null && (st.cost.estimated_usd > 0 || st.cost.actual_usd > 0) && <div className="text-faint">est {fmtUsd(st.cost.estimated_usd)} · actual {fmtUsd(st.cost.actual_usd)}</div>}
        </div>
      ))}
    </div>
  )
}

export function GatesPanel({ projectId, gates, onChanged }: { projectId: number; gates: Gate[]; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const decide = async (g: Gate, status: 'approved' | 'rejected' | 'pending') => {
    setBusy(g.kind + (g.scene_id ?? ''))
    try {
      const r = await film.decideGate(projectId, g.kind, { status, scene_id: g.scene_id ?? undefined })
      const inv = (r.invalidated ?? {}) as Record<string, number[] | string[]>
      const n = (inv.shots?.length ?? 0) + (inv.gates?.length ?? 0)
      toastSuccess(`${g.label} ${status}${status === 'rejected' && n ? ` — ${inv.shots?.length ?? 0} shot(s) and ${inv.gates?.length ?? 0} gate(s) need re-approval` : ''}`)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="space-y-1" data-testid="gates">
      {gates.map((g) => (
        <div key={g.kind + (g.scene_id ?? '')} className="flex items-center gap-2 text-[12.5px] py-1 border-b border-line last:border-0">
          <span className={`w-2 h-2 rounded-full ${g.status === 'approved' ? (g.stale ? 'bg-amber-400' : 'bg-emerald-400') : g.status === 'rejected' ? 'bg-red-400' : 'bg-faint'}`} />
          <span className="flex-1">{g.label}{g.scene_id ? ` · scene ${g.scene_id}` : ''}</span>
          <span className="text-faint">{g.status}{g.stale ? ' (stale — changed since)' : ''}</span>
          {g.status !== 'approved' || g.stale ? (
            <button className="btn text-[11.5px] py-0.5" disabled={busy != null} onClick={() => decide(g, 'approved')}>Approve</button>
          ) : null}
          {g.status !== 'rejected' && <button className="btn-ghost text-[11.5px] py-0.5" disabled={busy != null} onClick={() => decide(g, 'rejected')}>Reject</button>}
        </div>
      ))}
    </div>
  )
}

export function DecisionLog({ projectId, limit = 30 }: { projectId: number; limit?: number }) {
  const { data } = useFetch(() => film.events(projectId, undefined, limit), [projectId])
  if (!data) return <Spinner />
  return (
    <ol className="space-y-1 text-[12px]" data-testid="decision-log">
      {data.events.map((e) => (
        <li key={e.id} className="flex gap-2">
          <span className="text-faint w-16 shrink-0">{timeAgo(e.at)}</span>
          <span className={`chip !text-[9.5px] shrink-0 ${e.actor === 'director' ? 'text-ember' : ''}`}>{e.actor}</span>
          <span className="min-w-0">
            <span className="text-fg">{e.title}</span>
            {e.reason && <span className="text-mute"> — {e.reason}</span>}
            {e.data?.estimate_usd != null && <span className="text-faint"> · est {fmtUsd(e.data.estimate_usd as number)}</span>}
            {e.data?.actual_usd != null && <span className="text-faint"> · actual {fmtUsd(e.data.actual_usd as number)}</span>}
          </span>
        </li>
      ))}
      {!data.events.length && <li className="text-faint">No decisions logged yet.</li>}
    </ol>
  )
}

export function CostSummary({ spend }: { spend: Spend }) {
  const b = spend.budget
  return (
    <dl className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[12.5px]" data-testid="costs">
      <div className="card !bg-well p-2"><dt className="text-faint text-[11px]">Estimated</dt><dd className="font-display text-[16px] tabular-nums">{fmtUsd(spend.estimated_usd)}</dd></div>
      <div className="card !bg-well p-2"><dt className="text-faint text-[11px]">Spent (actual)</dt><dd className="font-display text-[16px] tabular-nums">{fmtUsd(spend.spent_usd)}</dd></div>
      <div className="card !bg-well p-2"><dt className="text-faint text-[11px]">Reserved (in flight)</dt><dd className="font-display text-[16px] tabular-nums">{fmtUsd(spend.reserved_usd)}</dd></div>
      <div className="card !bg-well p-2"><dt className="text-faint text-[11px]">Budget · {b.mode}</dt><dd className="font-display text-[16px] tabular-nums">{b.mode === 'cap' && b.cap_usd != null ? `${fmtUsd(spend.remaining_usd)} left of ${fmtUsd(b.cap_usd)}` : b.threshold_usd != null && b.mode !== 'observe' ? `${b.mode} above ${fmtUsd(b.threshold_usd)}` : 'observe only'}</dd></div>
      {spend.unknown_takes > 0 && <div className="col-span-full text-[11.5px] text-amber-300">{spend.unknown_takes} take(s) have no catalog price — cost shown is incomplete.</div>}
    </dl>
  )
}

export function ProjectSettingsForm({ project, onSaved }: { project: Project; onSaved: (p: Project) => void }) {
  const { presets } = useFilm()
  const [s, setS] = useState<ProjectSettings>(project.settings)
  const [busy, setBusy] = useState(false)
  useEffect(() => setS(project.settings), [project.id, project.settings])
  const save = async (patch: Partial<ProjectSettings>) => {
    setBusy(true)
    try {
      const p = await film.patchProject(project.id, { settings: patch })
      setS(p.settings)
      onSaved(p)
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <label className="text-[12px] text-mute flex flex-col gap-1">{label}{children}</label>
  )
  return (
    <div className="grid sm:grid-cols-3 gap-2.5" data-testid="project-settings">
      <Row label="Aspect ratio">
        <select className="input" value={s.aspect_ratio} onChange={(e) => save({ aspect_ratio: e.target.value })}>
          {['16:9', '9:16', '4:3', '1:1', '2.39:1', '21:9', '4:5'].map((a) => <option key={a}>{a}</option>)}
        </select>
      </Row>
      <Row label="Target runtime (s)">
        <input className="input" type="number" min="1" value={s.target_runtime_s} onChange={(e) => setS({ ...s, target_runtime_s: Number(e.target.value) })} onBlur={() => save({ target_runtime_s: s.target_runtime_s })} />
      </Row>
      <Row label="Frame rate">
        <select className="input" value={s.fps} onChange={(e) => save({ fps: Number(e.target.value) })}>
          {[24, 25, 30, 48, 50, 60].map((f) => <option key={f} value={f}>{f} fps</option>)}
        </select>
      </Row>
      <Row label="Pacing profile">
        <select className="input" value={s.pacing_profile} onChange={(e) => save({ pacing_profile: e.target.value })}>
          {Object.entries(presets?.pacing_profiles ?? {}).map(([k, v]) => <option key={k} value={k}>{v.label} (~{v.base_s}s)</option>)}
        </select>
      </Row>
      <Row label="Pipeline template">
        <select className="input" value={s.pipeline_template} onChange={(e) => save({ pipeline_template: e.target.value })}>
          {Object.entries(presets?.pipeline_templates ?? {}).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      </Row>
      <Row label="Continuity mode">
        <select className="input" value={s.continuity_mode} onChange={(e) => save({ continuity_mode: e.target.value as ProjectSettings['continuity_mode'] })}>
          <option value="flexible">Flexible — intentional changes allowed</option>
          <option value="balanced">Balanced — warn on likely errors</option>
          <option value="strict">Strict — block canonical violations</option>
        </select>
      </Row>
      <Row label="Budget mode">
        <select className="input" value={s.budget.mode} onChange={(e) => save({ budget: { ...s.budget, mode: e.target.value as ProjectSettings['budget']['mode'] } })}>
          <option value="observe">Observe only</option>
          <option value="warn">Warn above threshold</option>
          <option value="approve">Require approval above threshold</option>
          <option value="cap">Hard cap</option>
        </select>
      </Row>
      <Row label="Threshold (USD)">
        <input className="input" type="number" step="0.5" min="0" value={s.budget.threshold_usd ?? ''} onChange={(e) => setS({ ...s, budget: { ...s.budget, threshold_usd: e.target.value === '' ? null : Number(e.target.value) } })} onBlur={() => save({ budget: s.budget })} />
      </Row>
      <Row label="Hard cap (USD)">
        <input className="input" type="number" step="1" min="0" value={s.budget.cap_usd ?? ''} placeholder="none" onChange={(e) => setS({ ...s, budget: { ...s.budget, cap_usd: e.target.value === '' ? null : Number(e.target.value) } })} onBlur={() => save({ budget: s.budget })} />
      </Row>
      <Row label="Visual style">
        <input className="input" value={s.visual_style} placeholder="gritty 35mm, neon noir…" onChange={(e) => setS({ ...s, visual_style: e.target.value })} onBlur={() => save({ visual_style: s.visual_style })} />
      </Row>
      <Row label="Tone">
        <input className="input" value={s.tone} placeholder="tense, intimate…" onChange={(e) => setS({ ...s, tone: e.target.value })} onBlur={() => save({ tone: s.tone })} />
      </Row>
      <label className="text-[12px] text-mute flex items-center gap-2 self-end">
        <input type="checkbox" checked={s.chain_frames} onChange={(e) => save({ chain_frames: e.target.checked })} /> chain frames by default
      </label>
      {busy && <Spinner />}
    </div>
  )
}

export function ProjectsPage() {
  const { project, projects, setProjectId, reloadProject, reloadProjects } = useFilm()
  const navigate = useNavigate()
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [logline, setLogline] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const board = useFetch(() => (project ? film.board(project.id) : Promise.resolve(null)), [project?.id])
  const gates = useFetch(() => (project ? film.gates(project.id) : Promise.resolve(null)), [project?.id])
  const spend = useFetch(() => (project ? film.costs(project.id) : Promise.resolve(null)), [project?.id])
  useEffect(() => {
    if (!project) return
    const t = window.setInterval(() => board.reload(), 8000)
    return () => window.clearInterval(t)
  }, [project?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const create = async () => {
    if (!title.trim()) return
    setBusy(true)
    try {
      const p = await film.createProject({ title: title.trim(), logline: logline || undefined })
      await reloadProjects()
      setProjectId(p.id)
      setCreating(false)
      setTitle('')
      setLogline('')
      toastSuccess('Project created — write or import your story next')
      navigate('/film/story')
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    if (!project) return
    try {
      await film.deleteProject(project.id)
      setProjectId(null)
      await reloadProjects()
      toastSuccess('Project deleted')
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const refresh = () => {
    reloadProject()
    board.reload()
    gates.reload()
    spend.reload()
  }

  return (
    <div className="space-y-4" data-testid="projects-page">
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-[12.5px] text-faint">Inspiration → Story → Assets → Director → Storyboard → Generation → Timeline → Export</p>
        <button className="btn-accent ml-auto" onClick={() => setCreating(true)}>+ New film project</button>
      </div>
      {creating && (
        <Modal title="New film project" onClose={() => setCreating(false)}>
          <div className="space-y-3">
            <label className="label block">Title<input className="input mt-1" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && create()} placeholder="Rainy City" /></label>
            <label className="label block">Logline (optional)<textarea className="input mt-1 min-h-[72px]" value={logline} onChange={(e) => setLogline(e.target.value)} placeholder="A courier loses a package in a city that never dries." /></label>
            <p className="text-[12px] text-faint">Try: “I want a 60-second cinematic scene in a rainy city.” — the Director drafts a production plan from it.</p>
            <div className="flex justify-end gap-2"><button className="btn" onClick={() => setCreating(false)}>Cancel</button><button className="btn-accent" onClick={create} disabled={busy || !title.trim()}>{busy ? <Spinner /> : 'Create'}</button></div>
          </div>
        </Modal>
      )}
      {projects.length === 0 && !creating && (
        <EmptyState icon="🎬" title="No film projects yet" hint="Create one, paste a script or a one-line idea, and let the Director propose a plan." action={<button className="btn-accent" onClick={() => setCreating(true)}>Create the first project</button>} />
      )}
      {projects.length > 0 && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2.5">
          {projects.map((p) => (
            <button key={p.id} className={`card p-3 text-left hover:border-ember/60 ${project?.id === p.id ? 'border-ember' : ''}`} onClick={() => setProjectId(p.id)} data-project-id={p.id}>
              <div className="flex items-center gap-2"><span className="font-display font-medium text-[14.5px] truncate">{p.title}</span><span className="chip !text-[10px] ml-auto">{p.status}</span></div>
              <p className="text-[12px] text-mute line-clamp-2 mt-1 min-h-[2.4em]">{p.logline || p.synopsis || 'No logline yet.'}</p>
              <p className="text-[11px] text-faint mt-1.5">{p.scene_count} scenes · {p.shot_count} shots · {p.settings.aspect_ratio} · updated {timeAgo(p.updated_at)}</p>
            </button>
          ))}
        </div>
      )}
      {project && (
        <div className="space-y-4 fade-in" data-testid="project-detail">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="font-display font-medium text-[17px]">{project.title}</h2>
            <span className="chip">{project.status}</span>
            <div className="ml-auto flex gap-1.5">
              <button className="btn text-[12px]" onClick={() => navigate('/film/story')}>Story</button>
              <button className="btn text-[12px]" onClick={() => navigate('/film/director')}>Director</button>
              <button className="btn text-[12px]" onClick={() => navigate('/film/storyboard')}>Storyboard</button>
              <button className="btn-danger text-[12px]" onClick={() => setConfirmDelete(true)}>Delete</button>
            </div>
          </div>
          <section className="card p-3.5 space-y-2">
            <h3 className="font-display text-[14px]">Backlot — live production board</h3>
            {board.data ? <BacklotBoard board={board.data} /> : <Spinner />}
          </section>
          <div className="grid lg:grid-cols-2 gap-3">
            <section className="card p-3.5 space-y-2">
              <h3 className="font-display text-[14px]">Approval gates</h3>
              {gates.data ? <GatesPanel projectId={project.id} gates={gates.data.gates} onChanged={refresh} /> : <Spinner />}
            </section>
            <section className="card p-3.5 space-y-2">
              <h3 className="font-display text-[14px]">Cost</h3>
              {spend.data ? <CostSummary spend={spend.data} /> : <Spinner />}
            </section>
          </div>
          <section className="card p-3.5 space-y-2">
            <h3 className="font-display text-[14px]">Project settings</h3>
            <ProjectSettingsForm project={project} onSaved={() => refresh()} />
          </section>
          <section className="card p-3.5 space-y-2">
            <h3 className="font-display text-[14px]">Decision log</h3>
            <DecisionLog projectId={project.id} />
          </section>
        </div>
      )}
      {confirmDelete && project && <ConfirmModal title={`Delete “${project.title}”?`} message="Scenes, shots, takes, audio and exports of this project are removed. Assets stay in the library." onConfirm={remove} onClose={() => setConfirmDelete(false)} />}
    </div>
  )
}
