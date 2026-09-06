// Editor sequence client + pure timeline math (Editor spec E4). Shapes
// mirror backend/promptforge/film/sequence.py. Everything interactive
// (snapping, geometry, flatten for playback) is a pure exported function so
// it is unit-testable and rendering stays a thin layer.
import { api } from '../api'

// ---------------------------------------------------------------- types ----
export type TrackKind = 'video' | 'audio' | 'caption'
export type ClipSource = 'take' | 'footage' | 'audio' | 'caption'

export interface SeqClip {
  id: number
  track_id: number
  source_kind: ClipSource
  take_id: number | null
  footage_id: number | null
  audio_track_id: number | null
  shot_id: number | null
  label: string | null
  start_s: number
  end_s: number
  duration_s: number
  trim_start_s: number
  speed: number
  gain_db: number
  muted: boolean
  fade_in_s: number
  fade_out_s: number
  effects: Record<string, unknown>
  transition_after: { kind: string; duration_s: number } | null
  data: Record<string, any>
  media_url: string | null
  thumb_url: string | null
  media_kind: string | null
  source_duration_s: number | null
  missing_media: boolean
}

export interface SeqTrack {
  id: number
  kind: TrackKind
  position: number
  label: string
  muted: boolean
  solo: boolean
  locked: boolean
  clips: SeqClip[]
}

export interface SeqMarker {
  id: number
  t_s: number
  label: string
  color: string
  note: string | null
}

export interface Sequence {
  project_id: number
  exists: boolean
  runtime_s: number
  runtime_tc: string
  fps: number
  aspect_ratio: string | null
  tracks: SeqTrack[]
  markers: SeqMarker[]
  can_undo: boolean
  can_redo: boolean
}

export interface FlatSegment {
  type: 'clip' | 'gap'
  clip_id?: number
  start_s: number
  duration_s: number
  trim_start_s?: number
  speed?: number
  media_url?: string | null
  media_kind?: string | null
  muted?: boolean
  gain_db?: number
  missing?: boolean
}

// ------------------------------------------------------------- geometry ----
/** Discrete px-per-second zoom ladder (ruler ticks derive from it). */
export const ZOOM_LADDER = [8, 13, 20, 32, 50, 80, 125, 200, 320]
export const DEFAULT_ZOOM_INDEX = 3

export const timeToPx = (t: number, pxPerSec: number) => t * pxPerSec
export const pxToTime = (px: number, pxPerSec: number) => px / pxPerSec

/** Ruler tick spacing for a zoom level: major interval in seconds chosen so
 *  labels stay ≥ ~70px apart, minor divisions for the in-between ticks. */
export function tickInterval(pxPerSec: number): { major: number; minor: number } {
  const options = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300]
  const major = options.find((o) => o * pxPerSec >= 70) ?? 600
  return { major, minor: major / (major >= 60 ? 4 : major >= 5 ? 5 : 2) }
}

/** HH:MM:SS:FF timecode (frames at the project fps). */
export function fmtTcF(t: number, fps: number): string {
  const s = Math.max(0, t)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  const f = Math.floor((s - Math.floor(s)) * fps)
  const p = (v: number, n = 2) => String(v).padStart(n, '0')
  return `${p(h)}:${p(m)}:${p(sec)}:${p(f)}`
}

// ------------------------------------------------------------- snapping ----
export interface SnapResult {
  start: number
  target: number | null
}

/** Candidate snap times: every clip edge (excluding the dragged clips),
 *  markers, the playhead, and 0. */
export function snapPoints(seq: Sequence, excludeClipIds: number[], playhead: number | null): number[] {
  const ex = new Set(excludeClipIds)
  const pts = new Set<number>([0])
  for (const t of seq.tracks)
    for (const c of t.clips) {
      if (ex.has(c.id)) continue
      pts.add(c.start_s)
      pts.add(round3(c.start_s + c.duration_s))
    }
  for (const m of seq.markers) pts.add(m.t_s)
  if (playhead != null) pts.add(round3(playhead))
  return [...pts].sort((a, b) => a - b)
}

