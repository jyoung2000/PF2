// Settings → X.com & Grok (X1.6, X3.6, X5.4): one-click X connect (in-app
// login) + scope controls; Grok (xAI) quick-connect (paste key → auto-test →
// model picker) with per-feature toggles/budgets; monitoring defaults.
import { useState } from 'react'
import { api, ApiError, listScrapers } from '../api'
import { useFetch } from '../lib/hooks'
import { SettingsMap } from '../lib/settings'
import { ConnectModal, DisconnectButton, SessionUploadButton } from './ConnectModal'
import { Spinner } from './Primitives'
import { ConnBadge, Field, NumberSetting, Section, TextSetting, ToggleSetting } from './SettingsKit'

export function XSourceCard({
  settings,
  save,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
}) {
  const { data, reload } = useFetch(listScrapers)
  const [connecting, setConnecting] = useState(false)
  const x = data?.scrapers.find((s) => s.name === 'x')
  const session = x?.session_status ?? 'missing'

  return (
    <Section
      title="X.com source"
      hint="Scrapes AI media from X search + your monitored accounts through your own logged-in session. Freeform tweets are mined for prompts/models with deterministic rules — anything uncertain is flagged low-confidence so it never pollutes the knowledge engine."
      id="x-source"
    >
      <div className="flex items-center gap-2 -mt-1">
        <ConnBadge status={session === 'valid' ? 'connected' : session === 'expired' ? 'error' : 'not_configured'} />
        <span className="text-[12px] text-faint">login session: {session}</span>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button className={session === 'valid' ? 'btn' : 'btn-accent'} onClick={() => setConnecting(true)}>
          {session === 'valid' ? 'Reconnect X account' : 'Connect X account'}
        </button>
        {session === 'valid' ? (
          <DisconnectButton platform="x" onDone={reload} />
        ) : (
          <SessionUploadButton platform="x" onDone={reload}>
            or upload x.json…
          </SessionUploadButton>
        )}
      </div>
      {session !== 'valid' && (
        <details className="text-[12.5px] text-mute">
          <summary className="cursor-pointer hover:text-fg">
            Prefer to log in on your desktop instead? (classic walkthrough)
          </summary>
          <div className="bg-well/50 border border-line rounded-el p-3 space-y-1 mt-1.5">
            <p className="font-mono text-[12px]">pip install playwright && playwright install chromium</p>
            <p className="font-mono text-[12px]">python scripts/capture_login.py x</p>
            <p>
              Log in in the window, press Enter, then upload the exported file with the button above (or copy it to{' '}
              <span className="font-mono text-[12px]">/data/sessions/x.json</span>).
            </p>
          </div>
        </details>
      )}
      {connecting && (
        <ConnectModal platform="x" label="X.com" onClose={() => setConnecting(false)} onConnected={reload} />
      )}
      <p className="text-[11.5px] text-faint">
        Heads-up: logged-in scraping is subject to X's Terms of Service and runs on <em>your</em> account —
        PromptForge polls gently (one browser, conservative backoff), but keep intervals relaxed.
      </p>

      <div className="grid sm:grid-cols-2 gap-3">
        <Field
          label="Search terms / hashtags"
          htmlFor="setting-x_search_terms"
          hint="Comma-separated; one is polled per run, rotating."
        >
          <TextSetting settings={settings} k="x_search_terms" save={save} placeholder="#midjourney, #AIvideo, #flux" />
        </Field>
        <Field label="Max tweets per run" htmlFor="setting-x_max_per_run">
          <NumberSetting settings={settings} k="x_max_per_run" save={save} min={5} max={200} />
        </Field>
        <Field
          label="Minimum engagement"
          htmlFor="setting-x_min_engagement"
          hint="Likes + reposts below this are skipped (cuts noise)."
        >
          <NumberSetting settings={settings} k="x_min_engagement" save={save} min={0} />
        </Field>
        <Field label="Media types" htmlFor="setting-x-media-filter">
          <select
            id="setting-x-media-filter"
            className="input !w-auto"
            value={String(settings.x_media_filter ?? 'both')}
            onChange={(e) => save({ x_media_filter: e.target.value })}
          >
            <option value="both">Images + videos</option>
            <option value="images">Images only</option>
            <option value="videos">Videos only</option>
          </select>
        </Field>
      </div>
      <ToggleSetting settings={settings} k="x_skip_replies" save={save} label="Skip replies (recommended)" />
      <div className="grid sm:grid-cols-2 gap-3">
        <Field label="Monitoring default interval" htmlFor="setting-monitor_default_interval" hint="For newly added accounts">
          <NumberSetting settings={settings} k="monitor_default_interval" save={save} min={15} suffix="min" />
        </Field>
        <Field label="Monitoring default auto-tag" htmlFor="setting-monitor_default_tag" hint="Applied to finds from new accounts (blank = none)">
          <TextSetting settings={settings} k="monitor_default_tag" save={save} placeholder="e.g. x-finds" />
        </Field>
      </div>
    </Section>
  )
}

interface GrokTestResult {
  ok: boolean
  detail: string
  models?: string[]
}

