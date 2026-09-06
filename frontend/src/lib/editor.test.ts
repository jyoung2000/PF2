// Editor pure-helper tests (E4): snapping, flatten, collision, shortcuts.
import { describe, expect, it } from 'vitest'
import {
  audioAt, captionsAt, collides, flattenVideo, fmtTcF, matchShortcut, nearestFreeStart,
  segmentAt, Sequence, snapDrag, snapPoints, snapTime, tickInterval,
} from './editor'

const clip = (id: number, track_id: number, start: number, dur: number, extra: Partial<any> = {}) => ({
  id, track_id, source_kind: 'take', take_id: id, footage_id: null, audio_track_id: null,
  shot_id: null, label: `c${id}`, start_s: start, end_s: start + dur, duration_s: dur,
  trim_start_s: 0, speed: 1, gain_db: 0, muted: false, fade_in_s: 0, fade_out_s: 0,
  effects: {}, transition_after: null, data: {}, media_url: `/m/${id}.mp4`, thumb_url: null,
  media_kind: 'video', source_duration_s: 10, missing_media: false, ...extra,
})

const seqOf = (tracks: any[], runtime = 0, markers: any[] = []): Sequence => ({
  project_id: 1, exists: true,
  runtime_s: runtime || Math.max(0, ...tracks.flatMap((t) => t.clips.map((c: any) => c.start_s + c.duration_s))),
  runtime_tc: '', fps: 24, aspect_ratio: '16:9', tracks, markers, can_undo: false, can_redo: false,
})

const track = (id: number, kind: string, clips: any[], extra: Partial<any> = {}) => ({
  id, kind, position: 0, label: '', muted: false, solo: false, locked: false, clips, ...extra,
})

describe('snapping', () => {
  const seq = seqOf([track(1, 'video', [clip(1, 1, 0, 4), clip(2, 1, 6, 2)])], 0, [{ id: 9, t_s: 5, label: '', color: 'amber', note: null }])
  it('collects clip edges, markers, playhead and zero', () => {
    expect(snapPoints(seq, [2], 3.3)).toEqual([0, 3.3, 4, 5])
  })
  it('snaps the closer edge — trailing edge shifts start back', () => {
    // leading edge near 4
    expect(snapDrag(3.9, 2, [0, 4], 0.25)).toEqual({ start: 4, target: 4 })
    // trailing edge near 6 wins (leading edge is nowhere near a point)
    expect(snapDrag(4.6, 1.5, [0, 4, 6], 0.25)).toEqual({ start: 4.5, target: 6 })
    // outside the threshold nothing snaps
    expect(snapDrag(2.5, 1, [0, 4, 6], 0.25).target).toBeNull()
  })
  it('snapTime picks the nearest point inside the threshold', () => {
    expect(snapTime(3.9, [0, 4], 0.2)).toEqual({ start: 4, target: 4 })
    expect(snapTime(3.5, [0, 4], 0.2).target).toBeNull()
  })
})

describe('collision + free slots', () => {
  const t = track(1, 'video', [clip(1, 1, 0, 4), clip(2, 1, 6, 2)])
  it('detects overlap and honours the ignore id', () => {
    expect(collides(t as any, 3, 2)).toBe(true)
    expect(collides(t as any, 4, 2)).toBe(false)
    expect(collides(t as any, 3, 2, 1)).toBe(false)
  })
  it('nudges to the nearest opening', () => {
    expect(nearestFreeStart(t as any, 1, 2)).toBe(4)     // gap 4..6 fits
    expect(nearestFreeStart(t as any, 7, 3)).toBe(8)     // after the last clip
    expect(nearestFreeStart(t as any, 4.5, 2)).toBe(4)
  })
})

