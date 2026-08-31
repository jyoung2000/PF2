// Follow-list monitoring (X2.5): curate X accounts the app watches — bulk
// add, per-account controls, run-now, pause/resume-all, recent-finds strip.
// Also hosts the Grok "Find AI creators" tool (X3.3).
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, listCollections, searchPosts } from '../api'
import { ConfirmModal, EmptyState, Modal, Spinner, StatusDot } from '../components/Primitives'
import { timeAgo } from '../lib/format'
import { useFetch } from '../lib/hooks'
import { toastError, toastSuccess } from '../lib/toast'

interface MonitoredAccount {
  id: number
  handle: string
  display_name: string | null
  platform: string
  added_by: 'manual' | 'grok'
  notes: string | null
  active: boolean
  last_checked: string | null
  last_post_id: string | null
  check_interval: number
  media_only: boolean
  auto_tag: string | null
  auto_collection_id: number | null
  auto_collection_name: string | null
  status: 'ok' | 'error' | 'not_found' | null
  last_error: string | null
  last_new: number
  total_posts: number
  profile_url: string
  created_at: string | null
}

interface MonitoringData {
  accounts: MonitoredAccount[]
  x_session_ok: boolean
  defaults: { interval: number; auto_tag: string }
}

function AddBox({ onAdded }: { onAdded: () => void }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  const add = async () => {
    if (!text.trim()) return
    setBusy(true)
    try {
      const r = await api.post<{
        created: MonitoredAccount[]
        already_monitored: string[]
        rejected: string[]
      }>('/api/monitoring/accounts', { text })
      const bits = []
      if (r.created.length) bits.push(`added ${r.created.map((a) => '@' + a.handle).join(', ')}`)
      if (r.already_monitored.length) bits.push(`already watching ${r.already_monitored.length}`)
      if (r.rejected.length) bits.push(`couldn't parse: ${r.rejected.join(', ')}`)
      ;(r.created.length ? toastSuccess : toastError)(bits.join(' · ') || 'Nothing to add')
      if (r.created.length) {
        setText('')
        onAdded()
      }
    } catch (e) {
      toastError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card p-3.5">
      <label className="label" htmlFor="mon-add">
        Add accounts to watch
      </label>
      <textarea
        id="mon-add"
        className="input min-h-[64px] font-mono text-[12.5px]"
        placeholder={'@handle, bare handle, or profile URL — bulk paste welcome:\n@aurorforge  x.com/motionmuse  https://x.com/papercut_ai'}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) add()
        }}
      />
      <div className="flex items-center gap-2 mt-2">
        <button className="btn-accent" disabled={busy || !text.trim()} onClick={add}>
          {busy ? <Spinner /> : '＋ Watch accounts'}
        </button>
        <span className="text-[11.5px] text-faint">Validated on the first poll — a bad handle flips to “not found”.</span>
      </div>
    </div>
  )
}

