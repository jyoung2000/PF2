// Guided setup cards (4.6) — Baserow + Discord, each with a real end-to-end
// Test connection flow, live status badge and specific, actionable errors.
import { useEffect, useState } from 'react'
import { api, ApiError, listCollections, listScrapers } from '../api'
import { timeAgo } from '../lib/format'
import { SettingsMap } from '../lib/settings'
import { toastError, toastSuccess } from '../lib/toast'
import { ConnBadge, Field, Section, TextSetting, ToggleSetting } from './SettingsKit'
import { Spinner } from './Primitives'

interface TestState {
  status: 'idle' | 'running' | 'ok' | 'error'
  summary?: string
  step?: string
  message?: string
}

function useTest(path: string, onDone?: () => void) {
  const [state, setState] = useState<TestState>({ status: 'idle' })
  const run = async () => {
    setState({ status: 'running' })
    try {
      const r = await api.post<{ summary?: string }>(path)
      setState({ status: 'ok', summary: r.summary ?? 'Connected ✓' })
      onDone?.()
    } catch (e) {
      if (e instanceof ApiError) {
        try {
          const parsed = JSON.parse(e.message) as { step?: string; message?: string }
          setState({ status: 'error', step: parsed.step, message: parsed.message ?? e.message })
        } catch {
          setState({ status: 'error', message: e.message })
        }
      } else {
        setState({ status: 'error', message: (e as Error).message })
      }
      onDone?.()
    }
  }
  return { state, run }
}

function TestResult({ state }: { state: TestState }) {
  if (state.status === 'ok')
    return (
      <p className="text-[12.5px] text-emerald-300 bg-emerald-400/10 border border-emerald-400/30 rounded-el px-3 py-2">
        ✓ {state.summary}
      </p>
    )
  if (state.status === 'error')
    return (
      <p className="text-[12.5px] text-red-300 bg-red-400/10 border border-red-400/30 rounded-el px-3 py-2">
        {state.step && <span className="chip !text-red-300 border-red-400/40 mr-1.5">{state.step}</span>}
        {state.message}
      </p>
    )
  return null
}

function StepLabel({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-[13px] font-medium text-fg">
      <span className="w-5 h-5 rounded-full bg-well border border-line text-[11px] flex items-center justify-center text-mute shrink-0">
        {n}
      </span>
      {children}
    </div>
  )
}

interface IntegrationStatuses {
  baserow: { status: string; last_tested?: string }
  discord: { status: string; last_tested?: string; gateway?: boolean }
}

