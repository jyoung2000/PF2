// Shared building blocks for the Settings page sections.
import { ReactNode, useEffect, useState } from 'react'
import { SettingsMap } from '../lib/settings'

export function Section({
  title,
  hint,
  children,
  id,
}: {
  title: string
  hint?: string
  children: ReactNode
  id?: string
}) {
  return (
    <section id={id} className="card p-4 sm:p-5">
      <h2 className="font-display font-medium text-[15.5px]">{title}</h2>
      {hint && <p className="text-[12.5px] text-faint mt-0.5 max-w-measure">{hint}</p>}
      <div className="mt-3.5 space-y-3">{children}</div>
    </section>
  )
}

export function Field({
  label,
  children,
  hint,
  htmlFor,
}: {
  label: string
  children: ReactNode
  hint?: ReactNode
  htmlFor?: string
}) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint && <div className="text-[12px] text-faint mt-1">{hint}</div>}
    </div>
  )
}

/** Text input bound to a settings key; saves on blur/Enter when changed. */
export function TextSetting({
  settings,
  k,
  save,
  placeholder,
  secret = false,
  type = 'text',
}: {
  settings: SettingsMap
  k: string
  save: (v: SettingsMap) => Promise<boolean>
  placeholder?: string
  secret?: boolean
  type?: string
}) {
  const stored = String(settings[k] ?? '')
  const [value, setValue] = useState(stored)
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    if (!dirty) setValue(stored)
  }, [stored, dirty])

  const commit = async () => {
    if (!dirty) return
    const ok = await save({ [k]: value })
    if (ok) setDirty(false)
  }

  return (
    <input
      id={`setting-${k}`}
      type={secret ? 'text' : type}
      autoComplete="off"
      spellCheck={false}
      className="input font-mono"
      placeholder={secret && stored ? `${stored} (stored — paste to replace)` : placeholder}
      value={secret && !dirty ? '' : value}
      onChange={(e) => {
        setValue(e.target.value)
        setDirty(true)
      }}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && commit()}
    />
  )
}

export function ToggleSetting({
  settings,
  k,
  save,
  label,
}: {
  settings: SettingsMap
  k: string
  save: (v: SettingsMap) => Promise<boolean>
  label: string
}) {
  const on = Boolean(settings[k])
  return (
    <button
      role="switch"
      aria-checked={on}
      className="flex items-center gap-2.5 text-[13px] text-fg"
      onClick={() => save({ [k]: !on })}
    >
      <span
        className={`relative w-9 h-5 rounded-full transition-colors duration-fast ${on ? 'bg-ember' : 'bg-well border border-line'}`}
      >
        <span
          className={`absolute top-0.5 w-4 h-4 rounded-full bg-fg transition-transform duration-fast ${on ? 'translate-x-4' : 'translate-x-0.5'}`}
        />
      </span>
      {label}
    </button>
  )
}

export function NumberSetting({
  settings,
  k,
  save,
  min,
  max,
  suffix,
}: {
  settings: SettingsMap
  k: string
  save: (v: SettingsMap) => Promise<boolean>
  min?: number
  max?: number
  suffix?: string
}) {
  const stored = Number(settings[k] ?? 0)
  const [value, setValue] = useState(stored)
  useEffect(() => setValue(stored), [stored])
  return (
    <span className="inline-flex items-center gap-1.5">
      <input
        id={`setting-${k}`}
        type="number"
        min={min}
        max={max}
        className="input !w-24 tabular-nums"
        value={value}
        onChange={(e) => setValue(Number(e.target.value))}
        onBlur={() => value !== stored && save({ [k]: value })}
        onKeyDown={(e) => e.key === 'Enter' && value !== stored && save({ [k]: value })}
      />
      {suffix && <span className="text-[12px] text-faint">{suffix}</span>}
    </span>
  )
}

export function ConnBadge({ status }: { status: 'connected' | 'error' | 'not_configured' | string }) {
  const map: Record<string, { text: string; cls: string }> = {
    connected: { text: 'Connected ✓', cls: 'text-emerald-300 border-emerald-400/40 bg-emerald-400/10' },
    error: { text: 'Error', cls: 'text-red-300 border-red-400/40 bg-red-400/10' },
    not_configured: { text: 'Not configured', cls: 'text-mute border-line bg-well' },
    offline: { text: 'Offline', cls: 'text-amber-300 border-amber-400/40 bg-amber-400/10' },
  }
  const m = map[status] ?? map.not_configured
  return <span className={`inline-flex px-2 py-0.5 rounded-chip border text-[11.5px] font-medium ${m.cls}`}>{m.text}</span>
}
