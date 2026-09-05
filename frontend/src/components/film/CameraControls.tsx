// Visual camera controls (spec J): framing selector, angle diagram, lens
// strip with field-of-view preview, motion presets with mini diagrams,
// focus + depth of field. Presets first; expert fields behind "more".
import { useState } from 'react'
import { Presets } from '../../lib/film'

export interface CameraValue {
  shot_size?: string
  angle?: string
  lens_mm?: number
  height_m?: number
  movement?: string
  movement_speed?: string
  depth_of_field?: string
  focus_target?: string
  composition?: string
}

const SIZE_LABEL: Record<string, string> = {
  extreme_wide: 'EWS', wide: 'WS', full: 'FS', medium_wide: 'MWS', medium: 'MS', medium_close: 'MCU', close_up: 'CU', extreme_close_up: 'ECU',
}
const ANGLE_LABEL: Record<string, string> = { eye_level: 'Eye level', low: 'Low', high: 'High', overhead: 'Overhead', dutch: 'Dutch' }

function FramingPreview({ size }: { size: string }) {
  const order = ['extreme_wide', 'wide', 'full', 'medium_wide', 'medium', 'medium_close', 'close_up', 'extreme_close_up']
  const i = Math.max(0, order.indexOf(size))
  const scale = 0.12 + i * 0.18
  const figH = 40 * scale * 2.4
  return (
    <svg width="96" height="54" viewBox="0 0 96 54" className="rounded-el bg-ink" aria-hidden>
      <rect width="96" height="54" fill="#15171C" />
      <rect y="30" width="96" height="24" fill="#1C1F26" />
      <circle cx="48" cy={Math.max(6, 44 - figH)} r={4 * Math.max(0.6, scale * 1.4)} fill="#FF6A3D" />
      <path d={`M${48 - figH * 0.22} ${Math.max(6, 44 - figH) + 6} L${48 + figH * 0.22} ${Math.max(6, 44 - figH) + 6} L${48 + figH * 0.26} 60 L${48 - figH * 0.26} 60Z`} fill="#FF6A3D" opacity="0.8" />
    </svg>
  )
}

function AngleDiagram({ angle }: { angle: string }) {
  const y = angle === 'low' ? 44 : angle === 'high' ? 10 : angle === 'overhead' ? 4 : 27
  const x = angle === 'overhead' ? 48 : 14
  return (
    <svg width="96" height="54" viewBox="0 0 96 54" className="rounded-el bg-ink" aria-hidden>
      <rect width="96" height="54" fill="#15171C" />
      <line x1="0" y1="48" x2="96" y2="48" stroke="#272B33" />
      <circle cx="60" cy="18" r="5" fill="#9BA3AF" />
      <rect x="55" y="24" width="10" height="24" rx="2" fill="#9BA3AF" opacity="0.8" />
      <g transform={angle === 'dutch' ? `rotate(-18 ${x} ${y})` : undefined}>
        <rect x={x - 6} y={y - 4} width="12" height="8" rx="1.5" fill="#FF6A3D" />
        <line x1={x + 6} y1={y} x2="52" y2="26" stroke="#FF6A3D" strokeDasharray="2 2" />
      </g>
    </svg>
  )
}

function MotionDiagram({ move }: { move: string }) {
  const paths: Record<string, string> = {
    static: '', push_in: 'M20 27 L44 27', pull_out: 'M44 27 L20 27', pan: 'M18 27 Q48 10 78 27', tilt: 'M48 44 Q30 27 48 10',
    tracking: 'M10 34 L86 34', orbit: 'M48 27 m-22 0 a22 12 0 1 0 44 0', crane: 'M20 44 Q48 30 76 8', handheld: 'M12 27 q8 -8 16 0 t16 0 t16 0 t16 0',
    whip_pan: 'M8 27 L88 27',
  }
  return (
    <svg width="96" height="54" viewBox="0 0 96 54" className="rounded-el bg-ink" aria-hidden>
      <rect width="96" height="54" fill="#15171C" />
      <circle cx="48" cy="27" r="5" fill="#9BA3AF" />
      {paths[move] ? <path d={paths[move]} fill="none" stroke="#FF6A3D" strokeWidth={move === 'whip_pan' ? 3 : 1.5} markerEnd="url(#arrow)" /> : <rect x="40" y="19" width="16" height="16" rx="2" fill="none" stroke="#FF6A3D" />}
      <defs>
        <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0 0 L6 3 L0 6Z" fill="#FF6A3D" />
        </marker>
      </defs>
    </svg>
  )
}

