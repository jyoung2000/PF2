// Settings → Social accounts (I5.4), X.com scope (X1.6), Grok features (X3.6).
// Credentials live in ONE place (SocialAccountsCard): X login session, Grok
// Web session (a grok.com browser login — never an API authorisation) and the
// xAI API key. Each feature only needs the credential it actually uses.
import { useState } from 'react'
import { api, ApiError, listScrapers } from '../api'
import { useFetch } from '../lib/hooks'
import { SettingsMap } from '../lib/settings'
import { toastError, toastSuccess } from '../lib/toast'
import { ConnectModal, DisconnectButton, SessionUploadButton } from './ConnectModal'
import { Spinner } from './Primitives'
import { ConnBadge, Field, NumberSetting, Section, TextSetting, ToggleSetting } from './SettingsKit'

interface GrokStatus {
  configured: boolean
  web_session: { connected: boolean; saved_at: string | null }
  usage: { calls?: number }
  curate_budget: number
  features: { discover: boolean; curate: boolean; digest: boolean }
}

interface GrokTestResult {
  ok: boolean
  detail: string
  models?: string[]
}

async function testGrok(): Promise<GrokTestResult> {
  try {
    return await api.post<GrokTestResult>('/api/grok/test')
  } catch (e) {
    let detail = e instanceof ApiError ? e.message : String(e)
    try {
      detail = JSON.parse(detail).message ?? detail
    } catch {
      /* plain */
    }
    return { ok: false, detail }
  }
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

function AccountRow({
  title,
  badge,
  detail,
  children,
}: {
  title: string
  badge: 'connected' | 'error' | 'not_configured'
  detail: string
  children: React.ReactNode
}) {
  return (
    <div className="grid sm:grid-cols-[130px_1fr] gap-2 sm:gap-4 items-start py-3 border-t border-line first:border-t-0 first:pt-0">
      <div>
        <div className="font-medium text-[13.5px]">{title}</div>
        <div className="mt-1">
          <ConnBadge status={badge} />
        </div>
      </div>
      <div className="space-y-2">
        <p className="text-[12.5px] text-mute">{detail}</p>
        <div className="flex items-center gap-2 flex-wrap">{children}</div>
      </div>
    </div>
  )
}

export function SocialAccountsCard({
  settings,
  save,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
}) {
  const { data, reload } = useFetch(listScrapers)
  const { data: gs, reload: reloadGrok } = useFetch(() => api.get<GrokStatus>('/api/grok/status'))
  const [connecting, setConnecting] = useState<'x' | 'grok' | null>(null)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<GrokTestResult | null>(null)
  const x = data?.scrapers.find((s) => s.name === 'x')
  const session = x?.session_status ?? 'missing'
  const web = gs?.web_session
  const keyConfigured = Boolean(settings.grok_api_key)

  const runTest = async () => {
    setTesting(true)
    const r = await testGrok()
    setResult(r)
    setTesting(false)
    reloadGrok()
    if (r.ok) toastSuccess('Grok API connected ✓')
  }

  const disconnectWeb = async () => {
    try {
      await api.delete('/api/grok/session')
      toastSuccess('Grok Web session removed')
      reloadGrok()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  return (
    <Section
      title="Social accounts"
      hint="Connect X for scraping and monitoring, and Grok for the intelligence layer. Use any combination — X only, X + Grok Web, X + Grok API, or all three. Each feature asks only for the credential it needs."
      id="social"
    >
      <AccountRow
        title="X"
        badge={session === 'valid' ? 'connected' : session === 'expired' ? 'error' : 'not_configured'}
        detail={`Your own X login session — powers search crawls and account monitoring. Session: ${session}.`}
      >
        <button className={session === 'valid' ? 'btn' : 'btn-accent'} onClick={() => setConnecting('x')}>
          {session === 'valid' ? 'Reconnect X account' : 'Connect X account'}
        </button>
        {session === 'valid' ? (
          <DisconnectButton platform="x" onDone={reload} />
        ) : (
          <SessionUploadButton platform="x" onDone={reload}>
            or upload x.json…
          </SessionUploadButton>
        )}
      </AccountRow>

      <AccountRow
        title="Grok Web"
        badge={web?.connected ? 'connected' : 'not_configured'}
        detail="A grok.com browser session captured with the same in-app login. This is NOT an API key and authorises no API feature — it is stored for browser-based Grok features; nothing depends on it yet."
      >
        <button className={web?.connected ? 'btn' : 'btn-accent'} onClick={() => setConnecting('grok')}>
          {web?.connected ? 'Reconnect Grok Web' : 'Connect Grok Web'}
        </button>
        {web?.connected && (
          <>
            <button className="btn" onClick={disconnectWeb}>
              Disconnect
            </button>
            <span className="text-[12px] text-faint">saved {web.saved_at ? new Date(web.saved_at).toLocaleString() : ''}</span>
          </>
        )}
      </AccountRow>

      <AccountRow
        title="Grok API"
        badge={!keyConfigured ? 'not_configured' : result?.ok === false ? 'error' : 'connected'}
        detail="xAI API key — powers Discover (live X search), Curate, Digest and the “Grok” knowledge-engine provider. Pasting a key saves and tests it in one go; the key is never shown again after saving."
      >
        <span className="w-full sm:w-80">
          <GrokKeyInput settings={settings} save={save} onSaved={runTest} />
        </span>
        <a className="btn !py-1.5 text-[12px]" href="https://console.x.ai" target="_blank" rel="noreferrer">
          Get an API key ↗
        </a>
        {keyConfigured && (
          <button className="btn !py-1.5 text-[12px]" onClick={runTest} disabled={testing}>
            {testing ? <Spinner /> : 'Test'}
          </button>
        )}
        {keyConfigured && gs?.usage?.calls != null && (
          <span className="chip !text-[11.5px]">used today: {gs.usage.calls}</span>
        )}
      </AccountRow>
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

      <div className="text-[12px] text-faint border-t border-line pt-3 grid sm:grid-cols-2 gap-x-6 gap-y-1">
        <span>Search crawls &amp; monitoring → X session</span>
        <span>Find creators / Curate / Digest → Grok API key</span>
        <span>Knowledge provider “Grok” → Grok API key</span>
        <span>Grok Web → optional, no feature requires it yet</span>
      </div>

      {connecting && (
        <ConnectModal
          platform={connecting}
          label={connecting === 'x' ? 'X.com' : 'Grok Web'}
          onClose={() => setConnecting(null)}
          onConnected={() => {
            reload()
            reloadGrok()
          }}
        />
      )}
    </Section>
  )
}

export function XSourceCard({
  settings,
  save,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
}) {
  const { data } = useFetch(listScrapers)
  const x = data?.scrapers.find((s) => s.name === 'x')
  const session = x?.session_status ?? 'missing'

  return (
    <Section
      title="X.com source"
      hint="Scrapes AI media from X search + your monitored accounts through your own logged-in session. Freeform tweets are mined for prompts/models with deterministic rules — anything uncertain is flagged low-confidence so it never pollutes the knowledge engine."
      id="x-source"
    >
      {session !== 'valid' && (
        <p className="text-[12.5px] text-amber-200 bg-amber-400/10 border border-amber-400/30 rounded-el px-3 py-2">
          No X login session yet — connect it under{' '}
          <a href="#social" className="underline underline-offset-2">
            Social accounts
          </a>{' '}
          above. Crawls wait until then.
        </p>
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

export function GrokCard({
  settings,
  save,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
}) {
  const [loadingModels, setLoadingModels] = useState(false)
  const [models, setModels] = useState<string[]>([])
  const [note, setNote] = useState<string | null>(null)
  const configured = Boolean(settings.grok_api_key)

  const loadModels = async () => {
    setLoadingModels(true)
    const r = await testGrok()
    setLoadingModels(false)
    if (r.ok && r.models?.length) {
      setModels(r.models)
      setNote(null)
    } else {
      setNote(r.detail)
    }
  }

  return (
    <Section
      title="Grok (xAI) features"
      hint="Optional intelligence layer on top of X: discover AI creators with live X search, verify + enrich scraped media, and get periodic digests of your follow list. Also selectable as the knowledge-engine provider. Needs the Grok API key from Social accounts."
      id="grok"
    >
      <div className="flex items-center gap-2 -mt-1 flex-wrap">
        <ConnBadge status={configured ? 'connected' : 'not_configured'} />
        {!configured && (
          <span className="text-[12px] text-faint">
            Paste a key under{' '}
            <a href="#social" className="underline underline-offset-2 hover:text-fg">
              Social accounts
            </a>{' '}
            — everything below stays dormant until then.
          </span>
        )}
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <Field label="Model" htmlFor="setting-grok-model" hint={note ?? 'Load the live list to pick from your account’s models.'}>
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
        <div className="flex items-end">
          <button className="btn" onClick={loadModels} disabled={loadingModels || !configured}>
            {loadingModels ? <Spinner /> : 'Load model list'}
          </button>
        </div>
      </div>

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