describe('flattenVideo', () => {
  it('slices around a top-track clip and resumes the source', () => {
    const v1 = track(1, 'video', [clip(1, 1, 0, 6)], { position: 0 })
    const v2 = track(2, 'video', [clip(2, 2, 2, 2)], { position: 1 })
    const segs = flattenVideo(seqOf([v1, v2]))
    expect(segs.map((s) => [s.type, s.start_s, s.duration_s])).toEqual([
      ['clip', 0, 2], ['clip', 2, 2], ['clip', 4, 2],
    ])
    expect(segs[0].clip_id).toBe(1)
    expect(segs[1].clip_id).toBe(2)
    expect(segs[2].clip_id).toBe(1)
    expect(segs[2].trim_start_s).toBe(4)      // V1 resumes 4s into its source
  })
  it('honours mute/solo, trim and speed; empty space is a gap', () => {
    const v1 = track(1, 'video', [clip(1, 1, 1, 2, { trim_start_s: 0.5, speed: 2 })])
    const segs = flattenVideo(seqOf([v1], 4))
    expect(segs.map((s) => s.type)).toEqual(['gap', 'clip', 'gap'])
    expect(segs[1].trim_start_s).toBe(0.5)
    expect(segs[1].speed).toBe(2)
    const muted = flattenVideo(seqOf([track(1, 'video', [clip(1, 1, 0, 2)], { muted: true })], 2))
    expect(muted.every((s) => s.type === 'gap')).toBe(true)
    const soloed = flattenVideo(seqOf([
      track(1, 'video', [clip(1, 1, 0, 2)]),
      track(2, 'video', [clip(2, 2, 0, 2)], { solo: true, position: 1 }),
    ]))
    expect(soloed).toHaveLength(1)
    expect(soloed[0].clip_id).toBe(2)
  })
  it('segmentAt finds the segment under the playhead', () => {
    const segs = flattenVideo(seqOf([track(1, 'video', [clip(1, 1, 0, 2), clip(2, 1, 3, 2)])]))
    expect(segmentAt(segs, 1)?.clip_id).toBe(1)
    expect(segmentAt(segs, 2.5)?.type).toBe('gap')
    expect(segmentAt(segs, 4)?.clip_id).toBe(2)
  })
})

describe('audio + captions at time', () => {
  const seq = seqOf([
    track(1, 'video', []),
    track(2, 'audio', [clip(5, 2, 1, 4, { source_kind: 'audio', media_url: '/a.wav' })]),
    track(3, 'caption', [clip(6, 3, 0, 2, { source_kind: 'caption', media_url: null, data: { text: 'Hello' } })]),
  ], 6)
  it('returns audible clips and visible captions', () => {
    expect(audioAt(seq, 2).map((c) => c.id)).toEqual([5])
    expect(audioAt(seq, 0.5)).toHaveLength(0)
    expect(captionsAt(seq, 1)).toEqual(['Hello'])
    expect(captionsAt(seq, 3)).toEqual([])
  })
  it('muted caption tracks hide their text', () => {
    const muted = { ...seq, tracks: seq.tracks.map((t) => (t.kind === 'caption' ? { ...t, muted: true } : t)) }
    expect(captionsAt(muted, 1)).toEqual([])
  })
})

describe('misc', () => {
  it('tick intervals keep labels apart', () => {
    expect(tickInterval(200).major).toBe(0.5)
    expect(tickInterval(80).major).toBe(1)
    expect(tickInterval(8).major).toBe(10)
  })
  it('timecode renders frames', () => {
    expect(fmtTcF(0, 24)).toBe('00:00:00:00')
    expect(fmtTcF(61.5, 24)).toBe('00:01:01:12')
  })
  it('matches shortcuts incl. modifiers and ignores unknown keys', () => {
    expect(matchShortcut({ key: ' ', metaKey: false, ctrlKey: false, shiftKey: false } as any)).toBe('play')
    expect(matchShortcut({ key: 'z', metaKey: true, ctrlKey: false, shiftKey: false } as any)).toBe('undo')
    expect(matchShortcut({ key: 'z', metaKey: true, ctrlKey: false, shiftKey: true } as any)).toBe('redo')
    expect(matchShortcut({ key: '?', metaKey: false, ctrlKey: false, shiftKey: true } as any)).toBe('help')
    expect(matchShortcut({ key: 'q', metaKey: false, ctrlKey: false, shiftKey: false } as any)).toBeNull()
  })
})
