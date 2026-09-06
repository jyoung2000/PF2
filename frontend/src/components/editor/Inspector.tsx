// Contextual inspector (Editor E4): shows the selected clip's timing,
// retime, audio, fades and transition; a marker's fields; or sequence info.
// Every change goes through the sequence API (one undo step each).
import { useEffect, useState } from 'react'
import { ClipEffects, Sequence, SeqClip, SeqMarker } from '../../lib/editor'

function Num({ label, value, onCommit, step = 0.1, min, max, suffix = 's', testid }: {
  label: string
  value: number
  onCommit: (v: number) => void
  step?: number
  min?: number
  max?: number
  suffix?: string
  testid?: string
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])
  const commit = () => {
    const v = Number(draft)
    if (!Number.isNaN(v) && v !== value) onCommit(v)
  }
  return (
    <label className="flex items-center gap-1.5 text-[12px]">
      <span className="text-mute w-20 shrink-0">{label}</span>
      <input className="input !h-7 !w-20 tabular-nums" type="number" step={step} min={min} max={max} value={draft}
             onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === 'Enter' && commit()}
             aria-label={label} data-testid={testid} />
      <span className="text-faint">{suffix}</span>
    </label>
  )
}

const EFFECT_FIELDS: { key: keyof ClipEffects; label: string; step: number; min: number; max: number; def: number }[] = [
  { key: 'opacity', label: 'Opacity', step: 0.05, min: 0, max: 1, def: 1 },
  { key: 'scale', label: 'Scale', step: 0.05, min: 0.05, max: 4, def: 1 },
  { key: 'x', label: 'Position X', step: 0.05, min: -1, max: 1, def: 0 },
  { key: 'y', label: 'Position Y', step: 0.05, min: -1, max: 1, def: 0 },
  { key: 'rotation', label: 'Rotation °', step: 1, min: -180, max: 180, def: 0 },
  { key: 'blur', label: 'Blur', step: 0.5, min: 0, max: 50, def: 0 },
  { key: 'brightness', label: 'Brightness', step: 0.05, min: -1, max: 1, def: 0 },
  { key: 'contrast', label: 'Contrast', step: 0.05, min: 0, max: 3, def: 1 },
  { key: 'saturation', label: 'Saturation', step: 0.05, min: 0, max: 3, def: 1 },
]

function EffectsSection({ effects, onChange }: { effects: ClipEffects; onChange: (e: ClipEffects) => void }) {
  const active = Object.keys(effects).length > 0
  const crop = effects.crop ?? {}
  return (
    <details className="border-t border-line/60 pt-1" open={active} data-testid="effects-section">
      <summary className="cursor-pointer text-[12px] text-mute select-none">Effects{active ? ' ·' : ''} {active && <span className="text-ember">{Object.keys(effects).length}</span>}</summary>
      <div className="space-y-1.5 mt-1.5">
        {EFFECT_FIELDS.map((f) => (
          <Num key={f.key} label={f.label} value={Number(effects[f.key] ?? f.def)} step={f.step} min={f.min} max={f.max} suffix=""
               onCommit={(v) => onChange({ ...effects, [f.key]: v })} testid={`fx-${f.key}`} />
        ))}
        <div className="text-[11px] text-mute">Crop (fraction per edge)</div>
        <div className="grid grid-cols-2 gap-1">
          {(['l', 't', 'r', 'b'] as const).map((k) => (
            <Num key={k} label={{ l: 'Left', t: 'Top', r: 'Right', b: 'Bottom' }[k]} value={Number(crop[k] ?? 0)} step={0.02} min={0} max={0.45} suffix=""
                 onCommit={(v) => onChange({ ...effects, crop: { ...crop, [k]: v } })} />
          ))}
        </div>
        {active && <button className="btn-ghost text-[11.5px]" onClick={() => onChange({})} data-testid="fx-reset">Reset all effects</button>}
      </div>
    </details>
  )
}

