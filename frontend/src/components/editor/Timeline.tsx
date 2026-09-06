// Multi-track timeline (Editor E4): DOM clips + canvas ruler, pointer-event
// drag/trim with magnetic snapping (toggle + break-out), marquee multi-
// select, playhead scrub, markers, track mute/solo/lock. All geometry math
// comes from lib/editor (pure, unit-tested); this file is the thin render +
// gesture layer. Edits preview locally per pointer-move and land as ONE
// batch (one undo step) on pointer-up.
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  collides, FlatSegment, nearestFreeStart, pxToTime, round3, Sequence, SeqClip, SeqTrack,
  snapDrag, snapPoints, snapTime, tickInterval, timeToPx,
} from '../../lib/editor'

const TRACK_H: Record<string, number> = { video: 64, audio: 44, caption: 34 }
const HEADER_W = 148
const RULER_H = 26
const MARKER_H = 18
const SNAP_PX = 8
const SNAP_BREAK_PX = 18

export interface ClipOp {
  id: number
  start_s?: number
  duration_s?: number
  trim_start_s?: number
  track_id?: number
}

interface DragState {
  mode: 'move' | 'trim-start' | 'trim-end'
  clipIds: number[]
  anchorId: number
  startX: number
  orig: Map<number, { start: number; dur: number; trim: number; track: number }>
  grabOffset: number
  snapLockX: number | null
  moved: boolean
}

