// Visual shot-type library (spec I): original diagrammatic examples drawn as
// SVG from the preset descriptors — figure scale, framing, angle, lens —
// with plain-language use cases, favourites and custom presets.
import { useMemo, useState } from 'react'
import { ShotType } from '../../lib/film'

export function ShotDiagram({ st, active = false, size = 120 }: { st: ShotType; active?: boolean; size?: number }) {
  const w = size
  const h = Math.round(size * 0.5625)
  const fig = st.figure
  const cam = st.camera
  const horizon = cam.angle === 'low' ? h * 0.72 : cam.angle === 'high' ? h * 0.32 : cam.angle === 'overhead' ? h * 0.15 : h * 0.55
  const figH = Math.min(h * 2.2, h * Math.max(0.12, fig) * 1.15)
  const figW = figH * 0.36
  const cx = w * (st.figures === 2 ? 0.38 : 0.5)
  const baseY = cam.angle === 'overhead' ? h * 0.85 : Math.min(h + figH * 0.35, horizon + figH * 0.45)
  const headR = figW * 0.34
  const tilt = st.tilt_deg ?? 0
  const tone = active ? '#FF6A3D' : '#9BA3AF'
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="rounded-el bg-ink block" aria-hidden>
      <defs>
        <clipPath id={`clip-${st.key}-${size}`}>
          <rect width={w} height={h} rx="4" />
        </clipPath>
      </defs>
      <g clipPath={`url(#clip-${st.key}-${size})`} transform={`rotate(${tilt} ${w / 2} ${h / 2})`}>
        <rect width={w} height={h} fill="#15171C" />
        <rect x="0" y={horizon} width={w} height={h} fill="#1C1F26" />
        <line x1="0" y1={horizon} x2={w} y2={horizon} stroke="#272B33" strokeWidth="1" />
        {cam.angle === 'overhead' ? (
          <g>
            <ellipse cx={w / 2} cy={h * 0.55} rx={figW * 0.9} ry={figW * 0.55} fill="none" stroke={tone} strokeWidth="1.5" />
            <circle cx={w / 2} cy={h * 0.5} r={headR * 1.2} fill={tone} opacity="0.9" />
          </g>
        ) : st.object ? (
          <g>
            <rect x={w * 0.36} y={h * 0.32} width={w * 0.28} height={h * 0.36} rx="3" fill="none" stroke={tone} strokeWidth="2" />
            <line x1={w * 0.36} y1={h * 0.5} x2={w * 0.64} y2={h * 0.5} stroke={tone} strokeWidth="1" opacity="0.6" />
          </g>
        ) : fig === 0 ? (
          <g>
            <path d={`M${w * 0.1} ${h * 0.95} L${w * 0.35} ${horizon} L${w * 0.65} ${horizon} L${w * 0.9} ${h * 0.95}`} fill="none" stroke={tone} strokeWidth="1.5" opacity="0.7" />
            <circle cx={w * 0.5} cy={h * 0.35} r="2.5" fill={tone} />
          </g>
        ) : (
          <g>
            {st.foreground && (
              <g opacity="0.55">
                <circle cx={w * 0.16} cy={h * 0.62} r={headR * 1.7} fill="#0E0F12" stroke={tone} strokeWidth="1.5" />
                <rect x={w * 0.02} y={h * 0.62 + headR * 1.4} width={headR * 3.6} height={h} fill="#0E0F12" stroke={tone} strokeWidth="1.5" />
              </g>
            )}
            <Figure cx={cx} baseY={baseY} figH={figH} figW={figW} headR={headR} tone={tone} />
            {st.figures === 2 && <Figure cx={w * 0.64} baseY={baseY} figH={figH * 0.96} figW={figW} headR={headR} tone={tone} mirrored />}
          </g>
        )}
        {cam.angle === 'low' && <path d={`M${w * 0.3} ${h} L${w * 0.5} ${h * 0.7} L${w * 0.7} ${h}`} fill="none" stroke="#272B33" strokeWidth="1" />}
      </g>
      <rect x="0.5" y="0.5" width={w - 1} height={h - 1} rx="4" fill="none" stroke={active ? '#FF6A3D' : '#272B33'} strokeWidth="1" />
      <text x={w - 4} y={h - 4} textAnchor="end" fontSize="8" fill="#6B7280" fontFamily="Inter, system-ui">
        {cam.lens_mm}mm
      </text>
    </svg>
  )
}