function AccountCard({
  a,
  collections,
  onChanged,
}: {
  a: MonitoredAccount
  collections: { id: number; name: string }[]
  onChanged: () => void
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [running, setRunning] = useState(false)
  const [interval, setIntervalMin] = useState(a.check_interval)
  const [autoTag, setAutoTag] = useState(a.auto_tag ?? '')

  const patch = async (body: Record<string, unknown>) => {
    try {
      await api.patch(`/api/monitoring/accounts/${a.id}`, body)
      onChanged()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const runNow = async () => {
    setRunning(true)
    try {
      await api.post(`/api/monitoring/accounts/${a.id}/run`)
      toastSuccess(`Polling @${a.handle} — watch the Scrapers live log`)
      window.setTimeout(onChanged, 2500)
    } catch (e) {
      toastError(e instanceof ApiError ? e.message : String(e))
    } finally {
      window.setTimeout(() => setRunning(false), 1500)
    }
  }

  const statusKind =
    a.status === 'ok' ? 'ok' : a.status === 'error' || a.status === 'not_found' ? 'error' : 'off'

  return (
    <div className={`card p-3.5 flex flex-col gap-2.5 ${a.active ? '' : 'opacity-60'}`}>
      <div className="flex items-center gap-2.5">
        <span
          aria-hidden
          className="w-9 h-9 rounded-full bg-well border border-line flex items-center justify-center font-display font-semibold text-[15px] text-ember shrink-0"
        >
          {a.handle[0].toUpperCase()}
        </span>
        <div className="min-w-0">
          <a
            href={a.profile_url}
            target="_blank"
            rel="noreferrer"
            className="font-display font-medium text-[14.5px] hover:text-ember truncate block"
          >
            @{a.handle}
          </a>
          <p className="text-[11.5px] text-faint">
            {a.added_by === 'grok' && <span className="text-ember-soft">via Grok · </span>}
            checked {timeAgo(a.last_checked)} ·{' '}
            <span className="tabular-nums">
              +{a.last_new} last poll · {a.total_posts} collected
            </span>
          </p>
        </div>
        <span className="ml-auto shrink-0">
          <StatusDot
            status={statusKind as never}
            label={a.status === 'not_found' ? 'not found' : (a.status ?? 'never run')}
          />
        </span>
      </div>

      {a.last_error && a.status !== 'ok' && (
        <p className="text-[11.5px] text-red-300/90 break-words">{a.last_error}</p>
      )}

      <div className="flex items-center gap-2 flex-wrap text-[12px]">
        <button
          role="switch"
          aria-checked={a.active}
          aria-label={`@${a.handle} active`}
          onClick={() => patch({ active: !a.active })}
          className={`shrink-0 relative w-9 h-5 rounded-full transition-colors duration-fast ${a.active ? 'bg-ember' : 'bg-well border border-line'}`}
        >
          <span
            className={`absolute top-0.5 w-4 h-4 rounded-full bg-fg transition-transform duration-fast ${a.active ? 'translate-x-4' : 'translate-x-0.5'}`}
          />
        </button>
        <label className="flex items-center gap-1 text-mute">
          every
          <input
            type="number"
            min={5}
            aria-label={`@${a.handle} interval`}
            className="input !w-16 h-7 text-[12px] tabular-nums"
            value={interval}
            onChange={(e) => setIntervalMin(Number(e.target.value))}
            onBlur={() => interval !== a.check_interval && patch({ check_interval: interval })}
          />
          min
        </label>
        <label className="flex items-center gap-1.5 text-mute">
          <input
            type="checkbox"
            className="accent-[#FF6A3D]"
            checked={a.media_only}
            onChange={(e) => patch({ media_only: e.target.checked })}
          />
          media posts only
        </label>
        <button className="btn h-7 py-0 text-[12px] ml-auto" onClick={runNow} disabled={running}>
          {running ? <Spinner /> : '▶ Run now'}
        </button>
      </div>

      <div className="flex items-center gap-2 flex-wrap text-[12px] border-t border-line pt-2">
        <label className="flex items-center gap-1 text-mute">
          auto-tag
          <input
            aria-label={`@${a.handle} auto tag`}
            className="input !w-28 h-7 text-[12px]"
            placeholder="none"
            value={autoTag}
            onChange={(e) => setAutoTag(e.target.value)}
            onBlur={() => (autoTag || null) !== (a.auto_tag || null) && patch({ auto_tag: autoTag })}
          />
        </label>
        <label className="flex items-center gap-1 text-mute">
          → collection
          <select
            aria-label={`@${a.handle} auto collection`}
            className="input !w-auto h-7 py-0 text-[12px]"
            value={a.auto_collection_id ?? 0}
            onChange={(e) => patch({ auto_collection_id: Number(e.target.value) })}
          >
            <option value={0}>none</option>
            {collections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <button
          aria-label={`Remove @${a.handle}`}
          className="btn-danger h-7 py-0 text-[12px] ml-auto"
          onClick={() => setConfirmDelete(true)}
        >
          Remove
        </button>
      </div>

      {confirmDelete && (
        <ConfirmModal
          title={`Stop watching @${a.handle}?`}
          message="The account comes off the follow list. Everything already collected stays in your library."
          confirmLabel="Remove"
          onConfirm={async () => {
            try {
              await api.delete(`/api/monitoring/accounts/${a.id}`)
              toastSuccess(`Stopped watching @${a.handle}`)
              onChanged()
            } catch (e) {
              toastError((e as Error).message)
            }
          }}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </div>
  )
}

function RecentFinds() {
  const { data } = useFetch(() => searchPosts({ platform: 'x', limit: 14, nsfw: true }))
  if (!data?.items.length) return null
  return (
    <section>
      <h2 className="text-[12px] uppercase tracking-wide text-faint mb-2">Recent finds from X</h2>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {data.items.map((p) => (
          <Link
            key={p.id}
            to={`/?post=${p.id}`}
            className="shrink-0 w-24 h-24 rounded-el overflow-hidden border border-line/60 bg-well hover:border-mute/60 transition-colors duration-fast relative"
          >
            {p.thumb_url && <img src={p.thumb_url} alt="" loading="lazy" className="w-full h-full object-cover" />}
            {p.media_type === 'video' && (
              <span className="absolute bottom-1 right-1 text-[10px] bg-ink/70 rounded px-1">▶</span>
            )}
          </Link>
        ))}
      </div>
    </section>
  )
}

// ------------------------------------------------- Grok discover (X3.3) ----
interface GrokCandidate {
  handle: string
  display_name: string | null
  reason: string
  sample: string | null
  already_monitored: boolean
}

function DiscoverTool({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [interest, setInterest] = useState('')
  const [busy, setBusy] = useState(false)
  const [candidates, setCandidates] = useState<GrokCandidate[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  const discover = async () => {
    setBusy(true)
    setError(null)
    setCandidates(null)
    try {
      const r = await api.post<{ candidates: GrokCandidate[] }>('/api/grok/discover', { interest })
      setCandidates(r.candidates)
      setDismissed(new Set())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const addOne = async (c: GrokCandidate) => {
    try {
      await api.post('/api/monitoring/accounts', {
        text: c.handle,
        added_by: 'grok',
        notes: c.reason,
      })
      toastSuccess(`Watching @${c.handle}`)
      setDismissed((d) => new Set(d).add(c.handle))
      onAdded()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  return (
    <>
      <button className="btn" onClick={() => setOpen(true)}>
        ✦ Find AI creators (Grok)
      </button>
      {open && (
        <Modal title="Find AI creators" onClose={() => setOpen(false)} wide>
          <div className="space-y-3">
            <p className="text-[12.5px] text-faint -mt-1">
              Grok searches live X for accounts producing the kind of AI media you describe. Review each
              suggestion — nothing is followed silently.
            </p>
            <div className="flex gap-2">
              <input
                className="input"
                placeholder='e.g. "cinematic AI video creators" or "Flux portrait artists"'
                value={interest}
                aria-label="Interest"
                autoFocus
                onChange={(e) => setInterest(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && interest.trim() && discover()}
              />
              <button className="btn-accent shrink-0" disabled={busy || !interest.trim()} onClick={discover}>
                {busy ? <Spinner /> : 'Search'}
              </button>
            </div>
            {error && (
              <p className="text-[12.5px] text-amber-200 bg-amber-400/10 border border-amber-400/30 rounded-el px-3 py-2">
                {error}
              </p>
            )}
            {candidates && candidates.length === 0 && (
              <p className="text-[13px] text-mute">Grok found nothing new for that — try a broader interest.</p>
            )}
            {candidates
              ?.filter((c) => !dismissed.has(c.handle))
              .map((c) => (
                <div key={c.handle} className="border border-line rounded-el p-3 flex gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <a
                        href={`https://x.com/${c.handle}`}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-[13.5px] hover:text-ember"
                      >
                        @{c.handle}
                      </a>
                      {c.display_name && <span className="text-[12px] text-faint">{c.display_name}</span>}
                      {c.already_monitored && <span className="chip !text-[10.5px]">already watching</span>}
                    </div>
                    <p className="text-[12.5px] text-mute mt-0.5">{c.reason}</p>
                    {c.sample && <p className="text-[12px] text-faint mt-1 italic line-clamp-2">“{c.sample}”</p>}
                  </div>
                  <div className="flex flex-col gap-1.5 shrink-0">
                    <button
                      className="btn-accent h-7 py-0 text-[12px]"
                      disabled={c.already_monitored}
                      onClick={() => addOne(c)}
                    >
                      ＋ Watch
                    </button>
                    <button
                      className="btn-ghost h-7 py-0 text-[12px] text-faint"
                      onClick={() => setDismissed((d) => new Set(d).add(c.handle))}
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              ))}
          </div>
        </Modal>
      )}
    </>
  )
}

// ---------------------------------------------------------------- page -----
export function MonitoringPage() {
  const { data, loading, reload } = useFetch(() => api.get<MonitoringData>('/api/monitoring'))
  const { data: collectionsData } = useFetch(listCollections)
  const [digest, setDigest] = useState<{ at: string; text: string } | null>(null)

  useEffect(() => {
    const t = window.setInterval(reload, 20_000)
    return () => window.clearInterval(t)
  }, [reload])

  useEffect(() => {
    api
      .get<{ digest: { at: string; text: string } | null }>('/api/grok/digest')
      .then((r) => setDigest(r.digest))
      .catch(() => undefined)
  }, [])

  const accounts = data?.accounts ?? []
  const collections = (collectionsData?.user_collections ?? []).map((c) => ({ id: c.id, name: c.name }))
  const allPaused = accounts.length > 0 && accounts.every((a) => !a.active)

  const bulkToggle = async (resume: boolean) => {
    try {
      await api.post(`/api/monitoring/${resume ? 'resume-all' : 'pause-all'}`)
      toastSuccess(resume ? 'Monitoring resumed' : 'Monitoring paused')
      reload()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  return (
    <div className="space-y-5 fade-in">
      <div className="flex items-center gap-2 flex-wrap">
        <div>
          <h1 className="font-display font-medium text-[19px]">Monitoring</h1>
          <p className="text-[12.5px] text-faint">
            X accounts PromptForge watches on a schedule — new media flows through the normal pipeline.
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <DiscoverTool onAdded={reload} />
          {accounts.length > 0 &&
            (allPaused ? (
              <button className="btn" onClick={() => bulkToggle(true)}>
                ▶ Resume all
              </button>
            ) : (
              <button className="btn" onClick={() => bulkToggle(false)}>
                ⏸ Pause all
              </button>
            ))}
        </div>
      </div>

      {data && !data.x_session_ok && (
        <p className="text-[12.5px] text-amber-200 bg-amber-400/10 border border-amber-400/30 rounded-el px-3 py-2">
          No X login session yet — polls will wait until you capture one.{' '}
          <Link to="/settings#x-source" className="underline underline-offset-2">
            Settings → X.com source
          </Link>{' '}
          has the two-command walkthrough.
        </p>
      )}

      {digest && (
        <details className="card p-3.5">
          <summary className="cursor-pointer text-[13px] font-medium">
            ✦ Grok digest <span className="text-faint font-normal">— {timeAgo(digest.at)}</span>
          </summary>
          <p className="text-[13px] text-mute whitespace-pre-wrap mt-2 max-w-measure">{digest.text}</p>
        </details>
      )}

      <AddBox onAdded={reload} />

      {loading && !data ? (
        <div className="flex justify-center py-12">
          <Spinner className="w-6 h-6" />
        </div>
      ) : accounts.length === 0 ? (
        <EmptyState
          icon="◉"
          title="Not watching anyone yet"
          hint="Paste a few @handles above — or let Grok suggest creators matching your taste."
        />
      ) : (
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {accounts.map((a) => (
            <AccountCard key={a.id} a={a} collections={collections} onChanged={reload} />
          ))}
        </div>
      )}

      <RecentFinds />
    </div>
  )
}
