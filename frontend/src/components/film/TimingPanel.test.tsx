import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Timeline } from '../../lib/film'
import { runtimeOf, snapDuration, TimingPanel, widthFor } from './TimingPanel'

const tl: Timeline = {
  project_id: 1, runtime_s: 13, runtime_tc: '00:00:13.0', target_runtime_s: 60, target_tc: '00:01:00.0', default_scene_gap_s: 0.5,
  default_transition: { kind: 'cut', duration_s: 0 }, fps: 24, scene_count: 2, shot_count: 3,
  scenes: [
    { id: 1, number: 1, title: 'One', start_s: 0, end_s: 8.5, duration_s: 8.5, tc_in: '00:00:00.0', tc_out: '00:00:08.5', gap_after_s: 0.5, gap_inherited: true, transition: null, shot_count: 2, approved: false,
      shots: [{ id: 11, label: '1.1', title: 'wide', start_s: 0, end_s: 6, duration_s: 6, status: 'planned', media_strategy: 'ai_video', transition: { kind: 'dissolve', duration_s: 0.5 }, tc_in: '00:00:00.0', tc_out: '00:00:06.0' },
              { id: 12, label: '1.2', title: 'close', start_s: 6, end_s: 8.5, duration_s: 2.5, status: 'planned', media_strategy: 'ai_video', transition: null, tc_in: '00:00:06.0', tc_out: '00:00:08.5' }] },
    { id: 2, number: 2, title: 'Two', start_s: 9, end_s: 13, duration_s: 4, tc_in: '00:00:09.0', tc_out: '00:00:13.0', gap_after_s: null, gap_inherited: true, transition: null, shot_count: 1, approved: false,
      shots: [{ id: 21, label: '2.1', title: null, start_s: 9, end_s: 13, duration_s: 4, status: 'planned', media_strategy: 'ai_video', transition: null, tc_in: '00:00:09.0', tc_out: '00:00:13.0' }] },
  ],
}

describe('timing helpers', () => {
  it('computes runtime with inherited and overridden gaps', () => {
    expect(runtimeOf(tl, 0.5)).toBe(13)
    expect(runtimeOf({ scenes: [{ ...tl.scenes[0], gap_after_s: 2, gap_inherited: false }, tl.scenes[1]] }, 0.5)).toBe(14.5)
    expect(runtimeOf(tl, 1.5)).toBe(14)                                 // default change reaches inheriting scenes only
  })
  it('keeps proportional widths readable', () => {
    expect(widthFor(10, 26)).toBe(260)
    expect(widthFor(0.2, 26)).toBe(28)
    expect(widthFor(10, 26)).toBeGreaterThan(widthFor(2, 26))
  })
  it('snaps durations to the half-second grid within bounds', () => {
    expect(snapDuration(4.3)).toBe(4.5)
    expect(snapDuration(0.1)).toBe(0.5)
    expect(snapDuration(9999)).toBe(600)
  })
})

describe('<TimingPanel>', () => {
  it('shows the runtime, target delta and per-scene gaps with inherited/override labels', () => {
    const onSceneGap = vi.fn()
    render(<TimingPanel tl={tl} view="scene" onView={() => undefined} onDefaultGap={() => undefined} onApplyAll={() => undefined} onSceneGap={onSceneGap} onShotDuration={() => undefined} />)
    expect(screen.getByTestId('runtime')).toHaveTextContent('00:00:13.0')
    expect(screen.getByText('(-47.0s)')).toBeInTheDocument()
    expect(screen.getByText('0.5s inherited')).toBeInTheDocument()
    const gap = screen.getByLabelText('Gap after scene 1') as HTMLInputElement
    fireEvent.change(gap, { target: { value: '2' } })
    fireEvent.keyDown(gap, { key: 'Enter' })
    expect(onSceneGap).toHaveBeenCalledWith(1, 2)
  })
  it('applies the default gap to all scenes and resets overrides through the callbacks', () => {
    const onApplyAll = vi.fn()
    const onDefaultGap = vi.fn()
    render(<TimingPanel tl={tl} view="scene" onView={() => undefined} onDefaultGap={onDefaultGap} onApplyAll={onApplyAll} onSceneGap={() => undefined} onShotDuration={() => undefined} />)
    fireEvent.change(screen.getByLabelText('Default scene gap seconds'), { target: { value: '1.25' } })
    fireEvent.click(screen.getByText('Apply this gap to all scenes'))
    expect(onApplyAll).toHaveBeenCalledWith(1.25)
    fireEvent.click(screen.getByText('Reset overrides'))
    expect(onDefaultGap).toHaveBeenCalledWith(1.25, true)
  })
  it('lets the shot view type an exact duration', () => {
    const onShotDuration = vi.fn()
    render(<TimingPanel tl={tl} view="shot" onView={() => undefined} onDefaultGap={() => undefined} onApplyAll={() => undefined} onSceneGap={() => undefined} onShotDuration={onShotDuration} />)
    fireEvent.change(screen.getByLabelText('Duration of shot 1.2'), { target: { value: '3.3' } })
    expect(onShotDuration).toHaveBeenCalledWith(12, 3.5)
  })
  it('renders the proportional strip with gaps between scenes', () => {
    render(<TimingPanel tl={tl} view="timeline" onView={() => undefined} onDefaultGap={() => undefined} onApplyAll={() => undefined} onSceneGap={() => undefined} onShotDuration={() => undefined} />)
    const wide = screen.getByTestId('strip-shot-11')
    const close = screen.getByTestId('strip-shot-12')
    expect(parseInt(wide.style.width)).toBeGreaterThan(parseInt(close.style.width))
    expect(screen.getByTitle('gap 0.5s')).toBeInTheDocument()
  })
})