export function BaserowCard({
  settings,
  save,
  status,
  reloadStatus,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
  status?: IntegrationStatuses['baserow']
  reloadStatus: () => void
}) {
  const { state, run } = useTest('/api/integrations/baserow/test', reloadStatus)
  const [tables, setTables] = useState<{ id: number; name: string }[] | null>(null)

  const loadTables = async () => {
    try {
      const r = await api.get<{ tables: { id: number; name: string }[] }>('/api/integrations/baserow/tables')
      setTables(r.tables)
    } catch (e) {
      toastError(e instanceof ApiError ? parseMsg(e) : (e as Error).message)
    }
  }

  return (
    <Section
      title="Baserow"
      hint="Sync your library into a Baserow table — media files included."
      id="baserow"
    >
      <div className="flex items-center gap-2 -mt-1">
        <ConnBadge status={status?.status ?? 'not_configured'} />
        {status?.last_tested && (
          <span className="text-[11.5px] text-faint">last tested {timeAgo(status.last_tested)}</span>
        )}
      </div>

      <StepLabel n={1}>Server & token</StepLabel>
      <div className="grid sm:grid-cols-2 gap-3 pl-7">
        <Field label="Baserow URL" htmlFor="setting-baserow_url" hint="Cloud default, or your self-hosted URL">
          <TextSetting settings={settings} k="baserow_url" save={save} placeholder="https://api.baserow.io" />
        </Field>
        <Field
          label="Database token"
          htmlFor="setting-baserow_token"
          hint={
            <>
              Create one in Baserow →{' '}
              <a
                href="https://baserow.io/user-docs/database-tokens"
                target="_blank"
                rel="noreferrer"
                className="underline underline-offset-2 hover:text-fg"
              >
                Settings → API tokens
              </a>{' '}
              with create/read/update rights.
            </>
          }
        >
          <TextSetting settings={settings} k="baserow_token" save={save} secret placeholder="Paste database token" />
        </Field>
      </div>

      <StepLabel n={2}>Table</StepLabel>
      <div className="pl-7 space-y-2">
        <p className="text-[12.5px] text-faint">
          Leave empty to auto-create a “PromptForge” table on first test, or pick an existing one:
        </p>
        <div className="flex gap-2 items-center flex-wrap">
          <button className="btn" onClick={loadTables}>
            Load my tables
          </button>
          {tables && (
            <select
              aria-label="Baserow table"
              className="input !w-auto"
              value={String(settings.baserow_table_id ?? '')}
              onChange={(e) => save({ baserow_table_id: e.target.value })}
            >
              <option value="">Auto-create “PromptForge”</option>
              {tables.map((t) => (
                <option key={t.id} value={String(t.id)}>
                  {t.name} (#{t.id})
                </option>
              ))}
            </select>
          )}
          {!tables && (
            <span className="text-[12px] text-faint">
              table id: <span className="font-mono">{String(settings.baserow_table_id || 'auto')}</span>
            </span>
          )}
        </div>
      </div>

      <StepLabel n={3}>Sync</StepLabel>
      <div className="pl-7">
        <ToggleSetting
          settings={settings}
          k="baserow_auto_sync"
          save={save}
          label="Auto-sync every new post to Baserow"
        />
      </div>

      <div className="flex items-center gap-2 pt-1">
        <button className="btn-accent" onClick={run} disabled={state.status === 'running'}>
          {state.status === 'running' ? <Spinner /> : 'Test connection'}
        </button>
        <span className="text-[11.5px] text-faint">
          Authenticates, verifies/creates the table schema, writes a test row and deletes it.
        </span>
      </div>
      <TestResult state={state} />
    </Section>
  )
}

function parseMsg(e: ApiError): string {
  try {
    const parsed = JSON.parse(e.message)
    return parsed.message ?? e.message
  } catch {
    return e.message
  }
}

export function DiscordCard({
  settings,
  save,
  status,
  reloadStatus,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
  status?: IntegrationStatuses['discord']
  reloadStatus: () => void
}) {
  const { state, run } = useTest('/api/integrations/discord/test', reloadStatus)
  const [howTo, setHowTo] = useState(false)
  const [invite, setInvite] = useState<string | null>(null)
  const [channels, setChannels] = useState<{ id: string; name: string; guild: string }[] | null>(null)

  const loadInvite = async () => {
    try {
      const r = await api.get<{ invite_url: string }>('/api/integrations/discord/invite')
      setInvite(r.invite_url)
    } catch (e) {
      toastError(e instanceof ApiError ? parseMsg(e) : (e as Error).message)
    }
  }
  const loadChannels = async () => {
    try {
      const r = await api.get<{ channels: { id: string; name: string; guild: string }[] }>(
        '/api/integrations/discord/channels',
      )
      setChannels(r.channels)
      if (!r.channels.length) toastError('The bot sees no text channels yet — invite it to a server first.')
    } catch (e) {
      toastError(e instanceof ApiError ? parseMsg(e) : (e as Error).message)
    }
  }

  return (
    <Section title="Discord" hint="A bot that posts picks to your server and answers /latest, /random, /search." id="discord">
      <div className="flex items-center gap-2 -mt-1">
        <ConnBadge status={status?.status ?? 'not_configured'} />
        {status?.gateway && <span className="chip text-emerald-300 border-emerald-400/40">gateway live</span>}
        {status?.last_tested && (
          <span className="text-[11.5px] text-faint">last tested {timeAgo(status.last_tested)}</span>
        )}
      </div>

      <StepLabel n={1}>Bot token</StepLabel>
      <div className="pl-7 space-y-2">
        <TextSetting settings={settings} k="discord_bot_token" save={save} secret placeholder="Paste bot token" />
        <button className="text-[12px] text-mute hover:text-fg underline underline-offset-2" onClick={() => setHowTo(!howTo)}>
          {howTo ? 'Hide' : 'How to create the bot'}
        </button>
        {howTo && (
          <ol className="text-[12.5px] text-mute list-decimal pl-5 space-y-1 bg-well/50 border border-line rounded-el p-3">
            <li>
              Open the{' '}
              <a className="underline underline-offset-2" href="https://discord.com/developers/applications" target="_blank" rel="noreferrer">
                Discord Developer Portal
              </a>{' '}
              → New Application → name it “PromptForge”.
            </li>
            <li>In the app: Bot → Reset Token → copy it here.</li>
            <li>No privileged intents needed — slash commands work out of the box.</li>
            <li>Use the invite link in step 2 to add it to your server.</li>
          </ol>
        )}
      </div>

      <StepLabel n={2}>Invite it to your server</StepLabel>
      <div className="pl-7 flex items-center gap-2 flex-wrap">
        <button className="btn" onClick={loadInvite}>
          Generate invite link
        </button>
        {invite && (
          <a href={invite} target="_blank" rel="noreferrer" className="btn-accent">
            Open invite ↗
          </a>
        )}
        <span className="text-[11.5px] text-faint">scopes + permissions pre-selected</span>
      </div>

      <StepLabel n={3}>Default channel</StepLabel>
      <div className="pl-7 flex items-center gap-2 flex-wrap">
        <button className="btn" onClick={loadChannels}>
          Load channels
        </button>
        {channels ? (
          <select
            aria-label="Discord channel"
            className="input !w-auto"
            value={String(settings.discord_channel_id ?? '')}
            onChange={(e) => save({ discord_channel_id: e.target.value })}
          >
            <option value="">Pick a channel…</option>
            {channels.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.name} · {c.guild}
              </option>
            ))}
          </select>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-faint">
            or paste ID:
            <span className="w-44 inline-block">
              <TextSetting settings={settings} k="discord_channel_id" save={save} placeholder="channel id" />
            </span>
          </span>
        )}
      </div>

      <StepLabel n={4}>What gets posted</StepLabel>
      <div className="pl-7">
        <DiscordRulesPanel />
      </div>

      <div className="flex items-center gap-2 pt-1">
        <button className="btn-accent" onClick={run} disabled={state.status === 'running'}>
          {state.status === 'running' ? <Spinner /> : 'Test connection'}
        </button>
        <span className="text-[11.5px] text-faint">Sends one sample embed (auto-deletes after ~10s).</span>
      </div>
      <TestResult state={state} />
    </Section>
  )
}