function Figure({ cx, baseY, figH, figW, headR, tone, mirrored = false }: { cx: number; baseY: number; figH: number; figW: number; headR: number; tone: string; mirrored?: boolean }) {
  const top = baseY - figH
  const shoulder = top + headR * 2.3
  return (
    <g transform={mirrored ? `translate(${cx * 2} 0) scale(-1 1)` : undefined}>
      <circle cx={cx} cy={top + headR} r={headR} fill={tone} />
      <path
        d={`M${cx - figW / 2} ${shoulder + figW * 0.2} Q${cx} ${shoulder - figW * 0.15} ${cx + figW / 2} ${shoulder + figW * 0.2} L${cx + figW * 0.42} ${baseY} L${cx - figW * 0.42} ${baseY} Z`}
        fill={tone}
        opacity="0.85"
      />
    </g>
  )
}

export function ShotTypeLibrary({
  types,
  favorites,
  value,
  onPick,
  onToggleFavorite,
  compact = false,
}: {
  types: ShotType[]
  favorites: string[]
  value?: string | null
  onPick: (st: ShotType) => void
  onToggleFavorite?: (key: string) => void
  compact?: boolean
}) {
  const [q, setQ] = useState('')
  const [onlyFav, setOnlyFav] = useState(false)
  const list = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return types
      .filter((t) => !onlyFav || favorites.includes(t.key))
      .filter((t) => !needle || `${t.label} ${t.abbr} ${t.what} ${t.use}`.toLowerCase().includes(needle))
      .sort((a, b) => Number(favorites.includes(b.key)) - Number(favorites.includes(a.key)))
  }, [types, favorites, q, onlyFav])
  return (
    <div className="space-y-2" data-testid="shot-type-library">
      <div className="flex items-center gap-2">
        <input className="input !h-8 text-[12.5px] flex-1" placeholder="Find a shot type…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search shot types" />
        <button className={`btn-ghost text-[12px] px-2 ${onlyFav ? 'text-ember' : ''}`} onClick={() => setOnlyFav((v) => !v)} aria-pressed={onlyFav}>
          ★ favourites
        </button>
      </div>
      <div className={`grid gap-2 ${compact ? 'grid-cols-3' : 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4'}`}>
        {list.map((st) => {
          const active = st.key === value
          return (
            <div key={st.key} className={`relative rounded-el border ${active ? 'border-ember' : 'border-line'} bg-panel p-2 flex flex-col gap-1.5 text-left`}>
              <button className="block w-full text-left" onClick={() => onPick(st)} title={st.use} data-shot-type={st.key}>
                <ShotDiagram st={st} active={active} size={compact ? 96 : 150} />
                <div className="mt-1.5 flex items-baseline gap-1.5">
                  <span className="font-display text-[12.5px] font-medium">{st.label}</span>
                  <span className="text-[10px] text-faint">{st.abbr}</span>
                </div>
                {!compact && <p className="text-[11px] text-mute leading-snug">{st.what}</p>}
                {!compact && <p className="text-[10.5px] text-faint leading-snug">Use for: {st.use}</p>}
              </button>
              {onToggleFavorite && (
                <button
                  className={`absolute top-1.5 right-1.5 text-[13px] ${favorites.includes(st.key) ? 'text-ember' : 'text-faint hover:text-fg'}`}
                  onClick={() => onToggleFavorite(st.key)}
                  aria-label={favorites.includes(st.key) ? 'Remove favourite' : 'Add favourite'}
                >
                  ★
                </button>
              )}
              {st.custom && <span className="absolute bottom-1.5 right-1.5 chip !text-[9px]">custom</span>}
            </div>
          )
        })}
        {!list.length && <p className="text-[12px] text-faint col-span-full py-4 text-center">No shot types match.</p>}
      </div>
    </div>
  )
}