/** Snap a proposed clip position: BOTH edges are candidates and the closer
 *  one wins (trailing-edge snap shifts start back by the duration). */
export function snapDrag(proposedStart: number, duration: number, points: number[], thresholdS: number): SnapResult {
  let best: SnapResult = { start: proposedStart, target: null }
  let bestDelta = Infinity
  for (const p of points) {
    const dStart = Math.abs(p - proposedStart)
    if (dStart <= thresholdS && dStart < bestDelta) {
      best = { start: p, target: p }
      bestDelta = dStart
    }
    const dEnd = Math.abs(p - (proposedStart + duration))
    if (dEnd <= thresholdS && dEnd < bestDelta) {
      best = { start: round3(p - duration), target: p }
      bestDelta = dEnd
    }
  }
  return best
}

/** Snap a single time value (trim edges, playhead, markers). */
export function snapTime(proposed: number, points: number[], thresholdS: number): SnapResult {
  let best: SnapResult = { start: proposed, target: null }
  let delta = Infinity
  for (const p of points) {
    const d = Math.abs(p - proposed)
    if (d <= thresholdS && d < delta) {
      best = { start: p, target: p }
      delta = d
    }
  }
  return best
}

export const round3 = (v: number) => Math.round(v * 1000) / 1000

/** Does placing [start, start+duration) on `track` collide with another clip? */
export function collides(track: SeqTrack, start: number, duration: number, ignoreId?: number): boolean {
  const end = start + duration
  return track.clips.some((c) => c.id !== ignoreId && c.start_s < end - 1e-6 && c.start_s + c.duration_s > start + 1e-6)
}

/** Free slot at/after `want` on the track for a clip of `duration` (used on
 *  drops so a collision nudges to the nearest opening instead of failing). */
export function nearestFreeStart(track: SeqTrack, want: number, duration: number, ignoreId?: number): number {
  if (!collides(track, want, duration, ignoreId)) return Math.max(0, round3(want))
  const clips = [...track.clips].filter((c) => c.id !== ignoreId).sort((a, b) => a.start_s - b.start_s)
  let t = 0
  const slots: number[] = []
  for (const c of clips) {
    if (c.start_s - t >= duration - 1e-6) slots.push(t)
    t = Math.max(t, c.start_s + c.duration_s)
  }
  slots.push(t)
  let best = slots[0] ?? 0
  for (const s of slots) if (Math.abs(s - want) < Math.abs(best - want)) best = s
  return round3(Math.max(0, best))
}

// -------------------------------------------------------------- flatten ----
/** Client mirror of sequence.flatten's video half — what the player runs.
 *  Topmost unmuted video track wins; empty space is black. */
export function flattenVideo(seq: Sequence): FlatSegment[] {
  const vids = seq.tracks.filter((t) => t.kind === 'video')
  const solo = vids.filter((t) => t.solo)
  const audible = solo.length ? solo : vids.filter((t) => !t.muted)
  const layer = new Map(audible.map((t) => [t.id, t.position]))
  const clips = audible.flatMap((t) => t.clips)
  const runtime = seq.runtime_s || 0
  const bounds = [...new Set([0, ...clips.flatMap((c) => [c.start_s, round3(c.start_s + c.duration_s)]), runtime])].sort((a, b) => a - b)
  const out: FlatSegment[] = []
  for (let i = 0; i < bounds.length - 1; i++) {
    const a = bounds[i]
    const b = bounds[i + 1]
    if (b - a < 1e-6) continue
    const cover = clips.filter((c) => c.start_s <= a + 1e-6 && c.start_s + c.duration_s >= b - 1e-6)
    if (!cover.length) {
      out.push({ type: 'gap', start_s: a, duration_s: round3(b - a) })
      continue
    }
    const top = cover.reduce((x, y) => ((layer.get(y.track_id) ?? 0) > (layer.get(x.track_id) ?? 0) || ((layer.get(y.track_id) ?? 0) === (layer.get(x.track_id) ?? 0) && y.id > x.id) ? y : x))
    out.push({
      type: 'clip', clip_id: top.id, start_s: a, duration_s: round3(b - a),
      trim_start_s: round3(top.trim_start_s + (a - top.start_s) * top.speed), speed: top.speed,
      media_url: top.media_url, media_kind: top.media_kind, muted: top.muted, gain_db: top.gain_db,
      missing: top.missing_media,
    })
  }
  // merge continuous same-clip segments
  const merged: FlatSegment[] = []
  for (const seg of out) {
    const prev = merged[merged.length - 1]
    if (prev && prev.type === seg.type && prev.clip_id === seg.clip_id && Math.abs(prev.start_s + prev.duration_s - seg.start_s) < 1e-6 && (seg.type === 'gap' || prev.clip_id != null)) {
      prev.duration_s = round3(prev.duration_s + seg.duration_s)
    } else merged.push({ ...seg })
  }
  return merged
}

