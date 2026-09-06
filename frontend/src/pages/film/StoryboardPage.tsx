// Storyboard (spec §14–§22, H–K, Z, AA, AC, AD, AF): scene navigator ·
// image-first shot grid / contact sheet · shot inspector with basic /
// advanced / expert drawers · proportional strip. Every AI change is a
// proposal; locked properties are never touched.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { AssetPicker, AssetThumb, PickedAsset } from '../../components/film/AssetPicker'
import { CameraControls } from '../../components/film/CameraControls'
import { FootageModal } from '../../components/film/FootageModal'
import { LightingPanel } from '../../components/film/LightingPanel'
import { ShotDiagram, ShotTypeLibrary } from '../../components/film/ShotTypeLibrary'
import { Strip } from '../../components/film/TimingPanel'
import { Modal, Spinner } from '../../components/Primitives'
import { timeAgo } from '../../lib/format'
import { Capabilities, errorMessage, film, fmtUsd, inspirationToShotPatch, Proposal, Scene, Shot, ShotContext, Spend, Take, Timeline, Warning } from '../../lib/film'
import { clearInspirationContext, InspirationContext, loadInspirationContext } from '../../lib/inspiration'
import { toastError, toastSuccess } from '../../lib/toast'
import { GalleryImport } from './AssetsPage'
import { ProposalCard } from './DirectorPage'
import { useFilm } from './FilmPage'

const STRATEGY_LABEL: Record<string, string> = { ai_video: 'AI video', image_animation: 'Image + animation', user_footage: 'User footage', stock: 'Stock footage', archival: 'Archival', motion_graphics: 'Motion graphics', screen_recording: 'Screen recording', talking_head: 'Talking head', still: 'Still image' }
const STATUS_DOT: Record<string, string> = { planned: 'bg-faint', framed: 'bg-mute', generated: 'bg-emerald-400', approved: 'bg-emerald-300', needs_repair: 'bg-red-400' }
const SHOT_LOCKS = ['camera', 'lighting', 'environment', 'color', 'motion', 'action', 'expression', 'pose', 'timing', 'media_strategy']
const REGEN_GROUPS = ['face', 'hair', 'body', 'clothing', 'expression', 'pose', 'location', 'camera', 'lighting', 'environment', 'color', 'motion', 'action', 'style', 'props']

