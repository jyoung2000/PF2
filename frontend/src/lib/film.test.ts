import { describe, expect, it } from 'vitest'
import { fmtTc, fmtUsd, inspirationToShotPatch } from './film'
import type { InspirationContext } from './inspiration'

const ctx: InspirationContext = {
  post_id: 7, platform: 'x', source_url: 'https://x.com/p/7', author: 'motionmuse', prompt: 'orbit shot', prompt_source: 'observed',
  model: { name: 'Kling', family: 'kling', version: null, source: 'explicit' }, techniques: ['orbit', 'volumetric-light'],
  camera: ['35mm', 'close-up', 'low angle'], lighting: ['neon', 'rim light'], composition: ['symmetry'],
  subject: 'a glass lighthouse at dawn', style: 'cinematic', prompt_structure: 'natural', references: [], inspiration_score: 77, captured_at: '2026-09-05T00:00:00Z',
}

describe('inspirationToShotPatch', () => {
  it('maps camera, lighting, style, subject and techniques into shot overrides with provenance', () => {
    const { overrides, summary } = inspirationToShotPatch(ctx)
    expect(overrides.shot_type).toBe('close_up')
    expect(overrides.camera).toEqual({ lens_mm: 35, angle: 'low' })
    expect(overrides.lighting).toEqual({ mood: 'neon, rim light' })
    expect(overrides.style).toEqual({ visual_style: 'cinematic, symmetry' })
    expect(overrides.subject).toBe('a glass lighthouse at dawn')
    expect(overrides.motion).toEqual({ character_motion: 'orbit, volumetric light' })
    expect(overrides.inspiration).toMatchObject({ post_id: 7, platform: 'x', author: 'motionmuse', source_url: 'https://x.com/p/7' })
    expect(summary.join(' ')).toContain('shot type close up')
  })
  it('never copies the source prompt text', () => {
    const { overrides } = inspirationToShotPatch(ctx)
    expect(JSON.stringify(overrides)).not.toContain('orbit shot')
  })
  it('handles an empty context without inventing values', () => {
    const { overrides, summary } = inspirationToShotPatch({ ...ctx, camera: [], lighting: [], composition: [], techniques: [], subject: null, style: null })
    expect(Object.keys(overrides)).toEqual(['inspiration'])
    expect(summary).toEqual([])
  })
})

describe('formatters', () => {
  it('formats timecodes with tenths', () => {
    expect(fmtTc(0)).toBe('00:00:00.0')
    expect(fmtTc(102.5)).toBe('00:01:42.5')
    expect(fmtTc(3725.04)).toBe('01:02:05.0')
    expect(fmtTc(null)).toBe('00:00:00.0')
  })
  it('formats money with sub-dollar precision', () => {
    expect(fmtUsd(0.092)).toBe('$0.092')
    expect(fmtUsd(12.5)).toBe('$12.50')
    expect(fmtUsd(null)).toBe('—')
  })
})
