// Timeline component tests (E4): render, selection, track controls, marker
// add. Pointer gestures are exercised end-to-end by the Playwright journey;
// here we verify the wiring jsdom can reach.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Sequence } from '../../lib/editor'
import { Timeline } from './Timeline'

const seq: Sequence = {
  project_id: 1, exists: true, runtime_s: 10, runtime_tc: '00:00:10.0', fps: 24, aspect_ratio: '16:9',
  can_undo: false, can_redo: false,
  markers: [{ id: 5, t_s: 2, label: 'beat', color: 'red', note: null }],
  tracks: [
    { id: 1, kind: 'video', position: 0, label: 'V1', muted: false, solo: false, locked: false,
      clips: [{ id: 11, track_id: 1, source_kind: 'take', take_id: 1, footage_id: null, audio_track_id: null, shot_id: 7, label: '1.1 A', start_s: 0, end_s: 4, duration_s: 4, trim_start_s: 0, speed: 1, gain_db: 0, muted: false, fade_in_s: 0.5, fade_out_s: 0, effects: {}, transition_after: { kind: 'dissolve', duration_s: 0.5 }, data: {}, media_url: '/m.mp4', thumb_url: null, media_kind: 'video', source_duration_s: 6, missing_media: false }] },
    { id: 2, kind: 'audio', position: 0, label: 'A1', muted: false, solo: false, locked: true, clips: [] },
    { id: 3, kind: 'caption', position: 0, label: 'C1', muted: false, solo: false, locked: false, clips: [] },
  ],
}

const noop = () => undefined

function draw(overrides: Partial<React.ComponentProps<typeof Timeline>> = {}) {
  const props: React.ComponentProps<typeof Timeline> = {
    seq, pxPerSec: 32, playhead: 1, selection: [], snapping: true, playing: false,
    onSeek: noop, onSelect: noop, onCommit: noop, onTrackPatch: noop, onTrackDelete: noop,
    onAddTrack: noop, onMarkerMove: noop, onMarkerAdd: noop, onMarkerSelect: noop,
    ...overrides,
  }
  return render(<Timeline {...props} />)
}

describe('Timeline', () => {
  it('renders tracks, clips, markers, playhead and transition/fade cues', () => {
    draw()
    expect(screen.getByTestId('editor-timeline')).toBeTruthy()
    expect(screen.getAllByTestId(/^track-lane-/)).toHaveLength(3)
    expect(screen.getByTestId('clip-11')).toBeTruthy()
    expect(screen.getByTestId('marker-5')).toBeTruthy()
    expect(screen.getByTestId('playhead')).toBeTruthy()
    expect(screen.getByTitle('dissolve')).toBeTruthy()
  })
  it('pointer-down on a clip selects it; locked tracks do not select', () => {
    const onSelect = vi.fn()
    draw({ onSelect })
    fireEvent.pointerDown(screen.getByTestId('clip-11'))
    expect(onSelect).toHaveBeenCalledWith([11])
  })
  it('selected clips render highlighted', () => {
    draw({ selection: [11] })
    expect(screen.getByTestId('clip-11').dataset.selected).toBe('true')
  })
  it('track M/S/L buttons patch the track', () => {
    const onTrackPatch = vi.fn()
    draw({ onTrackPatch })
    const header = screen.getByTestId('track-header-1')
    fireEvent.click(header.querySelector('button[title="Hide track"]')!)
    expect(onTrackPatch).toHaveBeenCalledWith(1, { muted: true })
    fireEvent.click(header.querySelector('button[title="Solo track"]')!)
    expect(onTrackPatch).toHaveBeenCalledWith(1, { solo: true })
    fireEvent.click(header.querySelector('button[title="Lock track"]')!)
    expect(onTrackPatch).toHaveBeenCalledWith(1, { locked: true })
  })
  it('double-click on the marker lane adds a marker at that time', () => {
    const onMarkerAdd = vi.fn()
    draw({ onMarkerAdd })
    fireEvent.doubleClick(screen.getByTestId('marker-lane'))
    expect(onMarkerAdd).toHaveBeenCalled()
  })
  it('empty tracks offer delete; add-track buttons exist for all kinds', () => {
    const onTrackDelete = vi.fn()
    const onAddTrack = vi.fn()
    draw({ onTrackDelete, onAddTrack })
    fireEvent.click(screen.getByTestId('track-header-2').querySelector('button[title="Delete empty track"]')!)
    expect(onTrackDelete).toHaveBeenCalledWith(2)
    fireEvent.click(screen.getByTitle('Add video track'))
    expect(onAddTrack).toHaveBeenCalledWith('video')
  })
})