// ---------------------------------------------------------------- rules ----
interface DiscordRules {
  mode: 'manual' | 'all' | 'favorites' | 'collections' | 'families' | 'platforms'
  collections: number[]
  families: string[]
  platforms: string[]
  media: 'images' | 'videos' | 'both'
  require_prompt: boolean
  sfw_only: boolean
  delivery: 'individual' | 'digest'
  digest_hours: number
  digest_count: number
  routes: { match: 'family' | 'collection' | 'platform'; value: string | number; channel_id: string }[]
  throttle_per_hour: number
}

interface RulesPreview {
  scanned: number
  matched: number
  would_post: number
  delivery: string
}

const MODES: { value: DiscordRules['mode']; label: string; hint: string }[] = [
  { value: 'manual', label: 'Manual only', hint: 'Nothing posts unless you click “Post to Discord”.' },
  { value: 'all', label: 'All new finds', hint: 'Every ingested post that passes the filters.' },
  { value: 'favorites', label: 'Favorites only', hint: 'Posts you star.' },
  { value: 'collections', label: 'Selected collections', hint: 'Posts saved into chosen collections.' },
  { value: 'families', label: 'Selected model families', hint: 'e.g. only Flux and Kling.' },
  { value: 'platforms', label: 'Selected platforms', hint: 'e.g. only Midjourney finds.' },
]