export function Inspector({ seq, clip, marker, onPatchClip, onPatchMarker, onDeleteMarker, onOpenShot, onSetTake }: {
  seq: Sequence
  clip: SeqClip | null
  marker: SeqMarker | null
  onPatchClip: (id: number, body: Record<string, unknown>, label?: string) => void
  onPatchMarker: (id: number, body: Record<string, unknown>) => void
  onDeleteMarker: (id: number) => void
  onOpenShot: (shotId: number) => void
  onSetTake: (clip: SeqClip) => void
}) {
  if (marker) {
    return (
      <div className="space-y-2 text-[12.5px]" data-testid="inspector-marker">
        <h4 className="font-display text-[13px]">Marker</h4>
        <Num label="Time" value={marker.t_s} onCommit={(v) => onPatchMarker(marker.id, { t_s: v })} />
        <label className="flex items-center gap-1.5 text-[12px]"><span className="text-mute w-20">Label</span>
          <input className="input !h-7 flex-1" defaultValue={marker.label} onBlur={(e) => e.target.value !== marker.label && onPatchMarker(marker.id, { label: e.target.value })} /></label>
        <label className="flex items-center gap-1.5 text-[12px]"><span className="text-mute w-20">Colour</span>
          <select className="input !h-7 !w-24" value={marker.color} onChange={(e) => onPatchMarker(marker.id, { color: e.target.value })}>
            {['amber', 'red', 'green', 'blue', 'purple'].map((c) => <option key={c}>{c}</option>)}
          </select></label>
        <button className="btn-ghost text-red-300 text-[12px]" onClick={() => onDeleteMarker(marker.id)}>Delete marker</button>
      </div>
    )
  }
  if (!clip) {
    return (
      <div className="text-[12px] text-faint space-y-1.5" data-testid="inspector-empty">
        <h4 className="font-display text-[13px] text-fg">Sequence</h4>
        <p>{seq.tracks.length} tracks · runtime {seq.runtime_tc} · {seq.fps} fps{seq.aspect_ratio ? ` · ${seq.aspect_ratio}` : ''}</p>
        <p>Select a clip to edit its timing, speed, audio and transition. Drag clips to move, edges to trim; S splits at the playhead; ? lists every shortcut.</p>
      </div>
    )
  }
  const track = seq.tracks.find((t) => t.id === clip.track_id)
  const isCaption = clip.source_kind === 'caption'
  const isAudio = track?.kind === 'audio'
  return (
    <div className="space-y-2 text-[12.5px]" data-testid="inspector-clip">
      <div className="flex items-center gap-2">
        <h4 className="font-display text-[13px] truncate flex-1">{clip.label ?? `Clip #${clip.id}`}</h4>
        <span className="chip !text-[10px]">{clip.source_kind}</span>
      </div>
      {clip.missing_media && !isCaption && <p className="text-amber-300 text-[11.5px]">No media — <button className="underline" onClick={() => onSetTake(clip)}>pick a take</button>{clip.shot_id ? <> or <button className="underline" onClick={() => onOpenShot(clip.shot_id!)}>open the shot</button></> : null}.</p>}
      <Num label="Start" value={clip.start_s} onCommit={(v) => onPatchClip(clip.id, { start_s: v }, 'move clip')} testid="insp-start" />
      <Num label="Duration" value={clip.duration_s} onCommit={(v) => onPatchClip(clip.id, { duration_s: v }, 'trim clip')} min={0.05} testid="insp-duration" />
      {!isCaption && <Num label="Trim in" value={clip.trim_start_s} onCommit={(v) => onPatchClip(clip.id, { trim_start_s: v }, 'trim clip')} min={0} />}
      {!isCaption && <Num label="Speed" value={clip.speed} onCommit={(v) => onPatchClip(clip.id, { speed: v }, 'retime clip')} step={0.05} min={0.1} max={10} suffix="×" testid="insp-speed" />}
      {!isCaption && <Num label="Fade in" value={clip.fade_in_s} onCommit={(v) => onPatchClip(clip.id, { fade_in_s: v }, 'fade')} min={0} />}
      {!isCaption && <Num label="Fade out" value={clip.fade_out_s} onCommit={(v) => onPatchClip(clip.id, { fade_out_s: v }, 'fade')} min={0} />}
      {!isCaption && <Num label="Gain" value={clip.gain_db} onCommit={(v) => onPatchClip(clip.id, { gain_db: v }, 'gain')} step={1} min={-40} max={12} suffix="dB" />}
      {!isCaption && (
        <label className="flex items-center gap-1.5 text-[12px] text-mute"><input type="checkbox" checked={clip.muted} onChange={(e) => onPatchClip(clip.id, { muted: e.target.checked }, e.target.checked ? 'mute clip' : 'unmute clip')} data-testid="insp-mute" />{isAudio ? 'mute clip' : 'mute clip audio'}</label>
      )}
      {isCaption && (
        <label className="block text-[12px]"><span className="text-mute">Text</span>
          <textarea className="input mt-1 min-h-[60px]" defaultValue={String(clip.data?.text ?? '')}
                    onBlur={(e) => e.target.value !== String(clip.data?.text ?? '') && onPatchClip(clip.id, { data: { ...clip.data, text: e.target.value } }, 'edit caption')} data-testid="insp-caption-text" /></label>
      )}
      {!isAudio && !isCaption && (
        <div className="flex items-center gap-1.5 text-[12px]">
          <span className="text-mute w-20 shrink-0">Transition</span>
          <select className="input !h-7 !w-28" value={clip.transition_after?.kind ?? 'cut'}
                  onChange={(e) => onPatchClip(clip.id, { transition_after: e.target.value === 'cut' ? null : { kind: e.target.value, duration_s: clip.transition_after?.duration_s || 0.5 } }, 'transition')}
                  data-testid="insp-transition">
            {['cut', 'dissolve', 'wipe', 'fade_black', 'fade_white'].map((k) => <option key={k} value={k}>{k.replace('_', ' ')}</option>)}
          </select>
          {clip.transition_after && (
            <input className="input !h-7 !w-16 tabular-nums" type="number" step={0.1} min={0.1} max={3} value={clip.transition_after.duration_s}
                   onChange={(e) => onPatchClip(clip.id, { transition_after: { ...clip.transition_after, duration_s: Number(e.target.value) } }, 'transition')} aria-label="Transition duration" />
          )}
        </div>
      )}
      {!isCaption && !isAudio && (
        <EffectsSection effects={(clip.effects ?? {}) as ClipEffects}
                        onChange={(e) => onPatchClip(clip.id, { effects: e }, 'effects')} />
      )}
      <div className="text-[11px] text-faint pt-1 border-t border-line/60 space-y-0.5">
        {clip.source_duration_s != null && <div>source {clip.source_duration_s.toFixed(1)}s · showing {clip.trim_start_s.toFixed(1)}–{(clip.trim_start_s + clip.duration_s * clip.speed).toFixed(1)}s</div>}
        {clip.shot_id && <button className="underline" onClick={() => onOpenShot(clip.shot_id!)} data-testid="insp-open-shot">Open shot in storyboard →</button>}
        {clip.take_id && !clip.missing_media && <button className="underline block" onClick={() => onSetTake(clip)}>Swap take…</button>}
      </div>
    </div>
  )
}