/** Paste-to-connect key input: committing a key (paste/Enter/blur) saves it
 * and immediately runs the connection test — one paste and Grok is live. */
function GrokKeyInput({
  settings,
  save,
  onSaved,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
  onSaved: () => void
}) {
  const stored = String(settings.grok_api_key ?? '')
  const [value, setValue] = useState('')

  const commit = async (raw?: string) => {
    const v = (raw ?? value).trim()
    if (!v) return
    if (await save({ grok_api_key: v })) {
      setValue('')
      onSaved()
    }
  }

  return (
    <input
      id="setting-grok_api_key"
      type="text"
      autoComplete="off"
      spellCheck={false}
      className="input font-mono"
      placeholder={stored ? `${stored} (stored — paste to replace)` : 'xai-… (paste to connect)'}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onPaste={(e) => {
        const text = e.clipboardData.getData('text').trim()
        if (text) {
          e.preventDefault()
          setValue(text)
          void commit(text)
        }
      }}
      onBlur={() => void commit()}
      onKeyDown={(e) => e.key === 'Enter' && void commit()}
    />
  )
}

export function GrokCard({
  settings,
  save,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
}) {
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<GrokTestResult | null>(null)
  const [models, setModels] = useState<string[]>([])
  const configured = Boolean(settings.grok_api_key)

  const runTest = async () => {
    setTesting(true)
    setResult(null)
    try {
      const r = await api.post<GrokTestResult>('/api/grok/test')
      setResult(r)
      if (r.models?.length) setModels(r.models)
    } catch (e) {
      let detail = e instanceof ApiError ? e.message : String(e)
      try {
        detail = JSON.parse(detail).message ?? detail
      } catch {
        /* plain */
      }
      setResult({ ok: false, detail })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Section
      title="Grok (xAI)"
      hint="Optional intelligence layer on top of X: discover AI creators with live X search, verify + enrich scraped media, and get periodic digests of your follow list. Also selectable as the knowledge-engine provider."
      id="grok"
    >
      <div className="flex items-center gap-2 -mt-1 flex-wrap">
        <ConnBadge status={!configured ? 'not_configured' : result?.ok === false ? 'error' : 'connected'} />
        <a
          className="btn !py-1 !px-2.5 text-[12px]"
          href="https://console.x.ai"
          target="_blank"
          rel="noreferrer"
        >
          Get an API key ↗
        </a>
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <Field
          label="xAI API key"
          htmlFor="setting-grok_api_key"
          hint="Pasting a key connects immediately — it saves and tests itself."
        >
          <GrokKeyInput settings={settings} save={save} onSaved={runTest} />
        </Field>
        <Field label="Model" htmlFor="setting-grok-model" hint="Test connection to fetch the live list.">
          {models.length > 0 ? (
            <select
              id="setting-grok-model"
              className="input"
              value={String(settings.grok_model ?? '')}
              onChange={(e) => save({ grok_model: e.target.value })}
            >
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          ) : (
            <TextSetting settings={settings} k="grok_model" save={save} placeholder="grok-3-mini" />
          )}
        </Field>
      </div>

      <div className="flex items-center gap-2">
        <button className="btn-accent" onClick={runTest} disabled={testing || !configured}>
          {testing ? <Spinner /> : 'Test connection'}
        </button>
        {!configured && <span className="text-[12px] text-faint">Paste a key first — everything below stays dormant until then.</span>}
      </div>
      {result && (
        <p
          className={`text-[12.5px] rounded-el px-3 py-2 border ${
            result.ok
              ? 'text-emerald-300 bg-emerald-400/10 border-emerald-400/30'
              : 'text-red-300 bg-red-400/10 border-red-400/30'
          }`}
        >
          {result.ok ? '✓ ' : ''}
          {result.detail}
        </p>
      )}

      <div className="space-y-2.5 border-t border-line pt-3">
        <ToggleSetting
          settings={settings}
          k="grok_discover_enabled"
          save={save}
          label="Discover — “Find AI creators” tool on the Monitoring page (uses live X search)"
        />
        <div className="flex items-center gap-3 flex-wrap">
          <ToggleSetting
            settings={settings}
            k="grok_curate_enabled"
            save={save}
            label="Curate — verify fresh X finds are AI media, infer models, suggest technique tags"
          />
          <span className="inline-flex items-center gap-1.5 text-[12px] text-faint">
            budget
            <NumberSetting settings={settings} k="grok_curate_daily_budget" save={save} min={0} suffix="calls/day" />
          </span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <ToggleSetting
            settings={settings}
            k="grok_digest_enabled"
            save={save}
            label="Digest — periodic “what's new from your monitored accounts” summary"
          />
          <span className="inline-flex items-center gap-1.5 text-[12px] text-faint">
            every
            <NumberSetting settings={settings} k="grok_digest_hours" save={save} min={1} suffix="h" />
          </span>
          <ToggleSetting settings={settings} k="grok_digest_to_discord" save={save} label="also post digest to Discord" />
        </div>
      </div>
    </Section>
  )
}
