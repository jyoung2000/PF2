// Settings → AI providers (8.5): fal.ai / Replicate / WaveSpeed guided setup
// with test buttons, per-provider spend totals, and the editable pricing
// catalog.
import { useState } from 'react'
import { api, ApiError } from '../api'
import { formatMoney, timeAgo } from '../lib/format'
import { useFetch } from '../lib/hooks'
import { SettingsMap } from '../lib/settings'
import { toastError, toastSuccess } from '../lib/toast'
import { Spinner } from './Primitives'
import { ConnBadge, Section, TextSetting, ToggleSetting } from './SettingsKit'

interface ProviderInfo {
  name: string
  label: string
  key_setting: string
  key_url: string
  configured: boolean
  status: string
  last_tested: string | null
}

interface SpendInfo {
  totals: Record<string, number>
  total: number
  recent: { id: number; provider: string; status: string; cost_actual: number | null }[]
}

function ProviderRow({
  p,
  settings,
  save,
  spend,
  onTested,
}: {
  p: ProviderInfo
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
  spend: number
  onTested: () => void
}) {
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null)

  const runTest = async () => {
    setTesting(true)
    setResult(null)
    try {
      const r = await api.post<{ ok: boolean; detail: string }>(`/api/integrations/providers/${p.name}/test`)
      setResult({ ok: true, detail: r.detail })
    } catch (e) {
      let detail = e instanceof ApiError ? e.message : String(e)
      try {
        detail = JSON.parse(detail).message ?? detail
      } catch {
        /* plain message */
      }
      setResult({ ok: false, detail })
    } finally {
      setTesting(false)
      onTested()
    }
  }

  return (
    <div className="border border-line rounded-el p-3 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="font-display font-medium text-[14px]">{p.label}</h3>
        <ConnBadge status={p.status === 'configured' ? 'connected' : p.status} />
        {p.last_tested && <span className="text-[11px] text-faint">tested {timeAgo(p.last_tested)}</span>}
        <span className="chip ml-auto tabular-nums">spent {formatMoney(spend)}</span>
      </div>
      <div className="flex gap-2 items-start flex-wrap">
        <div className="flex-1 min-w-[220px]">
          <TextSetting settings={settings} k={p.key_setting} save={save} secret placeholder={`Paste ${p.label} API key`} />
          <p className="text-[11.5px] text-faint mt-1">
            Create one at{' '}
            <a className="underline underline-offset-2 hover:text-fg" href={p.key_url} target="_blank" rel="noreferrer">
              {p.key_url.replace('https://', '')}
            </a>
          </p>
        </div>
        <button className="btn" onClick={runTest} disabled={testing}>
          {testing ? <Spinner /> : 'Test'}
        </button>
      </div>
      {result && (
        <p
          className={`text-[12px] rounded-el px-2.5 py-1.5 border ${
            result.ok
              ? 'text-emerald-300 bg-emerald-400/10 border-emerald-400/30'
              : 'text-red-300 bg-red-400/10 border-red-400/30'
          }`}
        >
          {result.ok ? '✓ ' : ''}
          {result.detail}
        </p>
      )}
    </div>
  )
}

export function ProvidersCard({
  settings,
  save,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
}) {
  const { data: providers, reload } = useFetch(() =>
    api.get<{ providers: ProviderInfo[] }>('/api/integrations/providers'),
  )
  const { data: spend, reload: reloadSpend } = useFetch(() => api.get<SpendInfo>('/api/generation/spend'))
  const [showPricing, setShowPricing] = useState(false)
  const [pricingJson, setPricingJson] = useState('')

  const openPricing = async () => {
    try {
      const r = await api.get<{ families: Record<string, unknown> }>('/api/generation/pricing')
      setPricingJson(JSON.stringify(r.families, null, 2))
      setShowPricing(true)
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const savePricing = async () => {
    try {
      const parsed = JSON.parse(pricingJson)
      await api.put('/api/generation/pricing', parsed)
      toastSuccess('Pricing catalog saved')
      setShowPricing(false)
    } catch (e) {
      toastError(e instanceof SyntaxError ? 'JSON is invalid — fix the syntax first.' : (e as Error).message)
    }
  }

  return (
    <Section
      title="AI generation providers"
      hint="Connect one or more providers; PromptForge always shows the expected price up front and auto-routes to the cheapest connected provider for the model you pick."
      id="providers"
    >
      <div className="space-y-2.5">
        {providers?.providers.map((p) => (
          <ProviderRow
            key={p.name}
            p={p}
            settings={settings}
            save={save}
            spend={spend?.totals[p.name] ?? 0}
            onTested={() => {
              reload()
              reloadSpend()
            }}
          />
        ))}
      </div>
      <div className="space-y-2 border-t border-line pt-3">
        <p className="text-[12.5px] text-faint max-w-measure">
          Forge routing (spec: explicit choice → free/local where capable → best configured;
          fallback is per-request and always visible on the job).
        </p>
        <ToggleSetting settings={settings} k="forge_prefer_free" save={save}
          label="Prefer free/local options when they can do the job (Forge routing)" />
      </div>
      <div className="flex items-center gap-3 flex-wrap pt-1">
        <span className="text-[13px]">
          Total spend recorded: <strong className="tabular-nums">{formatMoney(spend?.total ?? 0)}</strong>
        </span>
        <button className="btn ml-auto" onClick={showPricing ? () => setShowPricing(false) : openPricing}>
          {showPricing ? 'Close pricing catalog' : 'Edit model catalog & pricing…'}
        </button>
      </div>
      {showPricing && (
        <div className="space-y-2">
          <textarea
            className="input font-mono text-[11.5px] min-h-[260px]"
            value={pricingJson}
            onChange={(e) => setPricingJson(e.target.value)}
            spellCheck={false}
            aria-label="Pricing catalog JSON"
          />
          <div className="flex gap-2">
            <button className="btn-accent" onClick={savePricing}>
              Save catalog
            </button>
            <p className="text-[11.5px] text-faint self-center">
              families → providers → model_id + price_per_image / price_per_mp / price_per_second by
              resolution
            </p>
          </div>
        </div>
      )}
    </Section>
  )
}
