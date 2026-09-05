// Interactive lighting panel (spec K): drag key / fill / rim around a
// subject, sliders for intensities, colour temperature, contrast, ambient,
// practicals, plus the eight presets. AI proposals land here as values the
// user can override visually.
import { useRef } from 'react'
import { LightingPreset } from '../../lib/film'

export interface LightingValue {
  key_intensity?: number
  fill_intensity?: number
  rim_intensity?: number
  key_angle?: number
  fill_angle?: number
  rim_angle?: number
  direction?: string
  color_temp_k?: number
  contrast?: string
  ambient?: number
  practicals?: string
  mood?: string
}

const LIGHTS: { key: 'key' | 'fill' | 'rim'; label: string; color: string; defaultAngle: number }[] = [
  { key: 'key', label: 'Key', color: '#FF6A3D', defaultAngle: -45 },
  { key: 'fill', label: 'Fill', color: '#9BA3AF', defaultAngle: 45 },
  { key: 'rim', label: 'Rim', color: '#7DD3FC', defaultAngle: 160 },
]

function kelvinColor(k: number) {
  if (k <= 3200) return '#FFB46B'
  if (k <= 4300) return '#FFD9A8'
  if (k <= 5600) return '#FFF7EA'
  if (k <= 6500) return '#E8F1FF'
  return '#BFD8FF'
}