export function Timeline({
  seq, pxPerSec, playhead, selection, snapping, playing,
  onSeek, onSelect, onCommit, onTrackPatch, onTrackDelete, onAddTrack,
  onMarkerMove, onMarkerAdd, onMarkerSelect, followPlayhead,
}: {
  seq: Sequence
  pxPerSec: number
  playhead: number
  selection: number[]
  snapping: boolean
  playing: boolean
  onSeek: (t: number) => void
  onSelect: (ids: number[], additive?: boolean) => void
  onCommit: (ops: ClipOp[], label: string) => void
  onTrackPatch: (id: number, body: Record<string, unknown>) => void
  onTrackDelete: (id: number) => void
  onAddTrack: (kind: 'video' | 'audio' | 'caption') => void
  onMarkerMove: (id: number, t: number) => void
  onMarkerAdd: (t: number) => void
  onMarkerSelect: (id: number | null) => void
  followPlayhead?: boolean
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [drag, setDrag] = useState<DragState | null>(null)
  const [preview, setPreview] = useState<Map<number, { start: number; dur: number; trim: number; track: number }> | null>(null)
  const [snapGuide, setSnapGuide] = useState<number | null>(null)
  const [marquee, setMarquee] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null)
  const [scrollLeft, setScrollLeft] = useState(0)
  const [viewW, setViewW] = useState(1200)

  const width = Math.max(600, timeToPx(seq.runtime_s + 20, pxPerSec))
  const tracks = seq.tracks
  const trackTops = useMemo(() => {
    let y = RULER_H + MARKER_H
    const tops = new Map<number, { top: number; h: number; track: SeqTrack }>()
    for (const t of tracks) {
      tops.set(t.id, { top: y, h: TRACK_H[t.kind] ?? 48, track: t })
      y += (TRACK_H[t.kind] ?? 48) + 4
    }
    return { tops, total: y }
  }, [tracks])

  // keep the playhead visible while playing
  useEffect(() => {
    if (!playing || !followPlayhead || !scrollRef.current) return
    const x = timeToPx(playhead, pxPerSec)
    const el = scrollRef.current
    if (x < el.scrollLeft + 40 || x > el.scrollLeft + el.clientWidth - 80) el.scrollLeft = Math.max(0, x - 120)
  }, [playhead, playing, followPlayhead, pxPerSec])

  const clipAt = (id: number): SeqClip | undefined => tracks.flatMap((t) => t.clips).find((c) => c.id === id)

  // ------------------------------------------------------------ gestures ---
  const localX = (e: { clientX: number }) => {
    const el = scrollRef.current
    if (!el) return 0
    return e.clientX - el.getBoundingClientRect().left + el.scrollLeft
  }
  const localY = (e: { clientY: number }) => {
    const el = scrollRef.current
    if (!el) return 0
    return e.clientY - el.getBoundingClientRect().top + el.scrollTop
  }

  const trackAtY = (y: number): SeqTrack | null => {
    for (const { top, h, track } of trackTops.tops.values()) if (y >= top && y <= top + h) return track
    return null
  }

  const beginClipDrag = (e: React.PointerEvent, clip: SeqClip, mode: DragState['mode']) => {
    e.preventDefault()
    e.stopPropagation()
    const track = tracks.find((t) => t.id === clip.track_id)
    if (track?.locked) return
    const additive = e.shiftKey || e.metaKey || e.ctrlKey
    let ids = selection.includes(clip.id) ? selection : additive ? [...selection, clip.id] : [clip.id]
    if (mode !== 'move') ids = [clip.id]
    onSelect(ids)
    const orig = new Map<number, { start: number; dur: number; trim: number; track: number }>()
    for (const id of ids) {
      const c = clipAt(id)
      if (c) orig.set(id, { start: c.start_s, dur: c.duration_s, trim: c.trim_start_s, track: c.track_id })
    }
    setDrag({ mode, clipIds: ids, anchorId: clip.id, startX: e.clientX, orig, grabOffset: pxToTime(localX(e), pxPerSec) - clip.start_s, snapLockX: null, moved: false })
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (marquee) {
      setMarquee({ ...marquee, x1: localX(e), y1: localY(e) })
      return
    }
    if (!drag) return
    const dxPx = e.clientX - drag.startX
    if (!drag.moved && Math.abs(dxPx) < 3) return
    const dt = pxToTime(dxPx, pxPerSec)
    const anchor = drag.orig.get(drag.anchorId)!
    const points = snapping ? snapPoints(seq, drag.clipIds, playhead) : []
    const next = new Map<number, { start: number; dur: number; trim: number; track: number }>()
    let guide: number | null = null
    if (drag.mode === 'move') {
      let delta = dt
      if (snapping) {
        const snapped = snapDrag(anchor.start + dt, anchor.dur, points, SNAP_PX / pxPerSec)
        if (snapped.target != null) {
          // break-out: past the threshold the raw position wins again
          if (Math.abs(timeToPx(anchor.start + dt - snapped.start, pxPerSec)) < SNAP_BREAK_PX) {
            delta = snapped.start - anchor.start
            guide = snapped.target
          }
        }
      }
      // vertical: retarget the ANCHOR clip's track under the cursor (same kind)
      const anchorClip = clipAt(drag.anchorId)
      const over = trackAtY(localY(e))
      for (const [id, o] of drag.orig) {
        let trackId = o.track
        if (id === drag.anchorId && over && anchorClip && over.kind === tracks.find((t) => t.id === o.track)?.kind && !over.locked) trackId = over.id
        next.set(id, { ...o, start: Math.max(0, round3(o.start + delta)), track: trackId })
      }
    } else {
      const o = anchor
      const c = clipAt(drag.anchorId)!
      if (drag.mode === 'trim-start') {
        let ns = o.start + dt
        if (snapping) {
          const sn = snapTime(ns, points, SNAP_PX / pxPerSec)
          if (sn.target != null) {
            ns = sn.start
            guide = sn.target
          }
        }
        ns = Math.max(0, Math.min(ns, o.start + o.dur - 0.05))
        // trimming forward consumes source; backward restores it (never below 0)
        const shift = ns - o.start
        const trim = Math.max(0, round3(o.trim + shift * c.speed))
        if (o.trim + shift * c.speed < 0) ns = o.start - o.trim / c.speed
        next.set(drag.anchorId, { start: round3(ns), dur: round3(o.dur - (ns - o.start)), trim, track: o.track })
      } else {
        let ne = o.start + o.dur + dt
        if (snapping) {
          const sn = snapTime(ne, points, SNAP_PX / pxPerSec)
          if (sn.target != null) {
            ne = sn.start
            guide = sn.target
          }
        }
        ne = Math.max(o.start + 0.05, ne)
        const c2 = clipAt(drag.anchorId)!
        if (c2.source_duration_s != null && c2.source_kind !== 'caption') {
          const maxDur = Math.max(0.05, (c2.source_duration_s - o.trim) / c2.speed)
          ne = Math.min(ne, o.start + maxDur)
        }
        next.set(drag.anchorId, { start: o.start, dur: round3(ne - o.start), trim: o.trim, track: o.track })
      }
    }
    setPreview(next)
    setSnapGuide(guide)
    setDrag({ ...drag, moved: true })
  }

  const endDrag = () => {
    if (drag && drag.moved && preview) {
      const ops: ClipOp[] = []
      for (const [id, p] of preview) {
        const o = drag.orig.get(id)!
        if (p.start !== o.start || p.dur !== o.dur || p.trim !== o.trim || p.track !== o.track) {
          const op: ClipOp = { id }
          if (p.start !== o.start) op.start_s = p.start
          if (p.dur !== o.dur) op.duration_s = p.dur
          if (p.trim !== o.trim) op.trim_start_s = p.trim
          if (p.track !== o.track) op.track_id = p.track
          ops.push(op)
        }
      }
      if (ops.length) {
        // nudge into a free slot instead of failing on a collision
        for (const op of ops) {
          const p = preview.get(op.id)!
          const track = tracks.find((t) => t.id === p.track)
          if (track && collides({ ...track, clips: track.clips.filter((c) => !preview.has(c.id) || c.id === op.id) }, p.start, p.dur, op.id) && drag.mode === 'move' && ops.length === 1) {
            op.start_s = nearestFreeStart(track, p.start, p.dur, op.id)
          }
        }
        onCommit(ops, drag.mode === 'move' ? (ops.length > 1 ? 'move clips' : 'move clip') : 'trim clip')
      }
    }
    if (marquee) {
      const [xa, xb] = [Math.min(marquee.x0, marquee.x1), Math.max(marquee.x0, marquee.x1)]
      const [ya, yb] = [Math.min(marquee.y0, marquee.y1), Math.max(marquee.y0, marquee.y1)]
      const hit: number[] = []
      for (const { top, h, track } of trackTops.tops.values()) {
        if (top + h < ya || top > yb) continue
        for (const c of track.clips) {
          const cx0 = timeToPx(c.start_s, pxPerSec)
          const cx1 = timeToPx(c.start_s + c.duration_s, pxPerSec)
          if (cx1 >= xa && cx0 <= xb) hit.push(c.id)
        }
      }
      if (Math.abs(marquee.x1 - marquee.x0) > 4 || Math.abs(marquee.y1 - marquee.y0) > 4) onSelect(hit)
    }
    setDrag(null)
    setPreview(null)
    setSnapGuide(null)
    setMarquee(null)
  }

  const [scrub, setScrub] = useState(false)
  const beginScrub = (e: React.PointerEvent) => {
    setScrub(true)
    onSeek(Math.max(0, pxToTime(localX(e), pxPerSec)))
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }

  const [markerDrag, setMarkerDrag] = useState<number | null>(null)

  const bgPointerDown = (e: React.PointerEvent) => {
    if (e.target !== e.currentTarget) return
    onSelect([])
    onMarkerSelect(null)
    setMarquee({ x0: localX(e), y0: localY(e), x1: localX(e), y1: localY(e) })
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }

  const view = (c: SeqClip) => preview?.get(c.id) ?? { start: c.start_s, dur: c.duration_s, trim: c.trim_start_s, track: c.track_id }

  return (
    <div className="flex border border-line rounded-el bg-panel overflow-hidden select-none" data-testid="editor-timeline">
      {/* -------- track headers -------- */}
      <div className="shrink-0 border-r border-line bg-well" style={{ width: HEADER_W }}>
        <div style={{ height: RULER_H + MARKER_H }} className="border-b border-line flex items-end px-2 pb-0.5 text-[10px] text-faint">markers</div>
        {tracks.map((t) => (
          <div key={t.id} className="flex items-center gap-1 px-2 border-b border-line/50" style={{ height: (TRACK_H[t.kind] ?? 48) + 4 }} data-testid={`track-header-${t.id}`}>
            <span className="font-mono text-[11px] w-7 text-faint">{t.label}</span>
            <button className={`w-5 h-5 rounded text-[9.5px] border ${t.muted ? 'bg-red-500/30 border-red-400/50 text-red-200' : 'border-line text-faint hover:text-fg'}`} title={t.kind === 'video' ? 'Hide track' : 'Mute track'} onClick={() => onTrackPatch(t.id, { muted: !t.muted })}>M</button>
            <button className={`w-5 h-5 rounded text-[9.5px] border ${t.solo ? 'bg-amber-500/30 border-amber-400/50 text-amber-200' : 'border-line text-faint hover:text-fg'}`} title="Solo track" onClick={() => onTrackPatch(t.id, { solo: !t.solo })}>S</button>
            <button className={`w-5 h-5 rounded text-[9.5px] border ${t.locked ? 'bg-sky-500/30 border-sky-400/50 text-sky-200' : 'border-line text-faint hover:text-fg'}`} title="Lock track" onClick={() => onTrackPatch(t.id, { locked: !t.locked })}>L</button>
            {t.clips.length === 0 && <button className="ml-auto text-faint hover:text-red-300 text-[11px]" title="Delete empty track" onClick={() => onTrackDelete(t.id)}>✕</button>}
          </div>
        ))}
        <div className="p-1.5 flex gap-1">
          {(['video', 'audio', 'caption'] as const).map((k) => (
            <button key={k} className="chip !text-[10px] !px-1.5" title={`Add ${k} track`} onClick={() => onAddTrack(k)}>+{k[0].toUpperCase()}</button>
          ))}
        </div>
      </div>
      {/* -------- scrollable lane -------- */}
      <div
        ref={(el) => {
          scrollRef.current = el
          if (el && el.clientWidth !== viewW) setViewW(el.clientWidth)
        }}
        className="relative overflow-x-auto overflow-y-hidden flex-1"
        onScroll={(e) => setScrollLeft((e.target as HTMLDivElement).scrollLeft)}
        onPointerMove={(e) => {
          if (scrub) onSeek(Math.max(0, pxToTime(localX(e), pxPerSec)))
          else if (markerDrag != null) onMarkerMove(markerDrag, Math.max(0, round3(pxToTime(localX(e), pxPerSec))))
          else onPointerMove(e)
        }}
        onPointerUp={() => {
          setScrub(false)
          setMarkerDrag(null)
          endDrag()
        }}
        onPointerLeave={() => {
          if (!drag && !marquee) return
        }}
      >
        <div style={{ width, height: trackTops.total + 8, position: 'relative' }} onPointerDown={bgPointerDown}>
          <Ruler width={width} pxPerSec={pxPerSec} onPointerDown={beginScrub} scrollLeft={scrollLeft} viewW={viewW} />
          {/* marker lane */}
          <div className="absolute left-0" style={{ top: RULER_H, height: MARKER_H, width }} onDoubleClick={(e) => onMarkerAdd(round3(pxToTime(localX(e), pxPerSec)))} data-testid="marker-lane">
            {seq.markers.map((m) => (
              <button
                key={m.id}
                className="absolute -translate-x-1/2 text-[11px] leading-none"
                style={{ left: timeToPx(m.t_s, pxPerSec), top: 2, color: markerColor(m.color) }}
                title={`${m.label || 'marker'} @ ${m.t_s}s`}
                onPointerDown={(e) => {
                  e.stopPropagation()
                  onMarkerSelect(m.id)
                  setMarkerDrag(m.id)
                  ;(e.target as Element).setPointerCapture?.(e.pointerId)
                }}
                data-testid={`marker-${m.id}`}
              >◆</button>
            ))}
          </div>
          {/* tracks */}
          {tracks.map((t) => {
            const { top, h } = trackTops.tops.get(t.id)!
            return (
              <div key={t.id} className={`absolute left-0 rounded-el ${t.locked ? 'opacity-60' : ''} ${t.kind === 'video' ? 'bg-ink/70' : t.kind === 'audio' ? 'bg-ink/40' : 'bg-ink/25'}`} style={{ top, height: h, width }} data-testid={`track-lane-${t.id}`}>
                {t.clips
                  .filter((c) => {
                    const v = view(c)
                    const x0 = timeToPx(v.start, pxPerSec)
                    return x0 + timeToPx(v.dur, pxPerSec) >= scrollLeft - 200 && x0 <= scrollLeft + viewW + 200
                  })
                  .map((c) => {
                    const v = view(c)
                    const movedTrack = v.track !== t.id
                    if (movedTrack && preview) return null
                    return (
                      <Clip key={c.id} clip={c} v={v} h={h} pxPerSec={pxPerSec} selected={selection.includes(c.id)} locked={t.locked} kind={t.kind} onDown={beginClipDrag} />
                    )
                  })}
                {/* clips previewed onto this track from another */}
                {preview &&
                  tracks
                    .filter((o) => o.id !== t.id)
                    .flatMap((o) => o.clips)
                    .filter((c) => preview.get(c.id)?.track === t.id)
                    .map((c) => <Clip key={`ghost-${c.id}`} clip={c} v={preview.get(c.id)!} h={h} pxPerSec={pxPerSec} selected locked={false} kind={t.kind} onDown={beginClipDrag} ghost />)}
              </div>
            )
          })}
          {/* snap guide */}
          {snapGuide != null && <div className="absolute top-0 bottom-0 w-px bg-ember pointer-events-none" style={{ left: timeToPx(snapGuide, pxPerSec) }} data-testid="snap-guide" />}
          {/* playhead */}
          <div className="absolute top-0 bottom-0 pointer-events-none" style={{ left: timeToPx(playhead, pxPerSec) }} data-testid="playhead">
            <div className="w-px h-full bg-red-400" />
            <div className="absolute -top-0 -translate-x-1/2 text-red-400 text-[10px]">▼</div>
          </div>
          {/* marquee */}
          {marquee && (
            <div className="absolute border border-ember/70 bg-ember/10 pointer-events-none" style={{ left: Math.min(marquee.x0, marquee.x1), top: Math.min(marquee.y0, marquee.y1), width: Math.abs(marquee.x1 - marquee.x0), height: Math.abs(marquee.y1 - marquee.y0) }} data-testid="marquee" />
          )}
        </div>
      </div>
    </div>
  )
}

