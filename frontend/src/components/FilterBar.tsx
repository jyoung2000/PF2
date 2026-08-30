import { useEffect, useState } from 'react'
import { api, listScrapers } from '../api'

export interface GalleryFilters {
  platform?: string
  model?: string
  media_type?: string
  technique?: string
  nsfw?: boolean
  favorite?: boolean
  date_from?: string
}

const DATE_CHOICES: { label: string; days: number | null }[] = [
  { label: 'Any time', days: null },
  { label: 'Last 24h', days: 1 },
  { label: 'Last 7 days', days: 7 },
  { label: 'Last 30 days', days: 30 },
]

function Select({
  value,
  onChange,
  options,
  allLabel,
  ariaLabel,
}: {
  value: string | undefined
  onChange: (v: string | undefined) => void
  options: { value: string; label: string }[]
  allLabel: string
  ariaLabel: string
}) {
  return (
    <select
      aria-label={ariaLabel}
      className="input !w-auto h-8 py-0 text-[12.5px] pr-7"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value || undefined)}
    >
      <option value="">{allLabel}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

function Toggle({
  active,
  onClick,
  children,
  ariaLabel,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
  ariaLabel: string
}) {
  return (
    <button
      aria-label={ariaLabel}
      aria-pressed={active}
      className={`btn h-8 py-0 text-[12.5px] ${active ? '!border-ember/70 text-ember bg-ember/10' : ''}`}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

export function FilterBar({
  filters,
  onChange,
  hidePlatform = false,
  hideModel = false,
}: {
  filters: GalleryFilters
  onChange: (f: GalleryFilters) => void
  hidePlatform?: boolean
  hideModel?: boolean
}) {
  const [platforms, setPlatforms] = useState<string[]>([])
  const [models, setModels] = useState<{ family: string; label: string }[]>([])
  const [techniques, setTechniques] = useState<string[]>([])

  useEffect(() => {
    listScrapers()
      .then((r) => setPlatforms(r.scrapers.map((s) => s.name)))
      .catch(() => undefined)
    api
      .get<{ models: { family: string; label: string }[] }>('/api/suggest')
      .then((r) => setModels(r.models))
      .catch(() => undefined)
    api
      .get<{ techniques: string[] }>('/api/techniques')
      .then((r) => setTechniques(r.techniques))
      .catch(() => setTechniques([]))
  }, [])

  const set = (patch: Partial<GalleryFilters>) => onChange({ ...filters, ...patch })
  const activeDate = DATE_CHOICES.find((d) =>
    d.days === null ? !filters.date_from : filters.date_from !== undefined && dateFromDays(d.days) === filters.date_from,
  )

  return (
    <div className="flex items-center gap-1.5 flex-wrap" role="group" aria-label="Filters">
      {!hidePlatform && (
        <Select
          ariaLabel="Platform filter"
          value={filters.platform}
          onChange={(v) => set({ platform: v })}
          allLabel="All platforms"
          options={platforms.map((p) => ({ value: p, label: p }))}
        />
      )}
      {!hideModel && (
        <Select
          ariaLabel="Model filter"
          value={filters.model}
          onChange={(v) => set({ model: v })}
          allLabel="All models"
          options={models.map((m) => ({ value: m.family, label: m.label }))}
        />
      )}
      <Select
        ariaLabel="Media type filter"
        value={filters.media_type}
        onChange={(v) => set({ media_type: v })}
        allLabel="Images + video"
        options={[
          { value: 'image', label: 'Images' },
          { value: 'video', label: 'Videos' },
        ]}
      />
      {techniques.length > 0 && (
        <Select
          ariaLabel="Technique filter"
          value={filters.technique}
          onChange={(v) => set({ technique: v })}
          allLabel="All techniques"
          options={techniques.map((t) => ({ value: t, label: t }))}
        />
      )}
      <Select
        ariaLabel="Date filter"
        value={activeDate?.days ? String(activeDate.days) : ''}
        onChange={(v) => set({ date_from: v ? dateFromDays(Number(v)) : undefined })}
        allLabel="Any time"
        options={DATE_CHOICES.filter((d) => d.days !== null).map((d) => ({
          value: String(d.days),
          label: d.label,
        }))}
      />
      <Toggle
        ariaLabel="Favorites only"
        active={!!filters.favorite}
        onClick={() => set({ favorite: !filters.favorite || undefined })}
      >
        ★ Favorites
      </Toggle>
      <Toggle
        ariaLabel="Show NSFW"
        active={!!filters.nsfw}
        onClick={() => set({ nsfw: !filters.nsfw || undefined })}
      >
        NSFW
      </Toggle>
    </div>
  )
}

function dateFromDays(days: number): string {
  const d = new Date(Date.now() - days * 86400_000)
  return d.toISOString().slice(0, 10)
}
