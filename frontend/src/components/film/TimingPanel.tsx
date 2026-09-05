// Timing template + proportional strip (spec L, AB): project default gap,
// per-scene overrides (apply-all / reset), shot durations by drag or typed,
// live runtime. Pure helpers are exported for unit tests.
import { useRef, useState } from 'react'
import { fmtTc, Timeline, TimelineScene } from '../../lib/film'

/** Runtime from scene durations + gaps. A scene whose gap is inherited
 *  follows `gapDefault`; an explicit override keeps its own value. */
export function runtimeOf(tl: { scenes: Pick<TimelineScene, 'duration_s' | 'gap_after_s' | 'gap_inherited'>[] }, gapDefault: number): number {
  let t = 0
  tl.scenes.forEach((sc, i) => {
    t += sc.duration_s
    if (i < tl.scenes.length - 1) t += sc.gap_inherited || sc.gap_after_s == null ? gapDefault : sc.gap_after_s
  })
  return Math.round(t * 1000) / 1000
}

/** Pixel width for a duration at `pxPerSec`, never below a readable minimum. */
export function widthFor(seconds: number, pxPerSec: number, min = 28): number {
  return Math.max(min, Math.round(seconds * pxPerSec))
}

export function snapDuration(seconds: number, step = 0.5, min = 0.5, max = 600): number {
  return Math.min(max, Math.max(min, Math.round(seconds / step) * step))
}