function markerColor(c: string): string {
  return { amber: '#fbbf24', red: '#f87171', green: '#34d399', blue: '#60a5fa', purple: '#c084fc' }[c] ?? '#fbbf24'
}

function Clip({ clip, v, h, pxPerSec, selected, locked, kind, onDown, ghost }: {
  clip: SeqClip
  v: { start: number; dur: number; trim: number; track: number }
  h: number
  pxPerSec: number
  selected: boolean
  locked: boolean
  kind: string
  onDown: (e: React.PointerEvent, clip: SeqClip, mode: 'move' | 'trim-start' | 'trim-end') => void
  ghost?: boolean
}) {
  const w = Math.max(10, timeToPx(v.dur, pxPerSec))
  const showHandles = w > 26
  return (
    <div
      className={`absolute rounded-el border overflow-hidden ${ghost ? 'opacity-60' : ''} ${selected ? 'border-ember ring-1 ring-ember/60 bg-ember/20' : clip.missing_media && kind !== 'caption' ? 'border-amber-500/60 bg-amber-500/10' : 'border-line bg-panel'} ${locked ? 'cursor-not-allowed' : 'cursor-grab'}`}
      style={{ left: timeToPx(v.start, pxPerSec), top: 2, width: w, height: h - 4 }}
      onPointerDown={(e) => onDown(e, clip, 'move')}
      title={`${clip.label ?? clip.source_kind} · ${v.dur}s${clip.speed !== 1 ? ` · ${clip.speed}×` : ''}${clip.missing_media && kind !== 'caption' ? ' · no media' : ''}`}
      data-testid={`clip-${clip.id}`}
      data-selected={selected || undefined}
    >
      {clip.thumb_url && kind === 'video' && <img src={clip.thumb_url} alt="" className="absolute inset-0 w-full h-full object-cover opacity-40 pointer-events-none" />}
      <div className="relative px-1.5 py-0.5 text-[10.5px] leading-tight pointer-events-none">
        <div className="truncate text-fg/90">{kind === 'caption' ? String(clip.data?.text ?? '') || '(caption)' : clip.label ?? `#${clip.id}`}</div>
        <div className="text-faint tabular-nums">{v.dur.toFixed(1)}s{clip.speed !== 1 ? ` ${clip.speed}×` : ''}{clip.muted && kind !== 'caption' ? ' 🔇' : ''}</div>
      </div>
      {clip.transition_after && <span className="absolute right-0 top-0 h-full w-1.5 bg-ember/70 pointer-events-none" title={clip.transition_after.kind} />}
      {(clip.fade_in_s > 0 || clip.fade_out_s > 0) && (
        <svg className="absolute inset-0 w-full h-full pointer-events-none" preserveAspectRatio="none" viewBox="0 0 100 100">
          {clip.fade_in_s > 0 && <path d={`M0,100 L${Math.min(100, (clip.fade_in_s / v.dur) * 100)},0 L0,0 Z`} fill="rgba(0,0,0,0.35)" />}
          {clip.fade_out_s > 0 && <path d={`M100,100 L${Math.max(0, 100 - (clip.fade_out_s / v.dur) * 100)},0 L100,0 Z`} fill="rgba(0,0,0,0.35)" />}
        </svg>
      )}
      {showHandles && !locked && (
        <>
          <span className="absolute left-0 top-0 h-full w-2 cursor-ew-resize hover:bg-ember/50" onPointerDown={(e) => onDown(e, clip, 'trim-start')} data-testid={`trim-start-${clip.id}`} />
          <span className="absolute right-0 top-0 h-full w-2 cursor-ew-resize hover:bg-ember/50" onPointerDown={(e) => onDown(e, clip, 'trim-end')} data-testid={`trim-end-${clip.id}`} />
        </>
      )}
    </div>
  )
}

