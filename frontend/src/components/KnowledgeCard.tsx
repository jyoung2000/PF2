// Settings → Knowledge engine: LLM provider picker (Anthropic / OpenAI-compat
// / Ollama / Companion) with test button, daily budget + live usage counter,
// knowledge file overview, pack import/export (6.9).
import { useRef, useState } from 'react'
import { api, ApiError } from '../api'
import { formatBytes } from '../lib/format'
import { useFetch } from '../lib/hooks'
import { SettingsMap } from '../lib/settings'
import { toastError, toastSuccess } from '../lib/toast'
import { Spinner } from './Primitives'
import { ConnBadge, Field, NumberSetting, Section, TextSetting } from './SettingsKit'

interface KnowledgeOverview {
  foundation: { exists: boolean; size_bytes: number }
  models: { family: string; label: string; size_bytes: number; updated: string | null; analyzed_at: string | null }[]
  styles: { collection_id: number; collection: string; size_bytes: number }[]
  llm: { provider: string; usage: { calls: number }; budget: number; budget_applies: boolean }
}

const PROVIDERS = [
  { value: '', label: 'None (deterministic stats only)' },
  { value: 'anthropic', label: 'Anthropic API' },
  { value: 'openai', label: 'OpenAI-compatible endpoint' },
  { value: 'grok', label: 'Grok (xAI) — key from the Grok section below' },
  { value: 'ollama', label: 'Ollama (direct URL) — free' },
  { value: 'companion', label: 'Companion (desktop GPU) — free' },
]