export function TimingPanel({
  tl,
  view,
  onView,
  onDefaultGap,
  onApplyAll,
  onSceneGap,
  onShotDuration,
  onSelectShot,
  selectedShotId,
  onDefaultTransition,
}: {
  tl: Timeline
  view: 'scene' | 'shot' | 'timeline'
  onView: (v: 'scene' | 'shot' | 'timeline') => void
  onDefaultGap: (gap: number, resetOverrides?: boolean) => void
  onApplyAll: (gap: number) => void
  onSceneGap: (sceneId: number, gap: number | null) => void
  onShotDuration: (shotId: number, seconds: number) => void
  onSelectShot?: (shotId: number) => void
  selectedShotId?: number | null
  onDefaultTransition?: (kind: string) => void
}) {
  const [gapDraft, setGapDraft] = useState<string>(String(tl.default_scene_gap_s))
  const over = tl.target_runtime_s ? tl.runtime_s - tl.target_runtime_s : 0
  return (
    <div className="space-y-3" data-testid="timing-panel">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <div className="text-[10.5px] uppercase tracking-wide text-faint">Total runtime</div>
          <div className="font-display text-[22px] tabular-nums" data-testid="runtime">{tl.runtime_tc}</div>
        </div>
        <div className="text-[12px] text-mute">
          target {tl.target_tc}{' '}
          {tl.target_runtime_s ? <span className={over > 0 ? 'text-amber-300' : 'text-emerald-300'}>({over > 0 ? '+' : ''}{over.toFixed(1)}s)</span> : null}
          <div className="text-faint">{tl.scene_count} scenes · {tl.shot_count} shots · {tl.fps} fps</div>
        </div>
        <div className="ml-auto flex gap-1">
          {(['scene', 'shot', 'timeline'] as const).map((v) => (
            <button key={v} className={`chip ${view === v ? '!border-ember text-fg' : ''}`} onClick={() => onView(v)}>{v} view</button>
          ))}
        </div>
      </div>
      <div className="card !bg-well p-2.5 flex flex-wrap items-center gap-2 text-[12.5px]">
        <span className="text-mute">Default scene gap</span>
        <input className="input !w-20 tabular-nums" type="number" step="0.25" min="0" max="60" value={gapDraft} onChange={(e) => setGapDraft(e.target.value)} onBlur={() => gapDraft !== '' && onDefaultGap(Number(gapDraft))} onKeyDown={(e) => e.key === 'Enter' && onDefaultGap(Number(gapDraft))} aria-label="Default scene gap seconds" />
        <span className="text-faint">s</span>
        <button className="btn-ghost text-[12px]" onClick={() => onApplyAll(Number(gapDraft))} title="Set an explicit override on every scene">Apply this gap to all scenes</button>
        <button className="btn-ghost text-[12px]" onClick={() => onDefaultGap(Number(gapDraft), true)} title="Remove every per-scene override">Reset overrides</button>
        {onDefaultTransition && (
          <label className="ml-auto flex items-center gap-1.5">
            <span className="text-mute">Default transition</span>
            <select className="input !w-32 !h-8" value={tl.default_transition.kind} onChange={(e) => onDefaultTransition(e.target.value)}>
              {['cut', 'dissolve', 'fade_black', 'fade_white', 'wipe'].map((k) => <option key={k} value={k}>{k.replace('_', ' ')}</option>)}
            </select>
          </label>
        )}
      </div>
      {view === 'scene' && (
        <div className="space-y-1.5">
          {tl.scenes.map((sc) => (
            <SceneRow key={sc.id} sc={sc} gapDefault={tl.default_scene_gap_s} last={sc.number === tl.scene_count} onGap={(g) => onSceneGap(sc.id, g)} />
          ))}
        </div>
      )}
      {view === 'shot' && (
        <div className="space-y-2">
          {tl.scenes.map((sc) => (
            <div key={sc.id}>
              <div className="text-[11px] uppercase tracking-wide text-faint mb-1">Scene {String(sc.number).padStart(2, '0')} · {sc.title} · {fmtTc(sc.duration_s)}</div>
              <div className="space-y-1">
                {sc.shots.map((sh) => (
                  <div key={sh.id} className={`flex items-center gap-2 text-[12.5px] rounded-el px-2 py-1 ${selectedShotId === sh.id ? 'bg-well border border-ember/50' : ''}`}>
                    <button className="font-mono text-[11px] text-faint w-10 text-left" onClick={() => onSelectShot?.(sh.id)}>{sh.label}</button>
                    <span className="truncate flex-1">{sh.title ?? '—'}</span>
                    <span className="text-faint tabular-nums">{sh.tc_in} → {sh.tc_out}</span>
                    <input className="input !w-20 !h-7 tabular-nums" type="number" step="0.5" min="0.5" value={sh.duration_s} onChange={(e) => onShotDuration(sh.id, snapDuration(Number(e.target.value)))} aria-label={`Duration of shot ${sh.label}`} />
                    <span className="text-faint text-[11px] w-20 truncate">{sh.transition ? sh.transition.kind.replace('_', ' ') + (sh.transition.duration_s ? ` ${sh.transition.duration_s}s` : '') : ''}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      {view === 'timeline' && <Strip tl={tl} onShotDuration={onShotDuration} onSelectShot={onSelectShot} selectedShotId={selectedShotId} />}
    </div>
  )
}

function SceneRow({ sc, gapDefault, last, onGap }: { sc: TimelineScene; gapDefault: number; last: boolean; onGap: (g: number | null) => void }) {
  const [draft, setDraft] = useState<string>(sc.gap_after_s == null ? '' : String(sc.gap_after_s))
  return (
    <div className="card p-2.5 flex flex-wrap items-center gap-3 text-[12.5px]" data-testid={`scene-row-${sc.id}`}>
      <div className="w-24 font-display">Scene {String(sc.number).padStart(2, '0')}</div>
      <div className="flex-1 min-w-[120px] truncate">{sc.title}</div>
      <div className="text-faint tabular-nums">{sc.tc_in} → {sc.tc_out}</div>
      <div className="tabular-nums">Duration {fmtTc(sc.duration_s)}</div>
      {!last && (
        <div className="flex items-center gap-1.5">
          <span className="text-mute">Gap after</span>
          <input className="input !w-20 !h-7 tabular-nums" type="number" step="0.25" min="0" placeholder={String(gapDefault)} value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={() => onGap(draft === '' ? null : Number(draft))} onKeyDown={(e) => e.key === 'Enter' && onGap(draft === '' ? null : Number(draft))} aria-label={`Gap after scene ${sc.number}`} />
          <span className={`text-[11px] ${sc.gap_inherited ? 'text-faint' : 'text-ember'}`}>{sc.gap_inherited ? `${gapDefault}s inherited` : `${sc.gap_after_s}s override`}</span>
          {!sc.gap_inherited && <button className="btn-ghost text-[11px] px-1" onClick={() => { setDraft(''); onGap(null) }}>reset</button>}
          {sc.transition && sc.transition.kind !== 'cut' && <span className="chip !text-[10px]">{sc.transition.kind.replace('_', ' ')} {sc.transition.duration_s}s</span>}
        </div>
      )}
    </div>
  )
}

export function Strip({ tl, onShotDuration, onSelectShot, selectedShotId, pxPerSec = 26 }: { tl: Timeline; onShotDuration: (id: number, s: number) => void; onSelectShot?: (id: number) => void; selectedShotId?: number | null; pxPerSec?: number }) {
  const drag = useRef<{ id: number; startX: number; start: number } | null>(null)
  const [preview, setPreview] = useState<{ id: number; s: number } | null>(null)
  const onDown = (id: number, start: number) => (e: React.PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    drag.current = { id, startX: e.clientX, start }
    const move = (ev: PointerEvent) => {
      if (!drag.current) return
      const s = snapDuration(drag.current.start + (ev.clientX - drag.current.startX) / pxPerSec)
      setPreview({ id, s })
    }
    const up = (ev: PointerEvent) => {
      if (drag.current) {
        const s = snapDuration(drag.current.start + (ev.clientX - drag.current.startX) / pxPerSec)
        if (s !== drag.current.start) onShotDuration(id, s)
      }
      drag.current = null
      setPreview(null)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  return (
    <div className="overflow-x-auto pb-2" data-testid="timeline-strip">
      <div className="flex items-end gap-0 min-w-max">
        {tl.scenes.map((sc, i) => (
          <div key={sc.id} className="flex items-end">
            <div className="flex flex-col">
              <div className="text-[10px] text-faint mb-1 px-1">S{String(sc.number).padStart(2, '0')} {sc.title}</div>
              <div className="flex">
                {sc.shots.map((sh) => {
                  const d = preview?.id === sh.id ? preview.s : sh.duration_s
                  return (
                    <div
                      key={sh.id}
                      className={`relative h-12 border ${selectedShotId === sh.id ? 'border-ember bg-ember/15' : 'border-line bg-panel'} rounded-el mr-0.5 text-[10.5px] px-1.5 py-1 overflow-hidden cursor-pointer select-none`}
                      style={{ width: widthFor(d, pxPerSec) }}
                      onClick={() => onSelectShot?.(sh.id)}
                      title={`${sh.label} ${sh.title ?? ''} — ${d}s`}
                      data-testid={`strip-shot-${sh.id}`}
                    >
                      <div className="font-mono text-faint">{sh.label}</div>
                      <div className="tabular-nums">{d}s</div>
                      {sh.transition && sh.transition.kind !== 'cut' && <span className="absolute right-0 top-0 h-full w-1 bg-ember/60" title={sh.transition.kind} />}
                      <span className="absolute right-0 top-0 h-full w-2 cursor-ew-resize hover:bg-ember/40" onPointerDown={onDown(sh.id, sh.duration_s)} aria-label={`Resize shot ${sh.label}`} />
                    </div>
                  )
                })}
              </div>
            </div>
            {i < tl.scenes.length - 1 && (
              <div className="h-12 flex flex-col justify-end items-center mr-0.5" style={{ width: widthFor(sc.gap_after_s ?? tl.default_scene_gap_s, pxPerSec, 14) }} title={`gap ${sc.gap_after_s ?? tl.default_scene_gap_s}s`}>
                <div className="w-full h-6 bg-ink border border-dashed border-line rounded-el" />
                <div className="text-[9px] text-faint">{sc.gap_after_s ?? tl.default_scene_gap_s}s</div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
