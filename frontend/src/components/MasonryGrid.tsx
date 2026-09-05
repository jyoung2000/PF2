// True left-to-right masonry: CSS grid + per-card row span from real media
// dimensions (D4). Buttery loading is PostCard's job (blur-up, hover video).
import { ReactNode, useEffect, useRef, useState } from 'react'

const ROW = 8 // px — grid-auto-rows quantum
const GAP = 12

function columnsFor(width: number): number {
  if (width < 520) return 2
  if (width < 860) return 3
  if (width < 1200) return 4
  if (width < 1500) return 5
  return 6
}

export interface MasonryItem {
  key: number | string
  width: number | null
  height: number | null
  render: (colWidth: number) => ReactNode
  extraHeight?: number
}

export function MasonryGrid({ items }: { items: MasonryItem[] }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [containerW, setContainerW] = useState(1200)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width
      if (w) setContainerW(w)
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  const cols = columnsFor(containerW)
  const colW = (containerW - GAP * (cols - 1)) / cols

  return (
    <div
      ref={ref}
      className="grid"
      style={{
        gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
        gridAutoRows: ROW,
        gap: GAP,
      }}
    >
      {items.map((it) => {
        const ratio = it.width && it.height ? it.height / it.width : 4 / 3
        const clamped = Math.min(Math.max(ratio, 0.5), 2.2)
        const h = colW * clamped + (it.extraHeight ?? 0)
        // a span of N rows is N*ROW + (N-1)*GAP tall, so divide by the row pitch
        const span = Math.max(8, Math.ceil((h + GAP) / (ROW + GAP)))
        return (
          <div key={it.key} style={{ gridRowEnd: `span ${span}` }}>
            {it.render(colW)}
          </div>
        )
      })}
    </div>
  )
}