export function KnowledgeCard({
  settings,
  save,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
}) {
  const { data, reload } = useFetch(() => api.get<KnowledgeOverview>('/api/knowledge'))
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; detail: string } | null>(null)
  const [showFiles, setShowFiles] = useState(false)
  const fileInput = useRef<HTMLInputElement | null>(null)
  const provider = String(settings.llm_provider ?? '')

  const runTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await api.post<{ ok: boolean; detail: string }>('/api/knowledge/llm/test')
      setTestResult({ ok: true, detail: r.detail })
    } catch (e) {
      setTestResult({ ok: false, detail: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setTesting(false)
    }
  }

  const learnNow = async () => {
    try {
      await api.post('/api/knowledge/learn-now')
      toastSuccess('Learning pass started — watch the Scrapers live log')
      window.setTimeout(reload, 4000)
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const importPack = async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    try {
      const resp = await fetch('/api/knowledge/pack/import', { method: 'POST', body: form })
      const body = await resp.json()
      if (!resp.ok) throw new Error(body.detail ?? 'Import failed')
      toastSuccess(`Imported: ${body.imported.join(', ') || 'nothing new'}`)
      reload()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  return (
    <Section
      title="Knowledge engine"
      hint="PromptForge learns prompting per model from every scraped post and generation. Deterministic stats are always free; the AI provider below powers deep analysis, technique tagging, templates and Enhance."
      id="knowledge"
    >
      <div className="flex items-center gap-2 -mt-1">
        <ConnBadge
          status={!provider ? 'not_configured' : testResult?.ok === false ? 'error' : 'connected'}
        />
        {data?.llm.budget_applies === false && provider && (
          <span className="chip text-emerald-300 border-emerald-400/40">free provider — budget ignored</span>
        )}
      </div>

      <Field label="AI provider (analysis, templates, Enhance — never scraping)" htmlFor="llm-provider">
        <select
          id="llm-provider"
          className="input !w-auto"
          value={provider}
          onChange={(e) => save({ llm_provider: e.target.value })}
        >
          {PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </Field>

      {provider === 'anthropic' && (
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Anthropic API key" htmlFor="setting-anthropic_api_key">
            <TextSetting settings={settings} k="anthropic_api_key" save={save} secret placeholder="sk-ant-…" />
          </Field>
          <Field label="Model" htmlFor="setting-anthropic_model">
            <TextSetting settings={settings} k="anthropic_model" save={save} placeholder="claude-sonnet-5" />
          </Field>
        </div>
      )}
      {provider === 'openai' && (
        <div className="grid sm:grid-cols-3 gap-3">
          <Field label="Base URL" htmlFor="setting-openai_base_url">
            <TextSetting settings={settings} k="openai_base_url" save={save} placeholder="https://api.openai.com/v1" />
          </Field>
          <Field label="API key" htmlFor="setting-openai_api_key">
            <TextSetting settings={settings} k="openai_api_key" save={save} secret placeholder="sk-…" />
          </Field>
          <Field label="Model" htmlFor="setting-openai_model">
            <TextSetting settings={settings} k="openai_model" save={save} placeholder="gpt-4o-mini" />
          </Field>
        </div>
      )}
      {provider === 'ollama' && (
        <div className="grid sm:grid-cols-2 gap-3">
          <Field
            label="Ollama URL"
            htmlFor="setting-ollama_base_url"
            hint="From Docker, your desktop's Ollama is http://host.docker.internal:11434 — or pair the companion app instead."
          >
            <TextSetting settings={settings} k="ollama_base_url" save={save} placeholder="http://host.docker.internal:11434" />
          </Field>
          <Field label="Model" htmlFor="setting-ollama_model">
            <TextSetting settings={settings} k="ollama_model" save={save} placeholder="llama3.1" />
          </Field>
        </div>
      )}
      {provider === 'companion' && (
        <p className="text-[12.5px] text-mute">
          Uses your desktop GPU through the paired companion app — set it up in the{' '}
          <a href="#companion" className="underline underline-offset-2 hover:text-fg">
            Companion section
          </a>{' '}
          below. Jobs queue while the companion is offline. Model:{' '}
          <span className="w-40 inline-block align-middle">
            <TextSetting settings={settings} k="ollama_model" save={save} placeholder="llama3.1" />
          </span>
        </p>
      )}

      <div className="flex items-center gap-3 flex-wrap">
        <Field label="Daily analysis budget (LLM calls)" htmlFor="setting-llm_daily_budget">
          <NumberSetting settings={settings} k="llm_daily_budget" save={save} min={0} suffix="calls/day" />
        </Field>
        {data && (
          <span className="chip !text-[12px] mt-4">
            used today: {data.llm.usage?.calls ?? 0}
            {data.llm.budget_applies ? ` / ${data.llm.budget}` : ' (free)'}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 flex-wrap pt-1">
        {provider && (
          <button className="btn-accent" onClick={runTest} disabled={testing}>
            {testing ? <Spinner /> : 'Test provider'}
          </button>
        )}
        <button className="btn" onClick={learnNow}>
          Run learning pass now
        </button>
        <button className="btn" onClick={() => setShowFiles(!showFiles)}>
          {showFiles ? 'Hide' : 'Show'} knowledge files ({data?.models.length ?? 0})
        </button>
        <button className="btn" onClick={() => fileInput.current?.click()}>
          Import .pfpack…
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".pfpack,.zip"
          className="hidden"
          aria-label="Import knowledge pack"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) importPack(f)
            e.currentTarget.value = ''
          }}
        />
      </div>

      {testResult && (
        <p
          className={`text-[12.5px] rounded-el px-3 py-2 border ${
            testResult.ok
              ? 'text-emerald-300 bg-emerald-400/10 border-emerald-400/30'
              : 'text-red-300 bg-red-400/10 border-red-400/30'
          }`}
        >
          {testResult.ok ? '✓ ' : ''}
          {testResult.detail}
        </p>
      )}

      {showFiles && data && (
        <div className="border border-line rounded-el divide-y divide-line text-[12.5px]">
          <div className="px-3 py-2 flex justify-between">
            <span>
              foundation.md <span className="text-faint">(the shared fundamentals)</span>
            </span>
            <span className="text-faint tabular-nums">{formatBytes(data.foundation.size_bytes)}</span>
          </div>
          {data.models.map((m) => (
            <div key={m.family} className="px-3 py-2 flex justify-between gap-2">
              <span>
                models/{m.family}.md
                {m.analyzed_at && <span className="text-faint"> · analyzed {m.analyzed_at}</span>}
              </span>
              <span className="flex items-center gap-2 shrink-0">
                <a
                  className="text-mute hover:text-fg underline underline-offset-2"
                  href={`/api/knowledge/pack/export?family=${m.family}`}
                >
                  export
                </a>
                <span className="text-faint tabular-nums">{formatBytes(m.size_bytes)}</span>
              </span>
            </div>
          ))}
          {data.styles.map((st) => (
            <div key={st.collection_id} className="px-3 py-2 flex justify-between gap-2">
              <span>styles/collection-{st.collection_id}.md — “{st.collection}”</span>
              <span className="flex items-center gap-2 shrink-0">
                <a
                  className="text-mute hover:text-fg underline underline-offset-2"
                  href={`/api/knowledge/pack/export?collection_id=${st.collection_id}`}
                >
                  export
                </a>
                <span className="text-faint tabular-nums">{formatBytes(st.size_bytes)}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </Section>
  )
}