/** The flat segment under a time, for the player. */
export function segmentAt(segments: FlatSegment[], t: number): FlatSegment | null {
  return segments.find((s) => t >= s.start_s - 1e-6 && t < s.start_s + s.duration_s - 1e-6) ?? segments[segments.length - 1] ?? null
}

/** Audio clips that should sound at playback time (audible tracks only). */
export function audioAt(seq: Sequence, t: number): SeqClip[] {
  const auds = seq.tracks.filter((tr) => tr.kind === 'audio')
  const solo = auds.filter((tr) => tr.solo)
  const audible = solo.length ? solo : auds.filter((tr) => !tr.muted)
  return audible.flatMap((tr) => tr.clips).filter((c) => !c.muted && !!c.media_url && t >= c.start_s && t < c.start_s + c.duration_s)
}

/** Caption text visible at a time (unmuted caption tracks). */
export function captionsAt(seq: Sequence, t: number): string[] {
  return seq.tracks
    .filter((tr) => tr.kind === 'caption' && !tr.muted)
    .flatMap((tr) => tr.clips)
    .filter((c) => t >= c.start_s && t < c.start_s + c.duration_s)
    .map((c) => String(c.data?.text ?? ''))
    .filter(Boolean)
}

// ------------------------------------------------------------ shortcuts ----
export interface ShortcutDef {
  keys: string[]
  label: string
  group: string
}
/** One registry drives the handler AND the help overlay/tooltips. */
export const SHORTCUTS: Record<string, ShortcutDef> = {
  play: { keys: ['Space', 'k'], label: 'Play / pause', group: 'Playback' },
  prevFrame: { keys: ['ArrowLeft'], label: 'Previous frame (Shift: ×10)', group: 'Playback' },
  nextFrame: { keys: ['ArrowRight'], label: 'Next frame (Shift: ×10)', group: 'Playback' },
  home: { keys: ['Home'], label: 'Go to start', group: 'Playback' },
  end: { keys: ['End'], label: 'Go to end', group: 'Playback' },
  loop: { keys: ['l'], label: 'Toggle loop', group: 'Playback' },
  split: { keys: ['s'], label: 'Split at playhead', group: 'Editing' },
  del: { keys: ['Delete', 'Backspace'], label: 'Delete selection', group: 'Editing' },
  rippleDel: { keys: ['Shift+Delete', 'Shift+Backspace'], label: 'Ripple delete selection', group: 'Editing' },
  snap: { keys: ['n'], label: 'Toggle snapping', group: 'Editing' },
  marker: { keys: ['m'], label: 'Add marker at playhead', group: 'Editing' },
  undo: { keys: ['Mod+z'], label: 'Undo', group: 'History' },
  redo: { keys: ['Mod+Shift+z', 'Mod+y'], label: 'Redo', group: 'History' },
  zoomIn: { keys: ['='], label: 'Zoom in', group: 'View' },
  zoomOut: { keys: ['-'], label: 'Zoom out', group: 'View' },
  selectAll: { keys: ['Mod+a'], label: 'Select all clips', group: 'Editing' },
  help: { keys: ['?'], label: 'Keyboard shortcuts', group: 'View' },
}

