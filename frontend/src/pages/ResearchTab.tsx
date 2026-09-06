// Research (Inspiration 2.0, I13/I15): ask a question, watch PF2 route it to
// the sources that can actually answer it, and see WHY each result is there.
//
// Two things this screen must always be honest about (§190):
//   - it never needs an AI provider, and never needs Grok or X;
//   - a source that could not answer says so, with the reason, instead of
//     quietly shrinking the result set.
import { useCallback, useEffect, useRef, useState } from 'react'
import { PostCard } from '../api'
import { EmptyState, Spinner } from '../components/Primitives'
import { timeAgo } from '../lib/format'
import { useFetch } from '../lib/hooks'
import {
  controlResearch,
  getDiscoveryStatus,
  getResearch,
  listResearch,
  researchExportUrl,
  ResearchJob,
  researchPresets,
  startResearch,
} from '../lib/inspiration'
import { toastError, toastSuccess } from '../lib/toast'

const LIVE_STATES = new Set(['queued', 'running'])
const STATE_STYLE: Record<string, string> = {
  completed: 'text-emerald-300',
  partial: 'text-amber-300',
  running: 'text-ember',
  queued: 'text-mute',
  paused: 'text-mute',
  cancelled: 'text-faint',
  failed: 'text-rose-300',
}

export function SourceSelector({
  available,
  chosen,
  onChange,
}: {
  available: string[]
  chosen: string[]
  onChange: (next: string[]) => void
}) {
  if (!available.length) return null
  const toggle = (name: string) =>
    onChange(chosen.includes(name) ? chosen.filter((n) => n !== name) : [...chosen, name])
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <button
        className={`chip ${chosen.length === 0 ? '!text-fg border-ember/40' : ''}`}
        onClick={() => onChange([])}
        type="button"
      >
        auto-route
      </button>
      {available.map((name) => (
        <button
          key={name}
          type="button"
          className={`chip ${chosen.includes(name) ? '!text-fg border-ember/40' : ''}`}
          onClick={() => toggle(name)}
        >
          {name}
        </button>
      ))}
    </div>
  )
}

function Progress({ job }: { job: ResearchJob }) {
  const rows = Object.entries(job.progress ?? {})
  if (!rows.length) return null
  return (
    <ul className="flex flex-wrap gap-1.5 text-[11.5px]">
      {rows.map(([source, p]) => (
        <li
          key={source}
          className={`chip ${p.state === 'failed' || p.state === 'skipped' ? 'text-amber-300' : p.state === 'done' ? '!text-fg' : 'text-mute'}`}
          title={p.reason ?? ''}
        >
          {source}
          {p.state === 'done' ? (
            <span className="text-faint"> {p.kept ?? 0}/{p.found ?? 0}</span>
          ) : (
            <span className="text-faint"> {p.state}</span>
          )}
        </li>
      ))}
    </ul>
  )
}

function Results({ job, onOpen }: { job: ResearchJob; onOpen: (id: number) => void }) {
  const items = job.items ?? []
  if (!items.length) return null
  return (
    <ul className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
      {items.map((item: PostCard & { why?: string[]; relevance?: number }) => (
        <li key={item.id} className="card p-2.5 flex gap-2.5">
          <button
            className="w-16 h-16 shrink-0 rounded-el overflow-hidden border border-line bg-well"
            onClick={() => onOpen(item.id)}
          >
            {item.thumb_url ? <img src={item.thumb_url} alt="" className="w-full h-full object-cover" loading="lazy" /> : null}
          </button>
          <div className="min-w-0 text-[12px]">
            <div className="flex items-center gap-1.5">
              <span className="chip">{item.platform}</span>
              {item.relevance != null && <span className="chip">{Math.round(item.relevance * 100)}%</span>}
            </div>
            {item.prompt && <p className="text-mute line-clamp-2 mt-0.5">{item.prompt}</p>}
            {item.why?.length ? <p className="text-faint truncate mt-0.5">{item.why.join(' · ')}</p> : null}
          </div>
        </li>
      ))}
    </ul>
  )
}

