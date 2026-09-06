// Editor (Editor spec E4/E5): media bin | preview | inspector over the
// multi-track timeline. Every edit is one server call = one undo step, so
// the project is always saved; undo/redo replay server snapshots. The
// playhead derives from a performance.now() origin (never accumulated) and
// React state updates are throttled to ~30 Hz.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AddPayload, MediaBin } from '../../components/editor/MediaBin'
import { Inspector } from '../../components/editor/Inspector'
import { PreviewPlayer } from '../../components/editor/PreviewPlayer'
import { ClipOp, Timeline } from '../../components/editor/Timeline'
import { Spinner } from '../../components/Primitives'
import {
  DEFAULT_ZOOM_INDEX, matchShortcut, nearestFreeStart, round3, seq as seqApi, Sequence, SeqClip,
  SHORTCUTS, shortcutHint, ZOOM_LADDER,
} from '../../lib/editor'
import { errorMessage, film, Take } from '../../lib/film'
import { toastError, toastSuccess } from '../../lib/toast'
import { useFilm } from './FilmPage'

export function EditorPage() {
  const { project, reloadProject } = useFilm()
  const navigate = useNavigate()
  const [sq, setSq] = useState<Sequence | null>(null)
  const [selection, setSelection] = useState<number[]>([])
  const [markerSel, setMarkerSel] = useState<number | null>(null)
  const [zoomIdx, setZoomIdx] = useState(DEFAULT_ZOOM_INDEX)
  const [snapping, setSnapping] = useState(true)
  const [loop, setLoop] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [playhead, setPlayheadState] = useState(0)
  const [help, setHelp] = useState(false)
  const [takePick, setTakePick] = useState<SeqClip | null>(null)
  const playheadRef = useRef(0)
  const originRef = useRef({ t0: 0, ph: 0 })
  const sqRef = useRef<Sequence | null>(null)
  sqRef.current = sq

  const setPlayhead = useCallback((t: number) => {
    playheadRef.current = Math.max(0, t)
    setPlayheadState(playheadRef.current)
    originRef.current = { t0: performance.now(), ph: playheadRef.current }
  }, [])

  // ------------------------------------------------------------- loading ---
  const load = useCallback(() => {
    if (!project) return
    seqApi.get(project.id).then(setSq).catch((e) => toastError(errorMessage(e)))
  }, [project?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(load, [load])

  // one wrapper for every mutation: optimistic callers pass the promise;
  // errors surface as a toast and the authoritative state is reloaded
  const apply = useCallback((p: Promise<Sequence>, onDone?: () => void) => {
    p.then((s) => {
      setSq(s)
      onDone?.()
    }).catch((e) => {
      toastError(errorMessage(e))
      load()
    })
  }, [load])

  // ------------------------------------------------------------ playback ---
  useEffect(() => {
    if (!playing || !sq) return
    originRef.current = { t0: performance.now(), ph: playheadRef.current }
    let raf = 0
    let lastPaint = 0
    const tick = (now: number) => {
      const t = originRef.current.ph + (now - originRef.current.t0) / 1000
      const end = sqRef.current?.runtime_s ?? 0
      if (t >= end && end > 0) {
        if (loop) {
          originRef.current = { t0: now, ph: 0 }
          playheadRef.current = 0
          setPlayheadState(0)
        } else {
          playheadRef.current = end
          setPlayheadState(end)
          setPlaying(false)
          return
        }
      } else if (now - lastPaint >= 33) {
        playheadRef.current = t
        setPlayheadState(t)
        lastPaint = now
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, loop, sq?.runtime_s]) // eslint-disable-line react-hooks/exhaustive-deps

  const step = useCallback((frames: number) => {
    const fps = sqRef.current?.fps || 24
    setPlaying(false)
    setPlayhead(round3(playheadRef.current + frames / fps))
  }, [setPlayhead])

  // ------------------------------------------------------------- actions ---
  const pid = project?.id
  const splitAtPlayhead = useCallback(() => {
    const s = sqRef.current
    if (!s || !pid) return
    const t = playheadRef.current
    const targets = s.tracks.flatMap((tr) => tr.clips).filter((c) =>
      (selection.length ? selection.includes(c.id) : true) && t > c.start_s + 0.05 && t < c.start_s + c.duration_s - 0.05)
    const first = selection.length ? targets[0] : targets.find((c) => s.tracks.find((tr) => tr.id === c.track_id)?.kind === 'video') ?? targets[0]
    if (!first) return
    apply(seqApi.split(first.id, round3(t)))
  }, [selection, pid, apply])

  const deleteSelection = useCallback((ripple: boolean) => {
    if (!pid || !selection.length) return
    apply(seqApi.deleteClips(pid, selection, ripple), () => setSelection([]))
  }, [pid, selection, apply])

  const addFromBin = useCallback((p: AddPayload) => {
    const s = sqRef.current
    if (!s || !pid) return
    const wantKind = p.source_kind === 'audio' ? 'audio' : 'video'
    const track = s.tracks.find((t) => t.kind === wantKind && !t.locked)
    if (!track) {
      toastError(`No unlocked ${wantKind} track.`)
      return
    }
    const dur = p.duration_s ?? 3
    const start = nearestFreeStart(track, playheadRef.current, dur)
    apply(seqApi.addClip(pid, { track_id: track.id, source_kind: p.source_kind, start_s: start, duration_s: dur, take_id: p.take_id, footage_id: p.footage_id, audio_track_id: p.audio_track_id, shot_id: p.shot_id, label: p.label }), () => toastSuccess('Clip added at the playhead'))
  }, [pid, apply])

  const onCommit = useCallback((ops: ClipOp[], label: string) => {
    if (!pid) return
    if (ops.length === 1) {
      const { id, ...fields } = ops[0]
      apply(seqApi.patchClip(id, { ...fields, label_op: label }))
    } else apply(seqApi.batch(pid, ops as unknown as Record<string, unknown>[], label))
  }, [pid, apply])

  // ------------------------------------------------------------ shortcuts --
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable) return
      // text-entry inputs swallow shortcuts; range/checkbox controls don't
      if (el.tagName === 'INPUT' && !['range', 'checkbox', 'radio', 'button'].includes((el as HTMLInputElement).type)) return
      const action = matchShortcut(e)
      if (!action || !sqRef.current?.exists || !pid) return
      e.preventDefault()
      const s = sqRef.current
      const acts: Record<string, () => void> = {
        play: () => setPlaying((p) => !p),
        prevFrame: () => step(e.shiftKey ? -10 : -1),
        nextFrame: () => step(e.shiftKey ? 10 : 1),
        home: () => setPlayhead(0),
        end: () => setPlayhead(s.runtime_s),
        loop: () => setLoop((l) => !l),
        split: splitAtPlayhead,
        del: () => deleteSelection(false),
        rippleDel: () => deleteSelection(true),
        snap: () => setSnapping((v) => !v),
        marker: () => apply(seqApi.addMarker(pid, { t_s: round3(playheadRef.current) })),
        undo: () => s.can_undo && apply(seqApi.undo(pid)),
        redo: () => s.can_redo && apply(seqApi.redo(pid)),
        zoomIn: () => setZoomIdx((z) => Math.min(ZOOM_LADDER.length - 1, z + 1)),
        zoomOut: () => setZoomIdx((z) => Math.max(0, z - 1)),
        selectAll: () => setSelection(s.tracks.flatMap((t) => t.clips.map((c) => c.id))),
        help: () => setHelp((h) => !h),
      }
      acts[action]?.()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [pid, step, splitAtPlayhead, deleteSelection, apply, setPlayhead])

  // --------------------------------------------------------------- render --
  if (!project) return null
  if (!sq) return <Spinner />
  if (!sq.exists) {
    return (
      <div className="card p-6 max-w-xl mx-auto text-center space-y-3" data-testid="editor-empty">
        <h3 className="font-display text-[18px]">No sequence yet</h3>
        <p className="text-[12.5px] text-mute">Build the timeline from your storyboard: one clip per shot at the exact storyboard timing (scene gaps become space on the track), audio laid out underneath. From then on the edit — trims, moves, splits, speed — is yours, and export renders exactly what you see.</p>
        <button className="btn-accent" onClick={() => apply(seqApi.build(project.id), () => reloadProject())} data-testid="btn-build-timeline">Build timeline from storyboard</button>
        <p className="text-[11.5px] text-faint">The storyboard stays untouched; you can rebuild any time (undo restores the edit).</p>
      </div>
    )
  }
  const pxPerSec = ZOOM_LADDER[zoomIdx]
  const selClip = selection.length === 1 ? sq.tracks.flatMap((t) => t.clips).find((c) => c.id === selection[0]) ?? null : null
  const selMarker = markerSel != null ? sq.markers.find((m) => m.id === markerSel) ?? null : null
  return (
    <div className="space-y-2" data-testid="editor-page">
      <div className="grid gap-2 lg:grid-cols-[230px_1fr_250px]" style={{ minHeight: 0 }}>
        <div className="card p-2 max-h-[52vh] overflow-hidden hidden lg:flex"><MediaBin project={project} seq={sq} onAdd={addFromBin} /></div>
        <div className="card p-2.5"><PreviewPlayer seq={sq} playhead={playhead} playing={playing} loop={loop} onTogglePlay={() => setPlaying(!playing)} onSeek={(t) => setPlayhead(t)} onToggleLoop={() => setLoop(!loop)} onStep={step} /></div>
        <div className="card p-2.5 max-h-[52vh] overflow-y-auto">
          <Inspector seq={sq} clip={selClip} marker={selMarker}
                     onPatchClip={(id, body, label) => apply(seqApi.patchClip(id, { ...body, label_op: label }))}
                     onPatchMarker={(id, body) => apply(seqApi.patchMarker(id, body))}
                     onDeleteMarker={(id) => apply(seqApi.deleteMarker(id), () => setMarkerSel(null))}
                     onOpenShot={(shotId) => navigate('/film/storyboard', { state: { shotId } })}
                     onSetTake={setTakePick} />
        </div>
      </div>
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
        <button className="btn" onClick={splitAtPlayhead} title={`Split at playhead (${shortcutHint('split')})`} data-testid="btn-split">✂ Split</button>
        <button className="btn" disabled={!selection.length} onClick={() => deleteSelection(false)} title={`Delete (${shortcutHint('del')})`}>Delete</button>
        <button className="btn" disabled={!selection.length} onClick={() => deleteSelection(true)} title="Ripple delete — later clips close the gap (Shift+Del)">Ripple delete</button>
        <button className={`chip ${snapping ? '!border-ember text-fg' : ''}`} onClick={() => setSnapping(!snapping)} title={`Magnetic snapping (${shortcutHint('snap')})`} data-testid="btn-snap">🧲 snap</button>
        <button className="btn" onClick={() => apply(seqApi.addMarker(project.id, { t_s: round3(playheadRef.current) }))} title={`Marker at playhead (${shortcutHint('marker')})`}>◆ Marker</button>
        <span className="mx-1 text-line">|</span>
        <button className="btn !px-2" disabled={!sq.can_undo} onClick={() => apply(seqApi.undo(project.id))} title={`Undo (${shortcutHint('undo')})`} data-testid="btn-undo">↩</button>
        <button className="btn !px-2" disabled={!sq.can_redo} onClick={() => apply(seqApi.redo(project.id))} title={`Redo (${shortcutHint('redo')})`} data-testid="btn-redo">↪</button>
        <span className="mx-1 text-line">|</span>
        <button className="btn !px-2" onClick={() => setZoomIdx(Math.max(0, zoomIdx - 1))} title={`Zoom out (${shortcutHint('zoomOut')})`}>−</button>
        <span className="text-faint tabular-nums w-14 text-center">{pxPerSec}px/s</span>
        <button className="btn !px-2" onClick={() => setZoomIdx(Math.min(ZOOM_LADDER.length - 1, zoomIdx + 1))} title={`Zoom in (${shortcutHint('zoomIn')})`}>+</button>
        <span className="ml-auto text-faint">{selection.length ? `${selection.length} selected` : 'all changes saved'}</span>
        <button className="btn-ghost" onClick={() => setHelp(true)} title="Keyboard shortcuts (?)">⌨ shortcuts</button>
        <button className="btn-ghost" onClick={() => window.confirm('Rebuild from the storyboard? Your edit is replaced (undo restores it).') && apply(seqApi.build(project.id, true))} data-testid="btn-rebuild">Rebuild from storyboard</button>
      </div>
      <Timeline
        seq={sq} pxPerSec={pxPerSec} playhead={playhead} selection={selection} snapping={snapping} playing={playing} followPlayhead
        onSeek={(t) => setPlayhead(t)}
        onSelect={(ids) => { setSelection(ids); setMarkerSel(null) }}
        onCommit={onCommit}
        onTrackPatch={(id, body) => apply(seqApi.patchTrack(id, body))}
        onTrackDelete={(id) => apply(seqApi.deleteTrack(id))}
        onAddTrack={(kind) => apply(seqApi.addTrack(project.id, kind))}
        onMarkerMove={(id, t) => apply(seqApi.patchMarker(id, { t_s: t }))}
        onMarkerAdd={(t) => apply(seqApi.addMarker(project.id, { t_s: t }))}
        onMarkerSelect={(id) => { setMarkerSel(id); if (id != null) setSelection([]) }}
      />
      {help && <ShortcutsOverlay onClose={() => setHelp(false)} />}
      {takePick && <TakePicker clip={takePick} onClose={() => setTakePick(null)} onPick={(t) => { apply(seqApi.setTake(takePick.id, t.id)); setTakePick(null) }} />}
    </div>
  )
}

function ShortcutsOverlay({ onClose }: { onClose: () => void }) {
  const groups = new Map<string, [string, typeof SHORTCUTS[string]][]>()
  for (const [k, v] of Object.entries(SHORTCUTS)) {
    if (!groups.has(v.group)) groups.set(v.group, [])
    groups.get(v.group)!.push([k, v])
  }
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose} data-testid="shortcuts-overlay">
      <div className="card p-4 max-w-lg w-full" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center mb-2"><h3 className="font-display text-[15px] flex-1">Keyboard shortcuts</h3><button className="btn-ghost" onClick={onClose}>✕</button></div>
        <div className="grid sm:grid-cols-2 gap-3 text-[12px]">
          {[...groups.entries()].map(([g, items]) => (
            <div key={g}>
              <div className="text-[10.5px] uppercase tracking-wide text-faint mb-1">{g}</div>
              {items.map(([k, v]) => (
                <div key={k} className="flex gap-2 py-0.5"><kbd className="font-mono text-[10.5px] bg-well border border-line rounded px-1 shrink-0">{shortcutHint(k)}</kbd><span className="text-mute">{v.label}</span></div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function TakePicker({ clip, onClose, onPick }: { clip: SeqClip; onClose: () => void; onPick: (t: Take) => void }) {
  const [takes, setTakes] = useState<Take[] | null>(null)
  useEffect(() => {
    if (clip.shot_id) film.takes(clip.shot_id).then((r) => setTakes(r.takes.filter((t) => t.status === 'succeeded' || t.status === 'imported'))).catch(() => setTakes([]))
    else setTakes([])
  }, [clip.shot_id])
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose} data-testid="take-picker">
      <div className="card p-4 max-w-md w-full" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center mb-2"><h3 className="font-display text-[15px] flex-1">Pick a take</h3><button className="btn-ghost" onClick={onClose}>✕</button></div>
        {takes === null && <Spinner />}
        {takes?.length === 0 && <p className="text-[12px] text-faint">No finished takes on this clip's shot{clip.shot_id ? '' : ' (the clip has no shot link)'}.</p>}
        <div className="grid grid-cols-3 gap-2">
          {takes?.map((t) => (
            <button key={t.id} className={`rounded-el overflow-hidden border text-left ${t.id === clip.take_id ? 'border-ember' : 'border-line hover:border-ember/60'}`} onClick={() => onPick(t)}>
              {t.thumb_url ? <img src={t.thumb_url} alt="" className="w-full aspect-video object-cover" /> : <div className="aspect-video bg-well" />}
              <div className="text-[10.5px] px-1 py-0.5 text-faint">take {t.number} · {t.kind}{t.duration_s ? ` · ${t.duration_s.toFixed(1)}s` : ''}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