export function StoryboardPage() {
  const { project, reloadProject, presets, reloadPresets } = useFilm()
  const navigate = useNavigate()
  const location = useLocation() as { state?: { sceneId?: number; shotId?: number } }
  const [params] = useSearchParams()
  const scenes = project?.scenes ?? []
  const [sceneId, setSceneId] = useState<number | null>(location.state?.sceneId ?? null)
  const [shotId, setShotId] = useState<number | null>(location.state?.shotId ?? null)
  const [mode, setMode] = useState<'grid' | 'contact'>('grid')
  const [density, setDensity] = useState<2 | 4 | 6 | 9>(4)
  const [tl, setTl] = useState<Timeline | null>(null)
  const [spend, setSpend] = useState<Spend | null>(null)
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [continuity, setContinuity] = useState<{ counts: Record<string, number>; mode: string; blocking: boolean } | null>(null)
  const [inspiration, setInspiration] = useState<InspirationContext | null>(() => (params.get('inspiration') ? loadInspirationContext() : null))
  const scene = scenes.find((s) => s.id === sceneId) ?? (location.state?.shotId ? scenes.find((s) => s.shots.some((sh) => sh.id === location.state!.shotId)) : undefined) ?? scenes[0]
  const shot = scene?.shots.find((s) => s.id === shotId) ?? null
  const refreshAux = useCallback(() => {
    if (!project) return
    film.timeline(project.id).then(setTl).catch(() => undefined)
    film.costs(project.id).then(setSpend).catch(() => undefined)
  }, [project?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    refreshAux()
    film.capabilities().then(setCaps).catch(() => undefined)
  }, [refreshAux])
  useEffect(() => {
    if (!project) return
    const t = window.setInterval(() => reloadProject(), 6000)
    return () => window.clearInterval(t)
  }, [project?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const refresh = async () => {
    await reloadProject()
    refreshAux()
  }
  if (!project || !presets) return null
  const runContinuity = async () => {
    try {
      const r = await film.continuity(project.id)
      setContinuity(r)
      await reloadProject()
      toastSuccess(`Continuity: ${r.counts.block} blocking, ${r.counts.warn} warnings, ${r.counts.info} notes (${r.mode})`)
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const addShot = async () => {
    if (!scene) return
    try {
      const sh = await film.createShot(scene.id, { title: `Shot ${scene.shots.length + 1}` })
      await refresh()
      setShotId(sh.id)
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const addScene = async () => {
    try {
      const sc = await film.createScene(project.id, { title: `Scene ${scenes.length + 1}` })
      await refresh()
      setSceneId(sc.id)
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const reorder = async (ids: number[]) => {
    if (!scene) return
    try {
      await film.reorderShots(scene.id, ids)
      await refresh()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  return (
    <div className="space-y-3" data-testid="storyboard-page">
      {inspiration && shot && (
        <div className="card !bg-well p-2.5 text-[12.5px] flex flex-wrap items-center gap-2 fade-in" data-testid="inspiration-banner">
          <span>✦ Inspiration from <span className="text-fg">{inspiration.platform}</span>{inspiration.author ? ` · @${inspiration.author}` : ''}{inspiration.inspiration_score != null ? ` · score ${Math.round(inspiration.inspiration_score)}` : ''}</span>
          <span className="text-faint">{inspirationToShotPatch(inspiration).summary.join(' · ') || 'nothing detected to apply'}</span>
          <button className="btn-accent text-[12px] ml-auto" onClick={async () => { try { await film.patchShot(shot.id, { overrides: { ...shot.overrides, ...inspirationToShotPatch(inspiration).overrides } }); toastSuccess(`Applied to shot ${shot.label} with attribution`); await refresh() } catch (e) { toastError(errorMessage(e)) } }}>Apply to shot {shot.label}</button>
          <button className="btn-ghost text-[12px]" onClick={() => { clearInspirationContext(); setInspiration(null) }}>Dismiss</button>
        </div>
      )}
      {inspiration && !shot && <p className="text-[12.5px] text-faint">✦ Inspiration context loaded — select a shot to apply it.</p>}
      <div className="grid lg:grid-cols-[210px_1fr] xl:grid-cols-[210px_1fr_400px] gap-3">
        <aside className="space-y-2">
          <div className="flex items-center gap-1"><h3 className="font-display text-[13.5px]">Scenes</h3><button className="btn-ghost text-[12px] ml-auto" onClick={addScene}>+ scene</button></div>
          {scenes.length === 0 && <p className="text-[12px] text-faint">No scenes yet — import a script or direct the story.</p>}
          {scenes.map((sc) => {
            const t = tl?.scenes.find((x) => x.id === sc.id)
            const warn = sc.shots.reduce((n, sh) => n + sh.warnings.filter((w) => w.severity !== 'info').length, 0)
            return (
              <button key={sc.id} className={`w-full text-left card p-2 ${scene?.id === sc.id ? 'border-ember' : ''}`} onClick={() => { setSceneId(sc.id); setShotId(null) }} data-scene-nav={sc.id}>
                <div className="flex items-center gap-1.5 text-[12.5px]"><span className="font-mono text-faint">{String(sc.number).padStart(2, '0')}</span><span className="truncate font-medium">{sc.title}</span>{sc.approved && <span className="text-emerald-300 text-[10px] ml-auto">✓</span>}</div>
                <div className="text-[10.5px] text-faint flex gap-1.5">{sc.shots.length} shots{t ? ` · ${t.tc_out.replace(/^00:/, '')}` : ''}{warn > 0 && <span className="text-amber-300">⚠ {warn}</span>}</div>
                {t && t.gap_after_s != null && <div className="text-[10px] text-faint">gap after {t.gap_after_s}s{t.gap_inherited ? '' : ' (override)'}</div>}
              </button>
            )
          })}
          <div className="card p-2 text-[11.5px] space-y-1">
            <button className="btn w-full text-[12px]" onClick={runContinuity}>Check continuity</button>
            {continuity && <div className="text-faint">{continuity.mode}: {continuity.counts.block} block · {continuity.counts.warn} warn · {continuity.counts.info} info</div>}
            {spend && <div className="text-faint">spent {fmtUsd(spend.spent_usd)} · est {fmtUsd(spend.estimated_usd)}</div>}
            {caps && !caps.modes.some((m) => m.key === 'text_to_video' && m.supported) && <div className="text-amber-300">No video provider connected — takes will fail until one is set up in Settings → AI providers.</div>}
          </div>
        </aside>
        <main className="min-w-0 space-y-2">
          {!scene ? <p className="text-[12.5px] text-faint card p-6 text-center">Create or select a scene.</p> : (
            <>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="font-display text-[15px]">{String(scene.number).padStart(2, '0')} · {scene.title}</h2>
                <span className="text-[11.5px] text-faint">{scene.defaults?.location_name ?? ''} {scene.defaults?.time_of_day ?? ''} {scene.defaults?.weather ?? ''}</span>
                <div className="ml-auto flex items-center gap-1">
                  <button className={`chip ${mode === 'grid' ? '!border-ember text-fg' : ''}`} onClick={() => setMode('grid')}>grid</button>
                  <button className={`chip ${mode === 'contact' ? '!border-ember text-fg' : ''}`} onClick={() => setMode('contact')}>contact sheet</button>
                  {mode === 'grid' && ([2, 4, 6, 9] as const).map((d) => <button key={d} className={`chip !px-1.5 ${density === d ? '!border-ember text-fg' : ''}`} onClick={() => setDensity(d)} aria-label={`${d} panels`}>{d}</button>)}
                  <button className="btn text-[12px]" onClick={addShot}>+ shot</button>
                  <button className="btn text-[12px]" onClick={async () => { try { await film.directScene(scene.id); toastSuccess('Scene proposal ready in Director'); } catch (e) { toastError(errorMessage(e)) } }}>Direct scene</button>
                  <button className="btn text-[12px]" title="Open the sequence editor — first open builds the timeline from this storyboard" onClick={() => navigate('/film/editor', { state: { shotId } })} data-testid="open-in-editor">🎬 Editor</button>
                </div>
              </div>
              {mode === 'grid' ? (
                <ShotGrid scene={scene} density={density} selected={shotId} onSelect={setShotId} onReorder={reorder} tl={tl} presets={presets} />
              ) : (
                <ContactSheet project={project} scene={scene} tl={tl} spend={spend} onSelect={setShotId} onChanged={refresh} />
              )}
              {tl && <div className="card p-2"><Strip tl={tl} onShotDuration={(id, s) => film.patchShot(id, { duration_s: s }).then(refresh).catch((e) => toastError(errorMessage(e)))} onSelectShot={(id) => { const sc = scenes.find((s) => s.shots.some((sh) => sh.id === id)); if (sc) setSceneId(sc.id); setShotId(id) }} selectedShotId={shotId} /></div>}
            </>
          )}
        </main>
        <aside className="min-w-0">
          {shot && scene ? (
            <ShotInspector key={shot.id} shot={shot} scene={scene} caps={caps} onChanged={refresh} onClose={() => setShotId(null)} onFavoriteShotType={(k) => { const favs = presets.favorites.includes(k) ? presets.favorites.filter((x) => x !== k) : [...presets.favorites, k]; film.savePresets({ favorites: favs }).then(reloadPresets).catch((e) => toastError(errorMessage(e))) }} />
          ) : (
            <div className="card p-4 text-[12.5px] text-faint">Select a shot to inspect it. Double-click a card to open its takes.</div>
          )}
        </aside>
      </div>
    </div>
  )
}

// ------------------------------------------------------------ shot cards --
function ShotCard({ sh, tl, presets, selected, onSelect, draggable, onDragStart, onDrop }: { sh: Shot; tl: Timeline | null; presets: NonNullable<ReturnType<typeof useFilm>['presets']>; selected: boolean; onSelect: () => void; draggable?: boolean; onDragStart?: () => void; onDrop?: () => void }) {
  const st = presets.shot_types.find((x) => x.key === sh.overrides?.shot_type)
  const t = tl?.scenes.flatMap((s) => s.shots).find((x) => x.id === sh.id)
  const warn = sh.warnings.filter((w) => w.severity !== 'info')
  const chars = sh.assets.filter((a) => a.type === 'character')
  const loc = sh.assets.find((a) => a.type === 'location')
  const media = sh.selected_take
  return (
    <div
      className={`card p-2 text-left cursor-pointer select-none ${selected ? 'border-ember' : 'hover:border-ember/50'}`}
      onClick={onSelect}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
      data-shot-card={sh.id}
    >
      <div className="relative aspect-video rounded-el overflow-hidden bg-well flex items-center justify-center">
        {media?.media_url && media.kind !== 'image' && !/\.(png|jpe?g|webp)$/i.test(media.media_url) ? (
          <video src={media.media_url} poster={sh.thumb_url ?? undefined} muted className="w-full h-full object-cover" onMouseEnter={(e) => e.currentTarget.play().catch(() => undefined)} onMouseLeave={(e) => { e.currentTarget.pause(); e.currentTarget.currentTime = 0 }} />
        ) : sh.thumb_url ? (
          <img src={sh.thumb_url} alt="" className="w-full h-full object-cover" loading="lazy" />
        ) : sh.start_frame?.path ? (
          <img src={`/film-media/${sh.start_frame.path.replace(/^film\//, '')}`} alt="" className="w-full h-full object-cover opacity-80" />
        ) : st ? (
          <ShotDiagram st={st} size={160} />
        ) : (
          <span className="text-faint text-[11px]">no media</span>
        )}
        <span className="absolute top-1 left-1 font-mono text-[10.5px] bg-ink/80 px-1 rounded">{sh.label}</span>
        <span className="absolute top-1 right-1 flex items-center gap-1">
          {sh.locks.length > 0 && <span className="bg-ink/80 px-1 rounded text-[10px]" title={`locked: ${sh.locks.join(', ')}`}>🔒{sh.locks.length}</span>}
          {sh.approved && <span className="bg-ink/80 px-1 rounded text-[10px] text-emerald-300">✓</span>}
          <span className={`w-2 h-2 rounded-full ${STATUS_DOT[sh.status] ?? 'bg-faint'}`} title={sh.status} />
        </span>
        {t?.transition && t.transition.kind !== 'cut' && <span className="absolute bottom-1 right-1 bg-ink/80 px-1 rounded text-[10px]">{t.transition.kind.replace('_', ' ')} →</span>}
        {warn.length > 0 && <span className="absolute bottom-1 left-1 bg-ink/80 px-1 rounded text-[10px] text-amber-300" title={warn.map((w) => w.message).join('\n')}>⚠ {warn.length}</span>}
      </div>
      <div className="mt-1.5 flex items-center gap-1.5 text-[12px]">
        <span className="chip !text-[10px]" title={st?.label}>{st?.abbr ?? '—'}</span>
        <span className="truncate flex-1">{sh.title ?? sh.overrides?.action?.slice(0, 40) ?? '—'}</span>
        <span className="text-faint tabular-nums">{sh.duration_s}s</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-1 text-[10.5px]">
        {chars.map((c) => <span key={c.asset_id} className="chip !text-[10px]" title={`${c.name} ${c.version_label}${c.source === 'shot' ? ' (pinned)' : ''}`}>👤 {c.name}{!c.is_current ? ' ·v' + c.version : ''}</span>)}
        {loc && <span className="chip !text-[10px]">📍 {loc.name}</span>}
        <span className="text-faint ml-auto">{STRATEGY_LABEL[sh.media_strategy] ?? sh.media_strategy}{sh.take_count ? ` · ${sh.take_count} take${sh.take_count === 1 ? '' : 's'}` : ''}</span>
      </div>
    </div>
  )
}

function ShotGrid({ scene, density, selected, onSelect, onReorder, tl, presets }: { scene: Scene; density: number; selected: number | null; onSelect: (id: number) => void; onReorder: (ids: number[]) => void; tl: Timeline | null; presets: NonNullable<ReturnType<typeof useFilm>['presets']> }) {
  const [dragId, setDragId] = useState<number | null>(null)
  const cols = { 2: 'grid-cols-1 sm:grid-cols-2', 4: 'grid-cols-2 lg:grid-cols-2 xl:grid-cols-4', 6: 'grid-cols-2 md:grid-cols-3 xl:grid-cols-3', 9: 'grid-cols-3' }[density as 2 | 4 | 6 | 9]
  if (scene.shots.length === 0) return <p className="text-[12.5px] text-faint card p-6 text-center">No shots in this scene yet. Add one, or let the Director break the scene down.</p>
  return (
    <div className={`grid ${cols} gap-2`} data-testid="shot-grid">
      {scene.shots.map((sh) => (
        <ShotCard key={sh.id} sh={sh} tl={tl} presets={presets} selected={selected === sh.id} onSelect={() => onSelect(sh.id)} draggable onDragStart={() => setDragId(sh.id)} onDrop={() => {
          if (dragId == null || dragId === sh.id) return
          const ids = scene.shots.map((x) => x.id)
          const from = ids.indexOf(dragId)
          const to = ids.indexOf(sh.id)
          ids.splice(from, 1)
          ids.splice(to, 0, dragId)
          setDragId(null)
          onReorder(ids)
        }} />
      ))}
    </div>
  )
}

function ContactSheet({ project, scene, tl, spend, onSelect, onChanged }: { project: { id: number }; scene: Scene; tl: Timeline | null; spend: Spend | null; onSelect: (id: number) => void; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const t = tl?.scenes.find((x) => x.id === scene.id)
  const approveAll = async (status: 'approved' | 'rejected') => {
    setBusy(true)
    try {
      await film.decideGate(project.id, 'storyboard', { status, item_ids: status === 'rejected' ? scene.shots.map((s) => s.id) : [] })
      toastSuccess(`Storyboard ${status}`)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const regenAll = async () => {
    setBusy(true)
    try {
      const j = await film.startRun(project.id, { shot_ids: scene.shots.map((s) => s.id), force: true, skip_done: false })
      toastSuccess(`Regenerating ${j.progress.total} shot(s)`)
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="card p-2 space-y-1.5" data-testid="contact-sheet">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="font-display">Contact sheet — {scene.title}</span>
        <span className="text-faint">{t ? `${t.tc_in} → ${t.tc_out}` : ''}</span>
        <div className="ml-auto flex gap-1"><button className="btn text-[11.5px] py-0.5" onClick={() => approveAll('approved')} disabled={busy}>Approve storyboard</button><button className="btn-ghost text-[11.5px] py-0.5" onClick={() => approveAll('rejected')} disabled={busy}>Reject scene shots</button><button className="btn-ghost text-[11.5px] py-0.5" onClick={regenAll} disabled={busy}>Regenerate all</button></div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11.5px] min-w-[760px]">
          <thead className="text-faint text-left"><tr><th className="p-1">#</th><th className="p-1">frame</th><th className="p-1">type</th><th className="p-1">dur</th><th className="p-1">after</th><th className="p-1">assets</th><th className="p-1">prompt</th><th className="p-1">est / actual</th><th className="p-1">QA</th><th className="p-1">approved</th></tr></thead>
          <tbody>
            {scene.shots.map((sh) => {
              const ts = t?.shots.find((x) => x.id === sh.id)
              return (
                <tr key={sh.id} className="border-t border-line hover:bg-well cursor-pointer" onClick={() => onSelect(sh.id)}>
                  <td className="p-1 font-mono">{sh.label}</td>
                  <td className="p-1">{sh.thumb_url ? <img src={sh.thumb_url} alt="" className="h-10 rounded-el" /> : <span className="text-faint">—</span>}</td>
                  <td className="p-1">{sh.overrides?.shot_type?.replace(/_/g, ' ') ?? '—'}</td>
                  <td className="p-1 tabular-nums">{sh.duration_s}s</td>
                  <td className="p-1 text-faint">{ts?.transition ? ts.transition.kind.replace('_', ' ') : t && sh.position === scene.shots.length - 1 && t.gap_after_s != null ? `gap ${t.gap_after_s}s` : 'cut'}</td>
                  <td className="p-1">{sh.assets.map((a) => a.name).join(', ')}</td>
                  <td className="p-1 max-w-[220px] truncate" title={sh.overrides?.action ?? ''}>{sh.overrides?.action ?? sh.title ?? ''}</td>
                  <td className="p-1 tabular-nums">{fmtUsd(sh.selected_take?.cost_estimate)} / {fmtUsd(sh.selected_take?.cost_actual)}{spend?.by_shot[String(sh.id)] != null ? ` (Σ ${fmtUsd(spend.by_shot[String(sh.id)])})` : ''}</td>
                  <td className={`p-1 ${sh.qa?.verdict === 'FAIL' ? 'text-red-300' : sh.qa?.verdict === 'WARN' ? 'text-amber-300' : sh.qa ? 'text-emerald-300' : 'text-faint'}`}>{sh.qa?.verdict ?? '—'}</td>
                  <td className="p-1">{sh.approved ? '✓' : ''}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// -------------------------------------------------------------- inspector --
function ShotInspector({ shot, scene, caps, onChanged, onClose, onFavoriteShotType }: { shot: Shot; scene: Scene; caps: Capabilities | null; onChanged: () => Promise<void>; onClose: () => void; onFavoriteShotType: (k: string) => void }) {
  const { project, presets } = useFilm()
  const [level, setLevel] = useState<{ advanced: boolean; expert: boolean }>({ advanced: false, expert: false })
  const [ov, setOv] = useState<Record<string, any>>(shot.overrides ?? {})
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [picker, setPicker] = useState<'characters' | 'location' | 'props' | null>(null)
  const [shotTypes, setShotTypes] = useState(false)
  const [takes, setTakes] = useState<Take[] | null>(null)
  const [ctx, setCtx] = useState<ShotContext | null>(null)
  const [note, setNote] = useState('')
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [regen, setRegen] = useState<{ change: string[]; preserve: string[]; instruction: string } | null>(null)
  const [footage, setFootage] = useState(false)
  const [gallery, setGallery] = useState<'start_frame' | 'end_frame' | null>(null)
  const [card, setCard] = useState<{ text: string; subtitle: string; style: string } | null>(null)
  const [compare, setCompare] = useState<any>(null)
  const [blocked, setBlocked] = useState<{ message: string; budget?: any } | null>(null)
  useEffect(() => {
    setOv(shot.overrides ?? {})
    setDirty(false)
  }, [shot.id, shot.overrides])
  const loadTakes = useCallback(() => film.takes(shot.id).then((r) => setTakes(r.takes)).catch(() => undefined), [shot.id])
  useEffect(() => {
    loadTakes()
    const t = window.setInterval(loadTakes, 5000)
    return () => window.clearInterval(t)
  }, [loadTakes])
  useEffect(() => {
    if (level.expert) film.shotContext(shot.id).then(setCtx).catch(() => undefined)
  }, [level.expert, shot.id, shot.overrides])
  if (!project || !presets) return null
  const setO = (patch: Record<string, any>) => {
    setOv((o) => ({ ...o, ...patch }))
    setDirty(true)
  }
  const setGroup = (g: string, patch: Record<string, any>) => setO({ [g]: { ...(ov[g] ?? {}), ...patch } })
  const patchShot = async (body: Parameters<typeof film.patchShot>[1], ok?: string) => {
    try {
      await film.patchShot(shot.id, body)
      if (ok) toastSuccess(ok)
      await onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const save = () => patchShot({ overrides: ov }, 'Shot saved').then(() => setDirty(false))
  const generate = async (body: Parameters<typeof film.createTake>[1], label: string) => {
    if (dirty) await patchShot({ overrides: ov })
    setBusy(label)
    setBlocked(null)
    try {
      const r = await film.createTake(shot.id, body)
      toastSuccess(`${label} queued on ${r.take.provider} · ${r.take.model_family} · ${r.take.mode?.replace(/_/g, ' ')} · ${fmtUsd(r.take.cost_estimate)}`)
      await onChanged()
      loadTakes()
    } catch (e) {
      const detail = (e as any)?.detail
      setBlocked({ message: errorMessage(e), budget: detail?.budget })
    } finally {
      setBusy(null)
    }
  }
  const frameAction = async (which: 'start_frame' | 'end_frame', body: Parameters<typeof film.setFrame>[2]) => {
    try {
      await film.setFrame(shot.id, which, body)
      await onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const toggleLock = (k: string) => patchShot({ locks: shot.locks.includes(k) ? shot.locks.filter((x) => x !== k) : [...shot.locks, k] })
  const pinned = (picker: 'characters' | 'location' | 'props') => shot.assets.filter((a) => (picker === 'characters' ? a.type === 'character' : picker === 'location' ? a.type === 'location' : ['prop', 'vehicle', 'outfit', 'style'].includes(a.type))).map<PickedAsset>((a) => ({ asset_id: a.asset_id, version_id: a.version_id, role: a.role, name: a.name, type: a.type, thumb_url: a.thumb_url, version_label: a.version_label }))
  const applyPick = async (kind: 'characters' | 'location' | 'props', picked: PickedAsset[]) => {
    setPicker(null)
    const keepOthers = shot.assets.filter((a) => a.source === 'shot' && !pinned(kind).some((p) => p.asset_id === a.asset_id)).map((a) => ({ asset_id: a.asset_id, version_id: a.version_id, role: a.role }))
    const wanted = [...keepOthers, ...picked.map((p) => ({ asset_id: p.asset_id, version_id: p.version_id ?? undefined, role: p.role }))]
    await patchShot({ assets: wanted, overrides: kind === 'characters' ? { ...ov, characters: picked.map((p) => p.name) } : undefined }, 'Assets pinned to this shot')
  }
  const st = presets.shot_types.find((x) => x.key === ov.shot_type)
  const videoModes = caps?.modes.filter((m) => m.kind === 'video' && m.supported) ?? []
  const imageModes = caps?.modes.filter((m) => m.kind === 'image' && m.supported) ?? []
  const blockingWarnings = shot.warnings.filter((w) => w.severity === 'block')
  const frameUrl = (f: Shot['start_frame']) => (f?.path ? (f.path.startsWith('film/') ? `/film-media/${f.path.replace(/^film\//, '')}` : `/${f.path}`) : null)
  const selected = takes?.find((t) => t.id === shot.selected_take_id) ?? shot.selected_take
  return (
    <div className="card p-3 space-y-3 max-h-[calc(100vh-120px)] overflow-y-auto" data-testid="shot-inspector">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[11px] text-faint">{shot.label}</span>
        <input className="input !h-8 font-display flex-1" defaultValue={shot.title ?? ''} placeholder="Shot title" onBlur={(e) => e.target.value !== (shot.title ?? '') && patchShot({ title: e.target.value })} />
        <span className={`w-2 h-2 rounded-full ${STATUS_DOT[shot.status]}`} title={shot.status} />
        <button className="btn-ghost px-1" onClick={onClose} aria-label="Close inspector">✕</button>
      </div>
      {/* preview + takes */}
      <div className="rounded-el overflow-hidden bg-ink aspect-video flex items-center justify-center relative">
        {selected?.media_url ? (selected.kind === 'image' || /\.(png|jpe?g|webp)$/i.test(selected.media_url) ? <img src={selected.media_url} alt="" className="max-h-full" /> : <video src={selected.media_url} controls className="w-full h-full" />) : frameUrl(shot.start_frame) ? <img src={frameUrl(shot.start_frame)!} alt="" className="max-h-full opacity-80" /> : st ? <ShotDiagram st={st} size={360} /> : <span className="text-faint text-[12px]">no media yet</span>}
        {selected && <span className="absolute bottom-1 left-1 bg-ink/80 px-1.5 rounded text-[10.5px]">take {selected.number} · {selected.provider}{selected.model_family ? ` · ${selected.model_family}` : ''} · {fmtUsd(selected.cost_actual ?? selected.cost_estimate)}{selected.qa ? ` · QA ${selected.qa.verdict}` : ''}</span>}
      </div>
      {takes && takes.length > 0 && (
        <div className="flex gap-1.5 overflow-x-auto pb-1" data-testid="takes">
          {takes.map((t) => (
            <div key={t.id} className={`shrink-0 w-24 rounded-el border p-1 text-[10.5px] ${t.id === shot.selected_take_id ? 'border-ember' : 'border-line'}`} data-take-id={t.id}>
              <div className="aspect-video bg-well rounded-el overflow-hidden flex items-center justify-center">{t.thumb_url ? <img src={t.thumb_url} alt="" className="w-full h-full object-cover" /> : t.status === 'failed' ? <span className="text-red-300">✕</span> : t.status === 'succeeded' || t.status === 'imported' ? '·' : <Spinner />}</div>
              <div className="truncate">T{t.number} · {t.kind.replace('_', ' ')}</div>
              <div className="text-faint truncate" title={t.error ?? t.decision?.reason ?? ''}>{t.status}{t.qa ? ` · ${t.qa.verdict}` : ''}</div>
              <div className="flex gap-0.5 mt-0.5">
                {['succeeded', 'imported'].includes(t.status) && t.kind !== 'start_frame' && t.kind !== 'end_frame' && t.id !== shot.selected_take_id && <button className="btn-ghost text-[10px] px-1 py-0" onClick={() => film.selectTake(t.id).then(onChanged).then(loadTakes)}>use</button>}
                {shot.selected_take_id && t.id !== shot.selected_take_id && ['succeeded', 'imported'].includes(t.status) && <button className="btn-ghost text-[10px] px-1 py-0" onClick={() => film.compareTakes(shot.selected_take_id!, t.id).then(setCompare)}>vs</button>}
              </div>
            </div>
          ))}
        </div>
      )}
      {compare && (
        <div className="card !bg-well p-2 text-[11.5px] fade-in">
          <div className="flex items-center justify-between"><span>Take {compare.a.number} vs take {compare.b.number}</span><button className="btn-ghost text-[11px]" onClick={() => setCompare(null)}>close</button></div>
          <div className="grid grid-cols-2 gap-1 mt-1">{[compare.a, compare.b].map((x) => <div key={x.id} className="aspect-video bg-ink rounded-el overflow-hidden">{x.thumb_url && <img src={x.thumb_url} alt="" className="w-full h-full object-cover" />}</div>)}</div>
          <ul className="mt-1 space-y-0.5">{Object.entries(compare.differences as Record<string, { a: unknown; b: unknown }>).map(([k, v]) => <li key={k}><span className="text-faint">{k}:</span> {typeof v.a === 'object' ? JSON.stringify(v.a) : String(v.a)} → {typeof v.b === 'object' ? JSON.stringify(v.b) : String(v.b)}</li>)}</ul>
        </div>
      )}
      {blockingWarnings.length > 0 && <div className="card !bg-well p-2 text-[11.5px] text-red-300">Strict continuity blocks generation: {blockingWarnings.map((w) => w.message).join(' ')} <label className="text-fg ml-1"><input type="checkbox" checked={Boolean(ov.continuity_override)} onChange={(e) => patchShot({ overrides: { ...ov, continuity_override: e.target.checked } })} /> override for this shot</label></div>}
      {shot.warnings.filter((w) => w.severity !== 'block').length > 0 && (
        <details className="text-[11.5px]"><summary className="text-amber-300 cursor-pointer">⚠ {shot.warnings.length} continuity note(s)</summary>
          <ul className="mt-1 space-y-0.5">{shot.warnings.map((w: Warning, i) => <li key={i} className={w.severity === 'warn' ? 'text-amber-300' : 'text-faint'}>{w.message}{w.fix && <span className="text-faint"> · {w.fix}</span>}{w.heuristic && <span className="text-faint"> (heuristic)</span>}</li>)}</ul>
        </details>
      )}
      {/* generate */}
      <div className="flex flex-wrap gap-1.5 items-center">
        {['ai_video', 'image_animation', 'talking_head'].includes(shot.media_strategy) ? (
          <button className="btn-accent" onClick={() => generate({ kind: 'video' }, 'Video take')} disabled={busy != null || !videoModes.length} title={!videoModes.length ? 'No connected provider declares video generation' : ''} data-testid="generate-video">{busy === 'Video take' ? <Spinner /> : 'Generate video'}</button>
        ) : shot.media_strategy === 'still' ? (
          <button className="btn-accent" onClick={async () => { setBusy('still'); try { await film.still(shot.id, { source: 'start_frame' }); toastSuccess('Still rendered as a take'); await onChanged(); loadTakes() } catch (e) { toastError(errorMessage(e)) } finally { setBusy(null) } }} disabled={busy != null || !shot.start_frame?.path} title={!shot.start_frame?.path ? 'Set a start frame first' : ''}>{busy === 'still' ? <Spinner /> : 'Render still (Ken Burns)'}</button>
        ) : shot.media_strategy === 'motion_graphics' ? (
          <button className="btn-accent" onClick={() => setCard({ text: shot.title ?? '', subtitle: '', style: 'title' })}>Make a title card</button>
        ) : (
          <button className="btn-accent" onClick={() => setFootage(true)}>Find footage</button>
        )}
        <button className="btn text-[12px]" onClick={() => setRegen({ change: [], preserve: [], instruction: '' })} disabled={!selected}>Repair / regenerate…</button>
        <button className="btn text-[12px]" onClick={() => setFootage(true)}>Footage</button>
        <label className="btn text-[12px] cursor-pointer">Import file<input type="file" accept="video/*,image/*" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; try { await film.importTake(shot.id, f); toastSuccess('Imported as a take'); await onChanged(); loadTakes() } catch (err) { toastError(errorMessage(err)) } }} /></label>
        <select className="input !h-8 !w-40 text-[12px] ml-auto" value={shot.media_strategy} onChange={(e) => patchShot({ media_strategy: e.target.value })} aria-label="Media strategy" data-testid="media-strategy">{Object.entries(STRATEGY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      </div>
      {blocked && <div className="card !bg-well p-2 text-[11.5px] text-amber-300">{blocked.message}{blocked.budget?.requires_approval && <button className="btn ml-2 text-[11px] py-0.5" onClick={() => generate({ kind: 'video', approve_cost: true }, 'Video take')}>Approve {fmtUsd(blocked.budget.amount_usd)} and generate</button>}</div>}
      {/* basic */}
      <section className="space-y-2">
        <label className="label block">Action / prompt<textarea className="input mt-1 min-h-[70px] text-[12.5px]" value={ov.action ?? ''} placeholder="What happens in this shot?" onChange={(e) => setO({ action: e.target.value })} data-testid="shot-action" /></label>
        <div className="flex items-center gap-2 flex-wrap text-[12px]">
          <span className="label">Characters</span>
          {shot.assets.filter((a) => a.type === 'character').map((a) => <span key={a.asset_id} className={`chip ${a.source === 'shot' ? 'text-fg' : ''}`} title={`${a.version_label} · ${a.source === 'shot' ? 'pinned to shot' : 'from scene'}`}><AssetThumb url={a.thumb_url} name={a.name} size={16} /> {a.name} <span className="text-faint">{a.version_label}</span></span>)}
          <button className="btn-ghost text-[12px]" onClick={() => setPicker('characters')}>edit…</button>
        </div>
        <div className="flex items-center gap-2 flex-wrap text-[12px]">
          <span className="label">Location</span>
          {shot.assets.filter((a) => a.type === 'location').map((a) => <span key={a.asset_id} className="chip"><AssetThumb url={a.thumb_url} name={a.name} size={16} /> {a.name} <span className="text-faint">{a.version_label}</span></span>)}
          <button className="btn-ghost text-[12px]" onClick={() => setPicker('location')}>edit…</button>
          <span className="label ml-2">Props & style</span>
          {shot.assets.filter((a) => !['character', 'location'].includes(a.type)).map((a) => <span key={a.asset_id} className="chip">{a.name}</span>)}
          <button className="btn-ghost text-[12px]" onClick={() => setPicker('props')}>edit…</button>
        </div>
        <div className="flex items-center gap-2">
          <div className="label">Shot type</div>
          <button className="flex items-center gap-2 rounded-el border border-line p-1 hover:border-ember/60" onClick={() => setShotTypes(true)} data-testid="open-shot-types">
            {st ? <><ShotDiagram st={st} size={96} /><span className="text-[12px] text-left"><b>{st.label}</b><br /><span className="text-faint">{st.use}</span></span></> : <span className="text-[12px] text-faint px-2">choose from the visual library…</span>}
          </button>
        </div>
        <div className="grid grid-cols-[72px_1fr] gap-2 items-center text-[12px]">
          <span className="label">Duration</span>
          <div className="flex items-center gap-2"><input className="input !w-20 !h-8 tabular-nums" type="number" step="0.5" min="0.5" defaultValue={shot.duration_s} onBlur={(e) => Number(e.target.value) !== shot.duration_s && patchShot({ duration_s: Number(e.target.value) })} data-testid="shot-duration" /><span className="text-faint">s</span>
            <select className="input !h-8 !w-28" value={shot.transition?.kind ?? ''} onChange={(e) => patchShot({ transition: e.target.value ? { kind: e.target.value, duration_s: e.target.value === 'cut' ? 0 : 0.5 } : null })} aria-label="Transition to next shot"><option value="">transition: default</option>{presets.transitions.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}</select>
          </div>
          <span className="label">Camera</span>
          <div className="flex flex-wrap gap-1">{presets.camera_moves.slice(0, 6).map((m) => <button key={m.key} className={`chip ${ov.camera?.movement === m.key ? '!border-ember text-fg' : ''}`} onClick={() => setGroup('camera', { movement: m.key })}>{m.label}</button>)}</div>
          <span className="label">Lighting</span>
          <div className="flex flex-wrap gap-1">{presets.lighting_presets.map((l) => <button key={l.key} className={`chip ${ov.lighting_preset === l.key ? '!border-ember text-fg' : ''}`} onClick={() => setO({ lighting_preset: l.key })} title={l.mood}>{l.label}</button>)}</div>
          <span className="label">Style</span>
          <input className="input !h-8" value={typeof ov.style === 'string' ? ov.style : ov.style?.visual_style ?? ''} placeholder={project.settings.visual_style || 'inherits project style'} onChange={(e) => setO({ style: e.target.value })} />
        </div>
        <div className="flex items-center gap-1 flex-wrap text-[11.5px]">
          <span className="label">Locks</span>
          {SHOT_LOCKS.map((k) => <button key={k} className={`chip ${shot.locks.includes(k) ? '!border-ember text-fg' : ''}`} onClick={() => toggleLock(k)} data-shot-lock={k}>{shot.locks.includes(k) ? '🔒' : '🔓'} {k.replace('_', ' ')}</button>)}
          <span className="text-faint ml-auto">approved <input type="checkbox" checked={shot.approved} onChange={(e) => patchShot({ approved: e.target.checked })} /></span>
        </div>
      </section>
      {/* frames */}
      <section className="grid grid-cols-2 gap-2">
        {(['start_frame', 'end_frame'] as const).map((which) => {
          const f = shot[which]
          return (
            <div key={which} className="card !bg-well p-2 text-[11.5px] space-y-1" data-testid={which}>
              <div className="flex items-center gap-1"><span className="font-medium">{which === 'start_frame' ? 'Start frame' : 'End frame'}</span>{f?.locked && <span>🔒</span>}{f && <span className="text-faint ml-auto">{f.kind.replace('_', ' ')}{f.source_shot_id ? ` ← shot ${f.source_shot_id}` : ''}</span>}</div>
              <div className="aspect-video bg-ink rounded-el overflow-hidden flex items-center justify-center">{frameUrl(f) ? <img src={frameUrl(f)!} alt="" className="w-full h-full object-cover" /> : <span className="text-faint">none</span>}</div>
              <div className="flex flex-wrap gap-1">
                <button className="btn-ghost text-[11px] px-1" onClick={() => generate({ kind: which }, which === 'start_frame' ? 'Start frame' : 'End frame')} disabled={busy != null || !imageModes.length} title={!imageModes.length ? 'No image provider connected' : ''}>generate</button>
                <label className="btn-ghost text-[11px] px-1 cursor-pointer">upload<input type="file" accept="image/*" hidden onChange={async (e) => { const file = e.target.files?.[0]; if (!file) return; try { await film.uploadFrame(shot.id, which, file); await onChanged() } catch (err) { toastError(errorMessage(err)) } }} /></label>
                {which === 'start_frame' && <button className="btn-ghost text-[11px] px-1" onClick={() => frameAction(which, { kind: 'previous_shot' })} title="Use previous shot's last frame as this shot's start frame">← previous shot</button>}
                <button className="btn-ghost text-[11px] px-1" onClick={() => setGallery(which)}>gallery</button>
                {f && <button className="btn-ghost text-[11px] px-1" onClick={() => frameAction(which, { kind: 'lock', locked: !f.locked })}>{f.locked ? 'unlock' : 'lock'}</button>}
                {f && <button className="btn-ghost text-[11px] px-1 text-red-300" onClick={() => frameAction(which, { kind: 'clear' })}>clear</button>}
              </div>
            </div>
          )
        })}
        <label className="col-span-2 text-[11.5px] text-mute flex items-center gap-1.5"><input type="checkbox" checked={shot.chain_from_previous} onChange={(e) => patchShot({ chain_from_previous: e.target.checked })} /> chain: previous shot's last frame feeds this start frame automatically</label>
      </section>
      {/* advanced */}
      <button className="btn-ghost text-[12px] px-0" onClick={() => setLevel((l) => ({ ...l, advanced: !l.advanced }))} aria-expanded={level.advanced} data-testid="toggle-advanced">{level.advanced ? '▾ Advanced' : '▸ Advanced — lens, height, focus, lighting placement, atmosphere, colour, motion'}</button>
      {level.advanced && (
        <section className="space-y-3 fade-in">
          <CameraControls value={ov.camera ?? {}} presets={presets} onChange={(patch) => setGroup('camera', patch)} sources={ctx?.context.sources} />
          <LightingPanel value={ov.lighting ?? {}} presets={presets.lighting_presets} onChange={(patch) => setGroup('lighting', patch)} source={ctx?.context.sources?.['lighting.mood']} />
          <div className="grid sm:grid-cols-3 gap-2 text-[12px]">
            {[['environment', 'time_of_day', 'Time of day'], ['environment', 'weather', 'Weather'], ['environment', 'atmosphere', 'Atmosphere (fog, smoke, dust…)'], ['color', 'palette', 'Palette'], ['color', 'contrast', 'Contrast'], ['color', 'saturation', 'Saturation'], ['color', 'film_grain', 'Film grain'], ['motion', 'character_motion', 'Character motion'], ['motion', 'environmental_motion', 'Environmental motion'], ['motion', 'pacing', 'Pacing'], ['action', 'expression', 'Expression'], ['action', 'pose', 'Pose']].map(([g, k, label]) => (
              <label key={g + k} className="text-mute flex flex-col gap-1">{label}<input className="input !h-8" value={g === 'action' ? (ov[k] ?? '') : (ov[g]?.[k] ?? '')} placeholder={scene.defaults?.[k] ?? ''} onChange={(e) => (g === 'action' ? setO({ [k]: e.target.value }) : setGroup(g, { [k]: e.target.value }))} /></label>
            ))}
          </div>
        </section>
      )}
      {/* expert */}
      <button className="btn-ghost text-[12px] px-0" onClick={() => setLevel((l) => ({ ...l, expert: !l.expert }))} aria-expanded={level.expert} data-testid="toggle-expert">{level.expert ? '▾ Expert' : '▸ Expert — provider, model, raw prompt, negative, parameters'}</button>
      {level.expert && (
        <section className="space-y-2 fade-in text-[12px]">
          <div className="grid grid-cols-3 gap-2">
            <label className="text-mute flex flex-col gap-1">Provider<select className="input !h-8" value={ov.generation?.provider ?? ''} onChange={(e) => setGroup('generation', { provider: e.target.value || undefined })}><option value="">auto (scored)</option>{Object.entries(caps?.providers ?? {}).map(([k, p]) => <option key={k} value={k} disabled={!p.connected}>{p.label}{p.connected ? '' : ' (not connected)'}</option>)}</select></label>
            <label className="text-mute flex flex-col gap-1">Model family<select className="input !h-8" value={ov.generation?.family ?? ''} onChange={(e) => setGroup('generation', { family: e.target.value || undefined })}><option value="">default</option>{Array.from(new Set(videoModes.flatMap((m) => m.families))).map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
            <label className="text-mute flex flex-col gap-1">Mode<select className="input !h-8" value={ov.generation?.mode ?? ''} onChange={(e) => setGroup('generation', { mode: e.target.value || undefined })}><option value="">auto (richest supported)</option>{videoModes.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}</select></label>
          </div>
          <label className="text-mute flex flex-col gap-1">Raw prompt override (replaces the assembled body; locked facts stay)<textarea className="input min-h-[60px] font-mono text-[11.5px]" value={ov.prompt ?? ''} onChange={(e) => setO({ prompt: e.target.value })} /></label>
          <label className="text-mute flex flex-col gap-1">Negative<input className="input !h-8" value={ov.negative ?? ''} onChange={(e) => setO({ negative: e.target.value })} /></label>
          <div className="grid grid-cols-3 gap-2">
            <label className="text-mute flex flex-col gap-1">Resolution<select className="input !h-8" value={ov.generation?.params?.resolution ?? '720p'} onChange={(e) => setGroup('generation', { params: { ...(ov.generation?.params ?? {}), resolution: e.target.value } })}>{['480p', '720p', '1080p'].map((r) => <option key={r}>{r}</option>)}</select></label>
            <label className="text-mute flex flex-col gap-1">Seed<input className="input !h-8" value={ov.generation?.params?.seed ?? ''} onChange={(e) => setGroup('generation', { params: { ...(ov.generation?.params ?? {}), seed: e.target.value === '' ? undefined : Number(e.target.value) } })} /></label>
            <label className="text-mute flex flex-col gap-1">Reference strength<input className="input !h-8" type="number" step="0.05" min="0.1" max="1" value={ov.generation?.params?.strength ?? ''} placeholder="provider default" onChange={(e) => setGroup('generation', { params: { ...(ov.generation?.params ?? {}), strength: e.target.value === '' ? undefined : Number(e.target.value) } })} /></label>
          </div>
          {ctx && (
            <details className="card !bg-well p-2" open>
              <summary className="cursor-pointer text-mute">Effective prompt (assembled from presets → scene → shot; locked facts first)</summary>
              <p className="font-mono text-[11px] whitespace-pre-wrap mt-1 text-fg">{ctx.prompt.prompt}</p>
              {ctx.prompt.negative && <p className="font-mono text-[11px] text-faint mt-1">negative: {ctx.prompt.negative}</p>}
              <p className="text-faint mt-1">locks: {ctx.prompt.locks.join(', ') || 'none'} · sources: {Object.entries(ctx.context.sources ?? {}).slice(0, 8).map(([k, v]) => `${k}←${v}`).join(', ')}</p>
            </details>
          )}
        </section>
      )}
      {/* director note */}
      <section className="space-y-1.5">
        <div className="flex gap-1.5"><input className="input !h-8 text-[12.5px] flex-1" placeholder="Tell the Director: “make it tense, intimate, expensive, keep Jack's face”" value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && note.trim() && film.directShot(shot.id, note).then(setProposal).catch((err) => toastError(errorMessage(err)))} data-testid="director-note" /><button className="btn" onClick={() => film.directShot(shot.id, note).then(setProposal).catch((err) => toastError(errorMessage(err)))} disabled={!note.trim()}>Ask Director</button></div>
        {proposal && !proposal.applied && !proposal.rejected && <ProposalCard p={proposal} onChanged={async () => { setProposal(null); setNote(''); await onChanged() }} />}
      </section>
      {dirty && <div className="sticky bottom-0 flex items-center gap-2 card !bg-panel/95 backdrop-blur p-2"><span className="text-[12px] text-faint">Unsaved changes</span><button className="btn ml-auto" onClick={() => { setOv(shot.overrides ?? {}); setDirty(false) }}>Discard</button><button className="btn-accent" onClick={save} data-testid="save-shot">Save shot</button></div>}
      <p className="text-[10.5px] text-faint">updated {timeAgo(shot.assets.length ? undefined : undefined) === '—' ? '' : ''}{selected?.decision?.reason ? `Provider: ${selected.decision.selected?.provider} — ${selected.decision.reason} (${selected.decision.basis})` : ''}</p>

      {picker && <AssetPicker title={picker === 'characters' ? 'Characters in this shot' : picker === 'location' ? 'Location' : 'Props, vehicles, outfits, styles'} types={picker === 'characters' ? ['character'] : picker === 'location' ? ['location'] : ['prop', 'vehicle', 'outfit', 'style']} multi={picker !== 'location'} selected={pinned(picker)} onClose={() => setPicker(null)} onPick={(p) => applyPick(picker, p)} />}
      {shotTypes && (
        <Modal title="Shot types" onClose={() => setShotTypes(false)} wide>
          <ShotTypeLibrary types={presets.shot_types} favorites={presets.favorites} value={ov.shot_type} onToggleFavorite={onFavoriteShotType} onPick={(t) => { const locked = shot.locks.includes('camera'); setO({ shot_type: t.key, camera: locked ? ov.camera : { ...(ov.camera ?? {}), ...t.camera } }); setShotTypes(false); if (locked) toastSuccess('Shot type set — camera values kept because camera is locked') }} />
        </Modal>
      )}
      {regen && (
        <Modal title="Repair / regenerate" onClose={() => setRegen(null)}>
          <div className="space-y-2 text-[12.5px]">
            <p className="text-faint">Pick exactly what may change. Everything locked stays preserved automatically.</p>
            <div className="grid grid-cols-2 gap-2">
              <div><div className="label">Change</div>{REGEN_GROUPS.map((g) => <label key={g} className="block"><input type="checkbox" checked={regen.change.includes(g)} onChange={(e) => setRegen({ ...regen, change: e.target.checked ? [...regen.change, g] : regen.change.filter((x) => x !== g), preserve: regen.preserve.filter((x) => x !== g) })} /> {g}</label>)}</div>
              <div><div className="label">Preserve</div>{REGEN_GROUPS.map((g) => <label key={g} className="block"><input type="checkbox" checked={regen.preserve.includes(g)} onChange={(e) => setRegen({ ...regen, preserve: e.target.checked ? [...regen.preserve, g] : regen.preserve.filter((x) => x !== g), change: regen.change.filter((x) => x !== g) })} /> {g}</label>)}</div>
            </div>
            <input className="input" placeholder="instruction, e.g. “red jacket instead of the coat”" value={regen.instruction} onChange={(e) => setRegen({ ...regen, instruction: e.target.value })} />
            <div className="flex justify-end gap-2"><button className="btn" onClick={() => setRegen(null)}>Cancel</button><button className="btn-accent" onClick={() => { const r = regen; setRegen(null); generate({ kind: 'video', change: r.change, preserve: r.preserve, instruction: r.instruction || undefined }, 'Regeneration') }}>Generate</button></div>
          </div>
        </Modal>
      )}
      {footage && <FootageModal shotId={shot.id} projectId={project.id} initialQuery={ov.action ?? shot.title ?? ''} onClose={() => setFootage(false)} onAttached={async () => { setFootage(false); await onChanged(); loadTakes() }} />}
      {gallery && <GalleryImport onClose={() => setGallery(null)} onPick={async (pid) => { await frameAction(gallery, { kind: 'post', post_id: pid }); setGallery(null) }} />}
      {card && (
        <Modal title="Title card" onClose={() => setCard(null)}>
          <div className="space-y-2">
            <input className="input" value={card.text} onChange={(e) => setCard({ ...card, text: e.target.value })} placeholder="RAINY CITY" />
            <input className="input" value={card.subtitle} onChange={(e) => setCard({ ...card, subtitle: e.target.value })} placeholder="subtitle (optional)" />
            <select className="input" value={card.style} onChange={(e) => setCard({ ...card, style: e.target.value })}>{['title', 'lower_third', 'caption', 'end_card'].map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}</select>
            <div className="flex justify-end gap-2"><button className="btn" onClick={() => setCard(null)}>Cancel</button><button className="btn-accent" disabled={!card.text.trim()} onClick={async () => { try { await film.card(shot.id, { text: card.text, subtitle: card.subtitle || undefined, style: card.style }); toastSuccess('Card rendered as a take'); setCard(null); await onChanged(); loadTakes() } catch (e) { toastError(errorMessage(e)) } }}>Render</button></div>
          </div>
        </Modal>
      )}
    </div>
  )
}

export const strategyLabel = (k: string) => STRATEGY_LABEL[k] ?? k
export type { Shot }
export { useMemo as _useMemo, useNavigate as _useNavigate }