function JobCard({ job, onOpen, onChanged }: { job: ResearchJob; onOpen: (id: number) => void; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const act = async (action: 'pause' | 'resume' | 'cancel' | 'rerun' | 'refresh') => {
    setBusy(true)
    try {
      await controlResearch(job.id, action)
      onChanged()
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const intent = job.params?.intent
  const routing = job.params?.routing ?? []
  return (
    <section className="card p-3.5 space-y-2">
      <div className="flex items-start gap-2 flex-wrap">
        <div className="min-w-0">
          <h3 className="font-display font-medium text-[15px]">{job.label || job.query}</h3>
          <p className="text-[12px] text-faint">
            <span className={STATE_STYLE[job.status] ?? 'text-mute'}>{job.status}</span>
            {job.created_at && <> · started {timeAgo(job.created_at)}</>}
            {job.result_post_ids.length > 0 && <> · {job.result_post_ids.length} results</>}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-1.5 text-[12px]">
          {LIVE_STATES.has(job.status) && (
            <button className="btn-ghost !py-1 !px-2" disabled={busy} onClick={() => act('pause')}>
              Pause
            </button>
          )}
          {job.status === 'paused' && (
            <button className="btn-ghost !py-1 !px-2" disabled={busy} onClick={() => act('resume')}>
              Resume
            </button>
          )}
          <button className="btn-ghost !py-1 !px-2" disabled={busy} onClick={() => act('refresh')}>
            Refresh
          </button>
          <button className="btn-ghost !py-1 !px-2" disabled={busy} onClick={() => act('rerun')}>
            Run again
          </button>
          {job.result_post_ids.length > 0 &&
            (['json', 'csv', 'md'] as const).map((fmt) => (
              <a key={fmt} className="text-mute hover:text-ember" href={researchExportUrl(job.id, fmt)} download>
                {fmt}
              </a>
            ))}
        </div>
      </div>

      {intent && (
        <p className="text-[11.5px] text-faint">
          read as:{' '}
          {[
            intent.media_type,
            intent.wants_prompt ? 'wants published prompts' : null,
            intent.wants_workflow ? 'wants workflows' : null,
            intent.models?.length ? `models: ${intent.models.join(', ')}` : null,
            intent.techniques?.length ? `techniques: ${intent.techniques.join(', ')}` : null,
            intent.rank ? `ranked by ${intent.rank}` : null,
          ]
            .filter(Boolean)
            .join(' · ') || 'a general search'}
        </p>
      )}
      {routing.length > 0 && (
        <p className="text-[11.5px] text-faint">
          routed to {routing.map((r) => `${r.source} (${r.why})`).join(', ')}
        </p>
      )}
      {job.warning && <p className="text-[12px] text-amber-300">{job.warning}</p>}
      {job.error && <p className="text-[12px] text-rose-300">{job.error}</p>}
      <Progress job={job} />
      <Results job={job} onOpen={onOpen} />
    </section>
  )
}

export function ResearchTab({ onOpen }: { onOpen: (id: number) => void }) {
  const [query, setQuery] = useState('')
  const [sources, setSources] = useState<string[]>([])
  const [starting, setStarting] = useState(false)
  const [active, setActive] = useState<ResearchJob | null>(null)
  const { data: presets } = useFetch(researchPresets, [])
  const { data: status } = useFetch(getDiscoveryStatus, [])
  const { data: jobs, reload } = useFetch(() => listResearch(10), [])
  const poll = useRef<number | null>(null)

  // live progress: poll only while something is actually running
  const watch = useCallback(
    (id: number) => {
      if (poll.current) window.clearInterval(poll.current)
      poll.current = window.setInterval(async () => {
        try {
          const fresh = await getResearch(id)
          setActive(fresh)
          if (!LIVE_STATES.has(fresh.status)) {
            if (poll.current) window.clearInterval(poll.current)
            poll.current = null
            reload()
          }
        } catch {
          if (poll.current) window.clearInterval(poll.current)
          poll.current = null
        }
      }, 2000)
    },
    [reload],
  )
  useEffect(() => () => void (poll.current && window.clearInterval(poll.current)), [])

  const run = async (body: { query?: string; preset?: string }) => {
    setStarting(true)
    try {
      const job = await startResearch({ ...body, sources: sources.length ? sources : null })
      setActive(job)
      toastSuccess(job.warning ? 'Job created' : 'Research started')
      if (LIVE_STATES.has(job.status)) watch(job.id)
      reload()
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setStarting(false)
    }
  }

  const available = status?.searchable_sources ?? []
  return (
    <div className="space-y-4">
      <form
        className="card p-3.5 space-y-2.5"
        onSubmit={(e) => {
          e.preventDefault()
          if (query.trim()) run({ query: query.trim() })
        }}
      >
        <div className="flex gap-2">
          <input
            className="input flex-1"
            placeholder="What do you want to find? e.g. “kling camera movement prompts with workflows”"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="btn-accent whitespace-nowrap" disabled={starting || !query.trim()}>
            {starting ? 'Starting…' : 'Research'}
          </button>
        </div>
        <SourceSelector available={available} chosen={sources} onChange={setSources} />
        <div className="flex flex-wrap gap-1.5">
          {(presets?.presets ?? []).map((p) => (
            <button
              key={p.key}
              type="button"
              className="chip hover:!text-fg"
              disabled={starting}
              onClick={() => run({ preset: p.key })}
            >
              {p.label}
            </button>
          ))}
        </div>
        {status && (
          <p className="text-[11.5px] text-faint">
            {status.detail}
            {!status.requires_grok && <> Grok and X are optional — nothing here depends on them.</>}
          </p>
        )}
      </form>

      {active && <JobCard job={active} onOpen={onOpen} onChanged={reload} />}

      {!jobs ? (
        <Spinner />
      ) : jobs.jobs.length === 0 ? (
        <EmptyState title="No research yet" hint="Ask a question above, or start from a preset." />
      ) : (
        <section className="space-y-2">
          <h3 className="label">Recent research</h3>
          {jobs.jobs
            .filter((j) => j.id !== active?.id)
            .map((j) => (
              <JobCard key={j.id} job={j} onOpen={onOpen} onChanged={reload} />
            ))}
        </section>
      )}
    </div>
  )
}