/** Normalise a KeyboardEvent to the registry's key syntax. */
export function eventKey(e: KeyboardEvent | React.KeyboardEvent): string {
  const mods = `${e.metaKey || e.ctrlKey ? 'Mod+' : ''}${e.shiftKey ? 'Shift+' : ''}`
  const k = e.key === ' ' ? 'Space' : e.key.length === 1 ? e.key.toLowerCase() : e.key
  // '?' already implies shift — don't double it
  if (e.key === '?') return '?'
  return mods + k
}

export function matchShortcut(e: KeyboardEvent | React.KeyboardEvent): string | null {
  const key = eventKey(e)
  for (const [action, def] of Object.entries(SHORTCUTS)) if (def.keys.includes(key)) return action
  return null
}

export function shortcutHint(action: string): string {
  const def = SHORTCUTS[action]
  if (!def) return ''
  const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform)
  return def.keys[0].replace('Mod', isMac ? '⌘' : 'Ctrl')
}

// ----------------------------------------------------------------- api -----
const F = '/api/film'
export const seq = {
  get: (pid: number) => api.get<Sequence>(`${F}/projects/${pid}/sequence`),
  build: (pid: number, replace = false) => api.post<Sequence>(`${F}/projects/${pid}/sequence/build`, { replace }),
  drop: (pid: number) => api.delete<{ ok: boolean }>(`${F}/projects/${pid}/sequence`),
  preview: (pid: number) => api.get<any>(`${F}/projects/${pid}/sequence/preview`),
  addTrack: (pid: number, kind: TrackKind, label?: string) => api.post<Sequence>(`${F}/projects/${pid}/sequence/tracks`, { kind, label }),
  patchTrack: (tid: number, body: Partial<Pick<SeqTrack, 'label' | 'muted' | 'solo' | 'locked' | 'position'>>) =>
    api.patch<Sequence>(`${F}/sequence/tracks/${tid}`, body),
  deleteTrack: (tid: number) => api.delete<Sequence>(`${F}/sequence/tracks/${tid}`),
  addClip: (pid: number, body: { track_id: number; source_kind: ClipSource; start_s: number; duration_s?: number; take_id?: number; footage_id?: number; audio_track_id?: number; shot_id?: number; label?: string; data?: Record<string, unknown> }) =>
    api.post<Sequence>(`${F}/projects/${pid}/sequence/clips`, body),
  patchClip: (cid: number, body: Record<string, unknown>) => api.patch<Sequence>(`${F}/sequence/clips/${cid}`, body),
  batch: (pid: number, ops: Record<string, unknown>[], label: string) =>
    api.post<Sequence>(`${F}/projects/${pid}/sequence/clips/batch`, { ops, label }),
  split: (cid: number, at_s: number) => api.post<Sequence>(`${F}/sequence/clips/${cid}/split`, { at_s }),
  setTake: (cid: number, take_id: number) => api.post<Sequence>(`${F}/sequence/clips/${cid}/take`, { take_id }),
  deleteClips: (pid: number, ids: number[], ripple = false) =>
    api.post<Sequence>(`${F}/projects/${pid}/sequence/delete-clips`, { ids, ripple }),
  insertGap: (pid: number, at_s: number, gap_s: number) =>
    api.post<Sequence>(`${F}/projects/${pid}/sequence/insert-gap`, { at_s, gap_s }),
  addMarker: (pid: number, body: { t_s: number; label?: string; color?: string; note?: string }) =>
    api.post<Sequence>(`${F}/projects/${pid}/sequence/markers`, body),
  patchMarker: (mid: number, body: Record<string, unknown>) => api.patch<Sequence>(`${F}/sequence/markers/${mid}`, body),
  deleteMarker: (mid: number) => api.delete<Sequence>(`${F}/sequence/markers/${mid}`),
  undo: (pid: number) => api.post<Sequence>(`${F}/projects/${pid}/sequence/undo`),
  redo: (pid: number) => api.post<Sequence>(`${F}/projects/${pid}/sequence/redo`),
  history: (pid: number) => api.get<{ undo: any[]; redo: any[] }>(`${F}/projects/${pid}/sequence/history`),
}
