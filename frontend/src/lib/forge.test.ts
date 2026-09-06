import { describe, expect, it } from 'vitest'
import { capabilityBadges, fmtUsd, layoutColumns, ModelEntry, WfGraph } from './forge'

describe('layoutColumns', () => {
  const graph: WfGraph = {
    nodes: [
      { id: 'in', type: 'input', config: {} },
      { id: 'compile', type: 'compile', config: {} },
      { id: 'gen', type: 'generate_image', config: {} },
      { id: 'stt', type: 'transcribe_audio', config: {} },
    ],
    edges: [
      { from: 'in', to: 'compile' },
      { from: 'compile', to: 'gen' },
      { from: 'in', to: 'stt' },
    ],
  }
  it('places nodes in dependency columns', () => {
    expect(layoutColumns(graph)).toEqual([['in'], ['compile', 'stt'], ['gen']])
  })
  it('stops on a cycle instead of hanging (validation reports it)', () => {
    const cyclic: WfGraph = {
      nodes: [{ id: 'a', type: 'prompt', config: {} }, { id: 'b', type: 'export', config: {} }],
      edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'a' }],
    }
    expect(layoutColumns(cyclic)).toEqual([])
  })
})

describe('capabilityBadges', () => {
  it('emits badges only for declared capabilities', () => {
    const m = {
      modality: 'video', availability: 'both', max_duration_s: 10,
      supports: { reference_images: true, character_consistency: true, negative_prompt: false },
    } as unknown as ModelEntry
    const badges = capabilityBadges(m)
    expect(badges).toContain('video')
    expect(badges).toContain('open weights')
    expect(badges).toContain('references')
    expect(badges).toContain('consistency')
    expect(badges).toContain('≤10s')
    expect(badges).not.toContain('negative prompt')
  })
})

describe('fmtUsd', () => {
  it('formats small amounts with three decimals and unknown as a dash', () => {
    expect(fmtUsd(0.025)).toBe('$0.025')
    expect(fmtUsd(1.5)).toBe('$1.50')
    expect(fmtUsd(null)).toBe('—')
  })
})