export function LightingPanel({ value, presets, onChange, source }: { value: LightingValue; presets: LightingPreset[]; onChange: (patch: LightingValue) => void; source?: string | null }) {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const cx = 110
  const cy = 90
  const R = 70
  const angleOf = (k: 'key' | 'fill' | 'rim') => (value[`${k}_angle`] ?? LIGHTS.find((l) => l.key === k)!.defaultAngle)
  const startDrag = (k: 'key' | 'fill' | 'rim') => (e: React.PointerEvent) => {
    const svg = svgRef.current
    if (!svg) return
    e.preventDefault()
    const move = (ev: PointerEvent) => {
      const rect = svg.getBoundingClientRect()
      const x = ((ev.clientX - rect.left) / rect.width) * 220 - cx
      const y = ((ev.clientY - rect.top) / rect.height) * 180 - cy
      const deg = Math.round((Math.atan2(y, x) * 180) / Math.PI / 5) * 5
      onChange({ [`${k}_angle`]: deg, direction: describeDirection(k, deg) } as LightingValue)
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  const temp = value.color_temp_k ?? 4300
  return (
    <div className="space-y-3" data-testid="lighting-panel">
      <div className="flex flex-wrap gap-1">
        {presets.map((p) => (
          <button
            key={p.key}
            className={`chip ${value.mood === p.mood ? '!border-ember text-fg' : ''}`}
            title={`${p.direction}, ${p.color_temp_k}K, ${p.contrast} contrast`}
            onClick={() =>
              onChange({ key_intensity: p.key_intensity, fill_intensity: p.fill_intensity, rim_intensity: p.rim_intensity, direction: p.direction, color_temp_k: p.color_temp_k, contrast: p.contrast, ambient: p.ambient, practicals: p.practicals, mood: p.mood })
            }
          >
            {p.label}
          </button>
        ))}
        {source && <span className="text-[10px] text-faint self-center">· {source.replace('preset:', 'preset ')}</span>}
      </div>
      <div className="grid sm:grid-cols-[220px_1fr] gap-3 items-start">
        <svg ref={svgRef} viewBox="0 0 220 180" className="w-full max-w-[220px] rounded-el bg-ink border border-line touch-none select-none" aria-label="Light positions (drag)">
          <rect width="220" height="180" fill="#0E0F12" />
          <circle cx={cx} cy={cy} r={R} fill="none" stroke="#272B33" strokeDasharray="3 3" />
          <circle cx={cx} cy={cy} r="16" fill={kelvinColor(temp)} opacity={0.25 + (value.ambient ?? 0.3) * 0.5} />
          <circle cx={cx} cy={cy} r="10" fill="#9BA3AF" />
          <rect x={cx - 8} y={cy + 10} width="16" height="22" rx="3" fill="#9BA3AF" opacity="0.8" />
          <text x={cx} y={cy + 48} textAnchor="middle" fontSize="9" fill="#6B7280">subject</text>
          <text x={cx} y="14" textAnchor="middle" fontSize="9" fill="#6B7280">camera ↓ at bottom</text>
          {LIGHTS.map((l) => {
            const a = (angleOf(l.key) * Math.PI) / 180
            const inten = value[`${l.key}_intensity`] ?? 0.5
            const x = cx + Math.cos(a) * R
            const y = cy + Math.sin(a) * R
            return (
              <g key={l.key} onPointerDown={startDrag(l.key)} className="cursor-grab" data-light={l.key}>
                <line x1={x} y1={y} x2={cx} y2={cy} stroke={l.color} strokeOpacity={0.15 + inten * 0.6} strokeWidth={1 + inten * 4} />
                <circle cx={x} cy={y} r={7 + inten * 6} fill={l.color} opacity={0.35 + inten * 0.6} />
                <text x={x} y={y - 12} textAnchor="middle" fontSize="9" fill={l.color}>{l.label}</text>
              </g>
            )
          })}
          <polygon points={`${cx - 8},172 ${cx + 8},172 ${cx},160`} fill="#FF6A3D" />
        </svg>
        <div className="space-y-2">
          {LIGHTS.map((l) => (
            <label key={l.key} className="grid grid-cols-[42px_1fr_36px] items-center gap-2 text-[12px]">
              <span style={{ color: l.color }}>{l.label}</span>
              <input type="range" min="0" max="1" step="0.05" value={value[`${l.key}_intensity`] ?? 0.5} onChange={(e) => onChange({ [`${l.key}_intensity`]: Number(e.target.value) } as LightingValue)} aria-label={`${l.label} intensity`} />
              <span className="text-faint tabular-nums text-right">{Math.round((value[`${l.key}_intensity`] ?? 0.5) * 100)}%</span>
            </label>
          ))}
          <label className="grid grid-cols-[42px_1fr_36px] items-center gap-2 text-[12px]">
            <span className="text-mute">Ambient</span>
            <input type="range" min="0" max="1" step="0.05" value={value.ambient ?? 0.3} onChange={(e) => onChange({ ambient: Number(e.target.value) })} aria-label="Ambient level" />
            <span className="text-faint tabular-nums text-right">{Math.round((value.ambient ?? 0.3) * 100)}%</span>
          </label>
          <label className="grid grid-cols-[42px_1fr_44px] items-center gap-2 text-[12px]">
            <span className="text-mute">Temp</span>
            <input type="range" min="2000" max="10000" step="100" value={temp} onChange={(e) => onChange({ color_temp_k: Number(e.target.value) })} aria-label="Colour temperature" style={{ accentColor: kelvinColor(temp) }} />
            <span className="text-faint tabular-nums text-right">{temp}K</span>
          </label>
          <div className="flex items-center gap-1 text-[12px]">
            <span className="text-mute w-[42px]">Contrast</span>
            {['very low', 'low', 'medium', 'high', 'very high'].map((c) => (
              <button key={c} className={`chip ${value.contrast === c ? '!border-ember text-fg' : ''}`} onClick={() => onChange({ contrast: c })}>{c}</button>
            ))}
          </div>
          <label className="block text-[12px] text-mute">
            Practicals
            <input className="input mt-1" value={value.practicals ?? ''} placeholder="neon signs, a desk lamp, candles…" onChange={(e) => onChange({ practicals: e.target.value })} />
          </label>
        </div>
      </div>
    </div>
  )
}

function describeDirection(k: string, deg: number) {
  const d = ((deg % 360) + 360) % 360
  const dir = d < 22 || d >= 338 ? 'right' : d < 67 ? 'front-right' : d < 112 ? 'front' : d < 157 ? 'front-left' : d < 202 ? 'left' : d < 247 ? 'back-left' : d < 292 ? 'back' : 'back-right'
  return `${k} from ${dir}`
}