export function DiscordRulesPanel() {
  const [rules, setRules] = useState<DiscordRules | null>(null)
  const [preview, setPreview] = useState<RulesPreview | null>(null)
  const [options, setOptions] = useState<{
    collections: { id: number; name: string }[]
    families: { family: string; label: string }[]
    platforms: string[]
  }>({ collections: [], families: [], platforms: [] })

  useEffect(() => {
    api
      .get<{ rules: DiscordRules; preview: RulesPreview }>('/api/integrations/discord/rules')
      .then((r) => {
        setRules(r.rules)
        setPreview(r.preview)
      })
      .catch(() => undefined)
    listCollections()
      .then((r) => setOptions((o) => ({ ...o, collections: r.user_collections.map((c) => ({ id: c.id, name: c.name })) })))
      .catch(() => undefined)
    api
      .get<{ models: { family: string; label: string }[] }>('/api/suggest')
      .then((r) => setOptions((o) => ({ ...o, families: r.models })))
      .catch(() => undefined)
    listScrapers()
      .then((r) => setOptions((o) => ({ ...o, platforms: r.scrapers.map((s) => s.name) })))
      .catch(() => undefined)
  }, [])

  const update = async (patch: Partial<DiscordRules>) => {
    if (!rules) return
    const next = { ...rules, ...patch }
    setRules(next)
    try {
      const r = await api.put<{ rules: DiscordRules; preview: RulesPreview }>('/api/integrations/discord/rules', patch)
      setRules(r.rules)
      setPreview(r.preview)
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  if (!rules) return <Spinner />

  const multiSelect = (
    kind: 'collections' | 'families' | 'platforms',
    items: { value: string | number; label: string }[],
  ) => (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {items.length === 0 && <span className="text-[12px] text-faint">none available yet</span>}
      {items.map((it) => {
        const list = rules[kind] as (string | number)[]
        const active = list.includes(it.value)
        return (
          <button
            key={String(it.value)}
            aria-pressed={active}
            className={`chip !text-[12px] transition-colors duration-fast ${active ? '!text-ember border-ember/60 bg-ember/10' : 'hover:border-mute/50'}`}
            onClick={() =>
              update({ [kind]: active ? list.filter((x) => x !== it.value) : [...list, it.value] } as Partial<DiscordRules>)
            }
          >
            {it.label}
          </button>
        )
      })}
    </div>
  )

  return (
    <div className="space-y-3 border border-line rounded-el p-3 bg-well/40">
      <div role="radiogroup" aria-label="Posting mode" className="space-y-1.5">
        {MODES.map((m) => (
          <label key={m.value} className="flex items-start gap-2 cursor-pointer text-[13px]">
            <input
              type="radio"
              name="discord-mode"
              className="mt-0.5 accent-[#FF6A3D]"
              checked={rules.mode === m.value}
              onChange={() => update({ mode: m.value })}
            />
            <span>
              {m.label} <span className="text-faint">— {m.hint}</span>
            </span>
          </label>
        ))}
      </div>
      {rules.mode === 'collections' &&
        multiSelect('collections', options.collections.map((c) => ({ value: c.id, label: c.name })))}
      {rules.mode === 'families' &&
        multiSelect('families', options.families.map((f) => ({ value: f.family, label: f.label })))}
      {rules.mode === 'platforms' && multiSelect('platforms', options.platforms.map((p) => ({ value: p, label: p })))}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3">
        <select
          aria-label="Media filter"
          className="input !w-auto h-8 py-0 text-[12.5px]"
          value={rules.media}
          onChange={(e) => update({ media: e.target.value as DiscordRules['media'] })}
        >
          <option value="both">Images + videos</option>
          <option value="images">Images only</option>
          <option value="videos">Videos only</option>
        </select>
        <label className="flex items-center gap-1.5 text-[12.5px]">
          <input type="checkbox" className="accent-[#FF6A3D]" checked={rules.require_prompt} onChange={(e) => update({ require_prompt: e.target.checked })} />
          must include a prompt
        </label>
        <label className="flex items-center gap-1.5 text-[12.5px]">
          <input type="checkbox" className="accent-[#FF6A3D]" checked={rules.sfw_only} onChange={(e) => update({ sfw_only: e.target.checked })} />
          SFW only
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3 text-[12.5px]">
        <label className="flex items-center gap-1.5">
          <input type="radio" name="delivery" className="accent-[#FF6A3D]" checked={rules.delivery === 'individual'} onChange={() => update({ delivery: 'individual' })} />
          Individual posts
        </label>
        <label className="flex items-center gap-1.5">
          <input type="radio" name="delivery" className="accent-[#FF6A3D]" checked={rules.delivery === 'digest'} onChange={() => update({ delivery: 'digest' })} />
          Digest
        </label>
        {rules.delivery === 'digest' && (
          <span className="flex items-center gap-1.5">
            every
            <input type="number" min={1} aria-label="Digest hours" className="input !w-14 h-7 tabular-nums" value={rules.digest_hours} onChange={(e) => update({ digest_hours: Number(e.target.value) })} />
            h, top
            <input type="number" min={1} aria-label="Digest count" className="input !w-14 h-7 tabular-nums" value={rules.digest_count} onChange={(e) => update({ digest_count: Number(e.target.value) })} />
            items
          </span>
        )}
        <span className="flex items-center gap-1.5 ml-auto">
          throttle
          <input type="number" min={1} aria-label="Throttle per hour" className="input !w-14 h-7 tabular-nums" value={rules.throttle_per_hour} onChange={(e) => update({ throttle_per_hour: Number(e.target.value) })} />
          / hour
        </span>
      </div>

      <RouteEditor rules={rules} options={options} update={update} />

      {preview && (
        <p className="text-[12px] text-mute border-t border-line pt-2.5">
          Preview: would have posted{' '}
          <strong className="text-fg tabular-nums">{preview.would_post}</strong> of{' '}
          <span className="tabular-nums">{preview.scanned}</span> items scraped in the last 24h with these
          rules{preview.delivery === 'digest' ? ' (digest mode)' : ''}.
        </p>
      )}
    </div>
  )
}

function RouteEditor({
  rules,
  options,
  update,
}: {
  rules: DiscordRules
  options: { collections: { id: number; name: string }[]; families: { family: string; label: string }[]; platforms: string[] }
  update: (p: Partial<DiscordRules>) => void
}) {
  const [draft, setDraft] = useState<{ match: 'family' | 'collection' | 'platform'; value: string; channel_id: string }>({
    match: 'family',
    value: '',
    channel_id: '',
  })
  const values =
    draft.match === 'family'
      ? options.families.map((f) => ({ v: f.family, l: f.label }))
      : draft.match === 'collection'
        ? options.collections.map((c) => ({ v: String(c.id), l: c.name }))
        : options.platforms.map((p) => ({ v: p, l: p }))
  return (
    <div className="border-t border-line pt-3 space-y-2">
      <p className="text-[12px] text-mute">
        Channel routing <span className="text-faint">— send a collection or model family to its own channel; everything else uses the default.</span>
      </p>
      {(rules.routes ?? []).map((r, i) => (
        <div key={i} className="flex items-center gap-2 text-[12.5px]">
          <span className="chip">{r.match}</span>
          <span className="font-mono">{String(r.value)}</span>
          <span className="text-faint">→</span>
          <span className="font-mono">#{r.channel_id}</span>
          <button
            aria-label="Remove route"
            className="text-faint hover:text-red-300"
            onClick={() => update({ routes: rules.routes.filter((_, j) => j !== i) })}
          >
            ✕
          </button>
        </div>
      ))}
      <div className="flex items-center gap-1.5 flex-wrap">
        <select aria-label="Route match type" className="input !w-auto h-7 py-0 text-[12px]" value={draft.match} onChange={(e) => setDraft({ ...draft, match: e.target.value as never, value: '' })}>
          <option value="family">model family</option>
          <option value="collection">collection</option>
          <option value="platform">platform</option>
        </select>
        <select aria-label="Route value" className="input !w-auto h-7 py-0 text-[12px]" value={draft.value} onChange={(e) => setDraft({ ...draft, value: e.target.value })}>
          <option value="">pick…</option>
          {values.map((v) => (
            <option key={v.v} value={v.v}>
              {v.l}
            </option>
          ))}
        </select>
        <input aria-label="Route channel id" className="input !w-36 h-7 text-[12px] font-mono" placeholder="channel id" value={draft.channel_id} onChange={(e) => setDraft({ ...draft, channel_id: e.target.value })} />
        <button
          className="btn h-7 py-0 text-[12px]"
          disabled={!draft.value || !draft.channel_id}
          onClick={() => {
            const value = draft.match === 'collection' ? Number(draft.value) : draft.value
            update({ routes: [...(rules.routes ?? []), { ...draft, value }] })
            setDraft({ match: draft.match, value: '', channel_id: '' })
            toastSuccess('Route added')
          }}
        >
          ＋ Add route
        </button>
      </div>
    </div>
  )
}