function Ruler({ width, pxPerSec, onPointerDown, scrollLeft, viewW }: { width: number; pxPerSec: number; onPointerDown: (e: React.PointerEvent) => void; scrollLeft: number; viewW: number }) {
  const ref = useRef<HTMLCanvasElement | null>(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    const w = Math.min(width, viewW + 400)
    canvas.width = w * dpr
    canvas.height = RULER_H * dpr
    canvas.style.width = `${w}px`
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, RULER_H)
    const { major, minor } = tickInterval(pxPerSec)
    const x0 = Math.max(0, scrollLeft - 200)
    const t0 = Math.floor(x0 / pxPerSec / minor) * minor
    ctx.fillStyle = 'rgba(148,148,160,0.9)'
    ctx.strokeStyle = 'rgba(148,148,160,0.4)'
    ctx.font = '9.5px ui-monospace, monospace'
    for (let t = t0; timeToPx(t, pxPerSec) < x0 + w; t += minor) {
      const x = timeToPx(t, pxPerSec) - x0
      const isMajor = Math.abs(t / major - Math.round(t / major)) < 1e-6
      ctx.beginPath()
      ctx.moveTo(x, isMajor ? 8 : 16)
      ctx.lineTo(x, RULER_H)
      ctx.stroke()
      if (isMajor) {
        const mm = Math.floor(t / 60)
        const ss = Math.round(t % 60)
        ctx.fillText(`${mm}:${String(ss).padStart(2, '0')}`, x + 3, 10)
      }
    }
  }, [width, pxPerSec, scrollLeft, viewW])
  return (
    <div className="absolute top-0 left-0 border-b border-line bg-well/60 cursor-col-resize" style={{ width, height: RULER_H }} onPointerDown={onPointerDown} data-testid="ruler">
      <canvas ref={ref} style={{ position: 'sticky', left: 0, marginLeft: Math.max(0, scrollLeft - 200) }} height={RULER_H} />
    </div>
  )
}

export type { FlatSegment }