export function CameraControls({ value, presets, onChange, sources = {} }: { value: CameraValue; presets: Presets; onChange: (patch: CameraValue) => void; sources?: Record<string, string> }) {
  const [more, setMore] = useState(false)
  const src = (k: string) => sources[`camera.${k}`]
  const Src = ({ k }: { k: string }) => (src(k) ? <span className="text-[10px] text-faint ml-1">· {src(k).replace('preset:', 'preset ')}</span> : null)
  return (
    <div className="space-y-3" data-testid="camera-controls">
      <div>
        <div className="label">Framing <Src k="shot_size" /></div>
        <div className="flex items-center gap-2 overflow-x-auto scrollbar-none pb-1">
          <FramingPreview size={value.shot_size ?? 'medium'} />
          <div className="flex gap-1 flex-wrap">
            {presets.shot_sizes.map((s) => (
              <button key={s} className={`chip ${value.shot_size === s ? '!border-ember text-fg' : ''}`} onClick={() => onChange({ shot_size: s })} title={s.replace(/_/g, ' ')}>
                {SIZE_LABEL[s] ?? s}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div>
        <div className="label">Angle <Src k="angle" /></div>
        <div className="flex items-center gap-2">
          <AngleDiagram angle={value.angle ?? 'eye_level'} />
          <div className="flex gap-1 flex-wrap">
            {presets.angles.map((a) => (
              <button key={a} className={`chip ${value.angle === a ? '!border-ember text-fg' : ''}`} onClick={() => onChange({ angle: a })}>
                {ANGLE_LABEL[a] ?? a}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div>
        <div className="label">Lens <Src k="lens_mm" /></div>
        <div className="flex gap-1 overflow-x-auto scrollbar-none pb-1" role="radiogroup" aria-label="Lens">
          {presets.lenses.map((l) => {
            const active = value.lens_mm === l.mm
            return (
              <button key={l.key} role="radio" aria-checked={active} className={`shrink-0 w-[76px] rounded-el border p-1.5 text-left ${active ? 'border-ember' : 'border-line'} bg-panel`} onClick={() => onChange({ lens_mm: l.mm })} title={l.depth}>
                <svg width="60" height="26" viewBox="0 0 60 26" aria-hidden>
                  <path d={`M30 24 L${30 - (l.fov_deg / 104) * 28} 2 L${30 + (l.fov_deg / 104) * 28} 2 Z`} fill={active ? '#FF6A3D' : '#272B33'} opacity="0.7" />
                </svg>
                <div className="text-[11px] font-medium">{l.label}</div>
                <div className="text-[10px] text-faint">{l.mm}mm · {l.fov_deg}°</div>
              </button>
            )
          })}
        </div>
      </div>
      <div>
        <div className="label">Camera motion <Src k="movement" /></div>
        <div className="grid grid-cols-5 gap-1">
          {presets.camera_moves.map((m) => (
            <button key={m.key} className={`rounded-el border p-1 ${value.movement === m.key ? 'border-ember' : 'border-line'} bg-panel`} onClick={() => onChange({ movement: m.key })} title={m.what}>
              <MotionDiagram move={m.key} />
              <div className="text-[10.5px] mt-0.5">{m.label}</div>
            </button>
          ))}
        </div>
        {value.movement && value.movement !== 'static' && (
          <div className="flex items-center gap-2 mt-1.5">
            <span className="text-[11px] text-faint">Speed</span>
            {presets.move_speeds.map((s) => (
              <button key={s} className={`chip ${value.movement_speed === s ? '!border-ember text-fg' : ''}`} onClick={() => onChange({ movement_speed: s })}>
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
      <button className="btn-ghost text-[12px] px-0" onClick={() => setMore((v) => !v)} aria-expanded={more}>
        {more ? '▾ fewer camera controls' : '▸ focus, height, composition'}
      </button>
      {more && (
        <div className="grid sm:grid-cols-2 gap-2 fade-in">
          <label className="text-[12px] text-mute">
            Camera height (m)
            <input className="input mt-1" type="number" step="0.1" min="0" max="50" value={value.height_m ?? ''} onChange={(e) => onChange({ height_m: e.target.value === '' ? undefined : Number(e.target.value) })} />
          </label>
          <label className="text-[12px] text-mute">
            Depth of field
            <select className="input mt-1" value={value.depth_of_field ?? ''} onChange={(e) => onChange({ depth_of_field: e.target.value || undefined })}>
              <option value="">—</option>
              {['shallow', 'medium', 'deep', 'rack focus'].map((o) => <option key={o}>{o}</option>)}
            </select>
          </label>
          <label className="text-[12px] text-mute sm:col-span-2">
            Focus target
            <input className="input mt-1" value={value.focus_target ?? ''} placeholder="e.g. Jack's eyes → the crate" onChange={(e) => onChange({ focus_target: e.target.value || undefined })} />
          </label>
          <label className="text-[12px] text-mute sm:col-span-2">
            Composition
            <input className="input mt-1" value={value.composition ?? ''} placeholder="rule of thirds, leading lines, symmetry…" onChange={(e) => onChange({ composition: e.target.value || undefined })} />
          </label>
        </div>
      )}
    </div>
  )
}
