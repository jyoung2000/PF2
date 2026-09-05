import { render } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { MasonryGrid } from './MasonryGrid'

// A span of N rows covers N*8px + (N-1)*12px of gap, so the row count must be
// derived from the row pitch (20px), not the row height alone — otherwise every
// card renders ~2.5× taller than its media and gets cropped.
describe('MasonryGrid', () => {
  beforeAll(() => {
    // jsdom has no ResizeObserver; the grid only uses it to track its width
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} })
  })
  it('sizes a card row span from the media aspect ratio and the row pitch', () => {
    const { container } = render(
      <MasonryGrid items={[{ key: 1, width: 1000, height: 1000, render: () => <div /> }]} />,
    )
    const item = container.querySelector('[style*="grid-row-end"]') as HTMLElement
    // default container width 1200 → 5 columns → colW = (1200 - 48) / 5 = 230.4
    // h = 230.4, span = ceil((230.4 + 12) / 20) = 13 → 13*8 + 12*12 = 248px ≈ h
    expect(item.style.gridRowEnd).toBe('span 13')
  })
})
