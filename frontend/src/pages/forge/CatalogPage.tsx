// Model intelligence browser (spec §2, §14): capability badges, offers with
// live prices and connection state, licensing honesty, side-by-side compare.
import { useState } from 'react'
import { EmptyState, SkeletonGrid } from '../../components/Primitives'
import { capabilityBadges, fmtUsd, forge, ModelEntry } from '../../lib/forge'
import { useFetch } from '../../lib/hooks'

const MODALITIES = ['all', 'image', 'video'] as const

function ModelCard({ m, comparing, onCompare }: { m: ModelEntry; comparing: boolean; onCompare: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={`card p-4 ${comparing ? 'border-ember' : ''}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="font-display font-medium text-[15px]">{m.display_name ?? m.family}</h2>
        {m.generatable && <span className="chip !text-[10.5px] text-emerald-300 border-emerald-400/40 bg-emerald-400/10">ready</span>}
        {m.latency_class && <span className="chip !text-[10.5px]">{m.latency_class}</span>}
        <span className="ml-auto flex gap-1.5">
          <button className="btn-ghost text-[12px] px-2 py-0.5" onClick={onCompare}>{comparing ? '✓ comparing' : 'compare'}</button>
          <button className="btn-ghost text-[12px] px-2 py-0.5" onClick={() => setOpen(!open)}>{open ? 'less' : 'more'}</button>
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {capabilityBadges(m).map((b) => <span key={b} className="chip !text-[11px]">{b}</span>)}
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {m.offers.map((o) => (
          <span key={o.provider} className={`chip !text-[11px] ${o.connected ? '!text-fg' : ''}`} title={o.provider_model_id ?? ''}>
            {o.provider} {fmtUsd(o.price_estimate)}{o.connected ? ' ●' : ''}
          </span>
        ))}
        {m.offers.length === 0 && <span className="text-[11.5px] text-faint">no provider offer in the pricing catalog</span>}
      </div>
      {m.observed && (
        <p className="mt-1.5 text-[11.5px] text-faint tabular-nums">{m.observed.post_count} posts in your library{m.knowledge_file ? ' · knowledge file learned' : ''}</p>
      )}
      {open && (
        <div className="mt-3 space-y-2 text-[12.5px] border-t border-line pt-3">
          {m.strengths.length > 0 && <p><span className="text-emerald-300">Strengths:</span> {m.strengths.join(', ')}</p>}
          {m.weaknesses.length > 0 && <p><span className="text-amber-300">Weak spots:</span> {m.weaknesses.join(', ')}</p>}
          {m.prompt.notes && <p><span className="text-faint">Prompting:</span> {m.prompt.notes} <span className="chip !text-[10.5px] ml-1">{m.prompt.style}</span></p>}
          {m.aspect_ratios && <p><span className="text-faint">Aspect ratios:</span> {m.aspect_ratios.join(' · ')}</p>}
          {m.licensing && <p><span className="text-faint">License:</span> {m.licensing}</p>}
          {m.commercial_use && <p><span className="text-faint">Commercial use:</span> {m.commercial_use}</p>}
          {m.local_hardware && <p><span className="text-faint">Local:</span> {m.local_hardware}</p>}
          {m.fallback_families.length > 0 && <p><span className="text-faint">Fallbacks:</span> {m.fallback_families.join(', ')}</p>}
          <p className="text-[11px] text-faint">last verified {m.last_verified ?? '—'} · edit in DATA_DIR/models_catalog.json (your copy wins)</p>
        </div>
      )}
    </div>
  )
}

const COMPARE_ROWS: [string, (m: ModelEntry) => string][] = [
  ['Modality', (m) => m.modality],
  ['Cheapest offer', (m) => fmtUsd(Math.min(...m.offers.filter((o) => o.price_estimate != null).map((o) => o.price_estimate as number)) || null)],
  ['Connected', (m) => (m.generatable ? 'yes' : 'no')],
  ['Latency', (m) => m.latency_class ?? '—'],
  ['Max duration', (m) => (m.max_duration_s ? `${m.max_duration_s}s` : '—')],
  ['References', (m) => (m.supports.reference_images ? 'yes' : 'no')],
  ['Consistency', (m) => (m.supports.character_consistency ? 'yes' : 'no')],
  ['Negative prompt', (m) => (m.supports.negative_prompt ? 'yes' : 'no')],
  ['Open weights', (m) => (m.availability === 'both' ? 'yes' : 'no')],
  ['Prompt style', (m) => m.prompt.style],
]

export function CatalogPage() {
  const { data, loading } = useFetch(() => forge.models())
  const [modality, setModality] = useState<(typeof MODALITIES)[number]>('all')
  const [compare, setCompare] = useState<string[]>([])

  if (loading) return <SkeletonGrid count={6} />
  const models = (data?.models ?? []).filter((m) => modality === 'all' || m.modality === modality)
  const comparing = (data?.models ?? []).filter((m) => compare.includes(m.family))

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1.5">
        {MODALITIES.map((mo) => (
          <button key={mo} className={`chip ${modality === mo ? '!border-ember text-fg' : ''}`} onClick={() => setModality(mo)}>
            {mo}
          </button>
        ))}
        <span className="ml-auto text-[12px] text-faint">
          {models.length} families · metadata is seeded intelligence, editable per install
        </span>
      </div>
      {comparing.length >= 2 && (
        <div className="card p-4 overflow-x-auto fade-in">
          <table className="w-full text-[12.5px] min-w-[560px]">
            <thead>
              <tr className="text-left text-faint">
                <th className="py-1 pr-4 font-medium"> </th>
                {comparing.map((m) => <th key={m.family} className="py-1 pr-4 font-display text-fg">{m.display_name}</th>)}
              </tr>
            </thead>
            <tbody>
              {COMPARE_ROWS.map(([label, get]) => (
                <tr key={label} className="border-t border-line">
                  <td className="py-1 pr-4 text-faint">{label}</td>
                  {comparing.map((m) => <td key={m.family} className="py-1 pr-4">{get(m)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {models.length === 0 ? (
        <EmptyState title="Nothing matches" hint="Switch the modality filter." icon="◈" />
      ) : (
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {models.map((m) => (
            <ModelCard
              key={m.family}
              m={m}
              comparing={compare.includes(m.family)}
              onCompare={() => setCompare((c) => (c.includes(m.family) ? c.filter((x) => x !== m.family) : [...c, m.family].slice(-3)))}
            />
          ))}
        </div>
      )}
    </div>
  )
}
