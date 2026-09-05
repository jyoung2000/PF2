// Inspiration Intelligence section (I7.1): Overview (sources + queue at a
// glance), Sources (the scrapers dashboard), Creators (follow list + creator
// intelligence), Clusters, Queue, Analytics. Image-first, data-driven.
import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError, listScrapers, PostCard, ScraperInfo } from '../api'
import { DetailDrawer } from '../components/DetailDrawer'
import { EmptyState, Spinner, StatusDot } from '../components/Primitives'
import { timeAgo, timeUntil } from '../lib/format'
import { useFetch } from '../lib/hooks'
import {
  ClusterInfo,
  CreatorInfo,
  getAnalytics,
  getCluster,
  getCreator,
  getQueue,
  getTrends,
  listClusters,
  listCreators,
  listSources,
  SourceReport,
  Trends,
} from '../lib/inspiration'
import { toastError, toastSuccess } from '../lib/toast'
import { MonitoringPage } from './MonitoringPage'
import { ScrapersPage } from './ScrapersPage'

const TABS = [
  { to: '', label: 'Overview', end: true },
  { to: 'sources', label: 'Sources' },
  { to: 'creators', label: 'Creators' },
  { to: 'clusters', label: 'Clusters' },
  { to: 'queue', label: 'Queue' },
  { to: 'analytics', label: 'Analytics' },
]

function pct(v: number | null | undefined) {
  return v == null ? '—' : `${Math.round(v * 100)}%`
}

// ------------------------------------------------------------ mini grid ----
export function MiniGrid({ items, onOpen }: { items: PostCard[]; onOpen: (id: number) => void }) {
  if (!items.length) return null
  return (
    <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 gap-2">
      {items.map((p) => (
        <button
          key={p.id}
          className="group relative aspect-square rounded-el overflow-hidden border border-line bg-well hover:border-ember/60 focus:outline-none focus:ring-2 focus:ring-ember/50"
          onClick={() => onOpen(p.id)}
          title={p.prompt ?? ''}
        >
          {p.thumb_url ? <img src={p.thumb_url} alt="" className="w-full h-full object-cover" loading="lazy" /> : null}
          {p.media_type === 'video' && <span className="absolute bottom-1 right-1 chip !text-[10px] !py-0">▶</span>}
          {p.prompt && (
            <span className="absolute inset-x-0 bottom-0 bg-ink/80 text-[10.5px] text-fg/90 px-1.5 py-1 line-clamp-2 text-left opacity-0 group-hover:opacity-100 transition-opacity">
              {p.prompt}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}

function useDrawer() {
  const [open, setOpen] = useState<number | null>(null)
  const drawer = open != null ? <DetailDrawer postId={open} onClose={() => setOpen(null)} /> : null
  return { open: setOpen, drawer }
}

// -------------------------------------------------------------- overview ---
function SourceCard({ s, r, onChanged }: { s: ScraperInfo; r: SourceReport | undefined; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true)
    try {
      await fn()
      toastSuccess(msg)
      window.setTimeout(onChanged, 1200)
    } catch (e) {
      toastError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  const last = r?.last_runs?.slice(-1)[0]
  const connected =
    s.auth_kind === 'session' ? s.session_status === 'valid' : s.auth_kind === 'api_key' ? Boolean(s.key_configured) : true
  return (
    <div className={`card p-3.5 flex flex-col gap-2 ${s.enabled ? '' : 'opacity-70'}`}>
      <div className="flex items-center gap-2">
        <h3 className="font-display font-medium text-[14.5px]">{s.label}</h3>
        {s.tier === 2 && <span className="chip !text-[10px]">browser</span>}
        <span className="ml-auto">
          <StatusDot
            status={(s.status === 'needs_setup' ? 'off' : s.status === 'experimental' ? 'experimental' : s.status) as never}
            label={s.running ? 'running' : s.status === 'needs_setup' ? 'needs setup' : s.status}
          />
        </span>
      </div>
      <p className="text-[11.5px] text-faint">
        {connected ? <span className="text-emerald-300">connected</span> : <span className="text-amber-300">not connected</span>}
        {' · '}last {timeAgo(s.last_run_at)} · next {s.enabled ? timeUntil(s.next_run_at) : 'paused'}
      </p>
      <dl className="grid grid-cols-4 gap-1 text-[11.5px] tabular-nums">
        <div>
          <dt className="text-faint">discovered</dt>
          <dd>{last?.found ?? s.last_found}</dd>
        </div>
        <div>
          <dt className="text-faint">kept</dt>
          <dd className="text-emerald-300">{last?.new ?? s.last_new}</dd>
        </div>
        <div>
          <dt className="text-faint">filtered</dt>
          <dd>{last?.filtered ?? 0}</dd>
        </div>
        <div>
          <dt className="text-faint">dupes</dt>
          <dd>{last?.dupes ?? 0}</dd>
        </div>
      </dl>
      {r && r.posts > 0 && (
        <p className="text-[11.5px] text-mute tabular-nums">
          {r.posts} posts · prompts {pct(r.prompt_yield)} · metadata {pct(r.metadata_yield)} · enriched {pct(r.enrichment_yield)} · AI{' '}
          {pct(r.ai_rate)} · efficiency {r.efficiency}
        </p>
      )}
      {r?.recommendation && r.runs > 0 && <p className="text-[11.5px] text-ember-soft">{r.recommendation}</p>}
      {s.last_error && s.last_status === 'error' && <p className="text-[11.5px] text-red-300/90 break-words">{s.last_error}</p>}
      <div className="flex gap-1.5 mt-auto pt-1">
        <button
          className="btn h-7 py-0 text-[12px]"
          disabled={busy || s.status === 'needs_setup'}
          onClick={() => act(() => api.post(`/api/scrapers/${s.name}/run`), `${s.label} run started`)}
        >
          ▶ Run now
        </button>
        <button
          className="btn h-7 py-0 text-[12px]"
          disabled={busy}
          onClick={() => act(() => api.patch(`/api/scrapers/${s.name}`, { enabled: !s.enabled }), s.enabled ? `${s.label} paused` : `${s.label} resumed`)}
        >
          {s.enabled ? '⏸ Pause' : '▶ Resume'}
        </button>
      </div>
    </div>
  )
}

function OverviewTab() {
  const { data: scrapers, reload: reloadScrapers } = useFetch(listScrapers)
  const { data: sources, reload: reloadSources } = useFetch(listSources)
  const { data: analytics, reload: reloadAnalytics } = useFetch(getAnalytics)
  const reload = () => {
    reloadScrapers()
    reloadSources()
    reloadAnalytics()
  }
  useEffect(() => {
    const t = window.setInterval(reload, 20_000)
    return () => window.clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const byName = Object.fromEntries((sources?.sources ?? []).map((r) => [r.name, r]))
  const a = analytics
  const analyzed = a ? (a.by_pipeline_state.analyzed ?? 0) : 0
  const enriched = a ? (a.by_pipeline_state.enriched ?? 0) + analyzed : 0
  return (
    <div className="space-y-4">
      {a && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          {[
            ['Posts', a.posts],
            ['With prompt', a.with_prompt],
            ['With metadata', a.with_metadata],
            ['Enriched', enriched],
            ['Analyzed', analyzed],
            ['Queue', a.queue_pending],
          ].map(([k, v]) => (
            <div key={String(k)} className="card !bg-well p-3">
              <div className="text-[11px] text-faint">{k}</div>
              <div className="font-display text-[20px] tabular-nums">{v as number}</div>
            </div>
          ))}
        </div>
      )}
      {!scrapers ? (
        <div className="flex justify-center py-10">
          <Spinner className="w-6 h-6" />
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {scrapers.scrapers.map((s) => (
            <SourceCard key={s.name} s={s} r={byName[s.name]} onChanged={reload} />
          ))}
        </div>
      )}
      {a?.queue?.errors?.length ? (
        <div className="card p-3.5">
          <h3 className="font-display font-medium text-[14px] mb-1">Recent pipeline errors</h3>
          <ul className="text-[12px] text-red-300/90 space-y-0.5">
            {a.queue.errors.slice(0, 5).map((e) => (
              <li key={e.id}>
                {e.stage} · post {e.post_id} · {e.error}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

// --------------------------------------------------------------- creators --
function CreatorsTab() {
  const [sort, setSort] = useState('posts')
  const { data, loading } = useFetch(() => listCreators(sort), [sort])
  const navigate = useNavigate()
  return (
    <div className="space-y-6">
      <MonitoringPage />
      <section className="space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="font-display font-medium text-[16px]">Creator intelligence</h2>
          <span className="text-[12px] text-faint">every creator PromptForge has stored posts from — computed, not claimed</span>
          <select className="input !w-auto ml-auto" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort creators">
            {['posts', 'followers', 'engagement', 'ai_ratio', 'prompts', 'inspiration', 'recent'].map((k) => (
              <option key={k} value={k}>
                sort: {k.replace('_', ' ')}
              </option>
            ))}
          </select>
        </div>
        {loading && !data ? (
          <Spinner />
        ) : !data?.creators.length ? (
          <EmptyState title="No creators yet" hint="Creators appear as soon as posts with an author are ingested." />
        ) : (
          <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {data.creators.map((c) => (
              <button key={c.id} className="card p-3.5 text-left hover:border-ember/50" onClick={() => navigate(`/inspiration/creators/${c.id}`)}>
                <div className="flex items-center gap-2">
                  <span className="w-8 h-8 rounded-full bg-well border border-line flex items-center justify-center font-display font-semibold text-ember">
                    {c.handle[0].toUpperCase()}
                  </span>
                  <div className="min-w-0">
                    <div className="font-medium text-[13.5px] truncate">
                      @{c.handle} <span className="text-faint font-normal">· {c.platform}</span>
                    </div>
                    <div className="text-[11.5px] text-faint tabular-nums">
                      {c.stats.posts ?? 0} posts{c.followers != null && <> · {c.followers.toLocaleString()} followers</>}
                      {c.stats.trend && <> · {c.stats.trend}</>}
                    </div>
                  </div>
                </div>
                <p className="text-[11.5px] text-mute mt-2 tabular-nums">
                  avg eng {c.stats.avg_engagement ?? 0} · AI {pct(c.stats.ai_ratio)} · prompts {pct(c.stats.prompt_availability)}
                  {c.stats.models?.length ? <> · {c.stats.models.map((m) => m.family).join(', ')}</> : null}
                </p>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function CreatorDetail() {
  const { id } = useParams()
  const { data, loading } = useFetch(() => getCreator(Number(id)), [id])
  const { open, drawer } = useDrawer()
  if (loading && !data) return <Spinner />
  if (!data) return <EmptyState title="Creator not found" />
  const st = data.stats
  const traj = st.engagement_trajectory ?? []
  const max = Math.max(1, ...traj.map((t) => t.avg_engagement))
  return (
    <div className="space-y-4">
      <div className="card p-4 flex gap-4 items-start flex-wrap">
        <span className="w-14 h-14 rounded-full bg-well border border-line flex items-center justify-center font-display font-semibold text-[22px] text-ember shrink-0">
          {data.avatar_url ? <img src={data.avatar_url} alt="" className="w-full h-full rounded-full object-cover" /> : data.handle[0].toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-display font-medium text-[18px]">
            @{data.handle} {data.verified && <span className="text-emerald-300 text-[13px]">✓</span>}{' '}
            <span className="text-faint text-[13px] font-normal">· {data.platform}</span>
          </h2>
          {data.bio && <p className="text-[12.5px] text-mute max-w-measure">{data.bio}</p>}
          <p className="text-[12px] text-faint tabular-nums mt-1">
            {data.followers != null && <>{data.followers.toLocaleString()} followers · </>}
            {st.posts ?? 0} posts ({st.images ?? 0} img / {st.videos ?? 0} vid)
            {st.posts_per_week != null && <> · {st.posts_per_week}/week</>} · avg eng {st.avg_engagement ?? 0}
            {st.trend && <> · {st.trend}</>} · AI {pct(st.ai_ratio)} · prompts {pct(st.prompt_availability)} · metadata{' '}
            {pct(st.metadata_richness)} · avg inspiration {st.avg_inspiration ?? '—'}
          </p>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {(st.models ?? []).map((m) => (
              <span key={m.family} className="chip !text-fg">
                {m.family} <span className="text-faint">{m.count}</span>
              </span>
            ))}
            {(st.techniques ?? []).map((t) => (
              <span key={t.slug} className="chip !text-ember-soft border-ember/30">
                {t.slug} <span className="text-faint">{t.count}</span>
              </span>
            ))}
            {(st.styles ?? []).map((s) => (
              <span key={s.style} className="chip">
                {s.style}
              </span>
            ))}
          </div>
          {data.profile_url && (
            <a href={data.profile_url} target="_blank" rel="noreferrer" className="text-[12px] text-mute underline underline-offset-2 hover:text-ember">
              {data.profile_url}
            </a>
          )}
        </div>
        {traj.length > 1 && (
          <div className="w-full sm:w-56">
            <div className="text-[11px] text-faint mb-1">engagement trajectory</div>
            <div className="flex items-end gap-0.5 h-12">
              {traj.map((t) => (
                <span
                  key={t.week}
                  className="flex-1 bg-ember/70 rounded-sm"
                  style={{ height: `${Math.max(6, (t.avg_engagement / max) * 100)}%` }}
                  title={`${t.week}: avg ${t.avg_engagement} over ${t.posts} posts`}
                />
              ))}
            </div>
          </div>
        )}
      </div>
      {data.top_posts?.length ? (
        <section>
          <h3 className="label">Top posts</h3>
          <MiniGrid items={data.top_posts} onOpen={open} />
        </section>
      ) : null}
      {data.recent_posts?.length ? (
        <section>
          <h3 className="label">Recent posts</h3>
          <MiniGrid items={data.recent_posts} onOpen={open} />
        </section>
      ) : null}
      {drawer}
    </div>
  )
}

// --------------------------------------------------------------- clusters --
const KIND_LABEL: Record<string, string> = {
  topic: 'Topics',
  model: 'Models',
  technique: 'Techniques',
  style: 'Styles',
  palette: 'Palettes',
  subject: 'Subjects',
  creator: 'Creators',
  media: 'Media',
  prompt: 'Prompt patterns',
  camera: 'Camera',
  engagement: 'Engagement',
}

function ClustersTab() {
  const [kind, setKind] = useState<string>('')
  const { data, loading, reload } = useFetch(() => listClusters(kind || undefined), [kind])
  const navigate = useNavigate()
  const [rebuilding, setRebuilding] = useState(false)
  const rebuild = async () => {
    setRebuilding(true)
    try {
      const r = await api.post<{ clusters: number; members: number }>('/api/inspiration/clusters/rebuild')
      toastSuccess(`${r.clusters} clusters over ${r.members} memberships`)
      reload()
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setRebuilding(false)
    }
  }
  const kinds = Object.keys(KIND_LABEL)
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 flex-wrap">
        <button className={`chip ${!kind ? '!border-ember text-fg' : ''}`} onClick={() => setKind('')}>
          all
        </button>
        {kinds.map((k) => (
          <button key={k} className={`chip ${kind === k ? '!border-ember text-fg' : ''}`} onClick={() => setKind(k)}>
            {KIND_LABEL[k]}
          </button>
        ))}
        <button className="btn h-7 py-0 text-[12px] ml-auto" onClick={rebuild} disabled={rebuilding}>
          {rebuilding ? <Spinner /> : 'Rebuild now'}
        </button>
      </div>
      {loading && !data ? (
        <Spinner />
      ) : !data?.clusters.length ? (
        <EmptyState title="No clusters yet" hint="Clusters form once a few posts share a topic, model, technique or style — rebuild after a scrape." />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {data.clusters.map((c) => (
            <button key={c.id} className="card p-3.5 text-left hover:border-ember/50" onClick={() => navigate(`/inspiration/clusters/${c.id}`)}>
              <div className="flex items-center gap-2">
                <span className="chip !text-[10px]">{KIND_LABEL[c.kind] ?? c.kind}</span>
                <span className="ml-auto text-[12px] tabular-nums text-faint">{c.post_count} posts</span>
              </div>
              <div className="font-display font-medium text-[15px] mt-1.5">{c.label}</div>
              <p className="text-[11.5px] text-mute mt-1 tabular-nums">
                avg inspiration {c.data.avg_inspiration ?? '—'}
                {c.data.videos ? <> · {c.data.videos} videos</> : null}
                {c.data.models?.length ? <> · {c.data.models.map((m) => m.label).join(', ')}</> : null}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ClusterDetail() {
  const { id } = useParams()
  const [order, setOrder] = useState<'score' | 'newest'>('score')
  const [items, setItems] = useState<PostCard[]>([])
  const [cursor, setCursor] = useState<number | null>(0)
  const [cluster, setCluster] = useState<(ClusterInfo & { top_posts: PostCard[]; newest_posts: PostCard[] }) | null>(null)
  const [loading, setLoading] = useState(false)
  const { open, drawer } = useDrawer()

  const load = async (c: number, reset: boolean) => {
    setLoading(true)
    try {
      const r = await getCluster(Number(id), c, order)
      setCluster(r)
      setItems((prev) => (reset ? r.items : [...prev, ...r.items]))
      setCursor(r.next_cursor)
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    setItems([])
    load(0, true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, order])

  if (!cluster) return <Spinner />
  const d = cluster.data
  return (
    <div className="space-y-4">
      <div className="card p-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="chip !text-[10px]">{KIND_LABEL[cluster.kind] ?? cluster.kind}</span>
          <h2 className="font-display font-medium text-[18px]">{cluster.label}</h2>
          <span className="text-[12px] text-faint tabular-nums">
            {cluster.post_count} posts · avg inspiration {d.avg_inspiration ?? '—'}
          </span>
          <div className="ml-auto flex gap-1">
            {(['score', 'newest'] as const).map((o) => (
              <button key={o} className={`chip ${order === o ? '!border-ember text-fg' : ''}`} onClick={() => setOrder(o)}>
                {o === 'score' ? 'strongest' : 'newest'}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5 mt-2">
          {(d.models ?? []).map((m) => (
            <span key={m.family} className="chip !text-fg">
              {m.label} <span className="text-faint">{m.count}</span>
            </span>
          ))}
          {(d.techniques ?? []).map((t) => (
            <span key={t.slug} className="chip !text-ember-soft border-ember/30">
              {t.slug} <span className="text-faint">{t.count}</span>
            </span>
          ))}
          {(d.creators ?? []).map((c) => (
            <span key={c.handle} className="chip">
              @{c.handle} <span className="text-faint">{c.count}</span>
            </span>
          ))}
        </div>
        {d.strongest_prompts?.length ? (
          <div className="mt-3">
            <h3 className="label">Strongest prompts</h3>
            <ul className="space-y-1">
              {d.strongest_prompts.map((p) => (
                <li key={p.post_id}>
                  <button className="text-left text-[12.5px] text-mute hover:text-fg line-clamp-2" onClick={() => open(p.post_id)}>
                    <span className="text-ember tabular-nums mr-1.5">{p.score != null ? Math.round(p.score) : '—'}</span>
                    {p.prompt}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
      <MiniGrid items={items} onOpen={open} />
      {cursor != null && (
        <div className="flex justify-center">
          <button className="btn" onClick={() => load(cursor, false)} disabled={loading}>
            {loading ? <Spinner /> : 'Load more'}
          </button>
        </div>
      )}
      {drawer}
    </div>
  )
}

// ------------------------------------------------------------------ queue --
function QueueTab() {
  const { data, reload } = useFetch(getQueue)
  useEffect(() => {
    const t = window.setInterval(reload, 8000)
    return () => window.clearInterval(t)
  }, [reload])
  const act = async (path: string, msg: string) => {
    try {
      await api.post(path)
      toastSuccess(msg)
      window.setTimeout(reload, 800)
    } catch (e) {
      toastError((e as Error).message)
    }
  }
  if (!data) return <Spinner />
  const states = ['queued', 'processing', 'retryable', 'failed', 'complete', 'skipped']
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="chip">{data.pending} pending</span>
        <button className="btn h-7 py-0 text-[12px]" onClick={() => act('/api/inspiration/queue/tick?max_jobs=20', 'Processing queue')}>
          Process now
        </button>
        <button className="btn h-7 py-0 text-[12px]" onClick={() => act('/api/inspiration/queue/retry', 'Failed jobs re-queued')}>
          Retry failed
        </button>
        <button className="btn h-7 py-0 text-[12px]" onClick={() => act('/api/inspiration/queue/clear', 'Finished jobs cleared')}>
          Clear finished
        </button>
        <span className="text-[11.5px] text-faint">The scheduler drains this every minute; enrich → analysis → knowledge. Analysis waits while the AI budget is spent.</span>
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-[12.5px] tabular-nums">
          <thead className="text-faint text-[11px]">
            <tr>
              <th className="text-left px-3 py-2">stage</th>
              {states.map((st) => (
                <th key={st} className="text-right px-3 py-2">
                  {st}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.stages).map(([stage, counts]) => (
              <tr key={stage} className="border-t border-line">
                <td className="px-3 py-1.5 font-medium">{stage}</td>
                {states.map((st) => (
                  <td key={st} className={`text-right px-3 py-1.5 ${st === 'failed' && counts[st] ? 'text-red-300' : ''}`}>
                    {counts[st] ?? 0}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.errors.length > 0 && (
        <div className="card p-3.5">
          <h3 className="font-display font-medium text-[14px] mb-1">Errors</h3>
          <ul className="text-[12px] space-y-0.5">
            {data.errors.map((e) => (
              <li key={e.id} className="text-red-300/90">
                #{e.id} {e.stage} · post {e.post_id} · attempt {e.attempts} · {e.error}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// -------------------------------------------------------------- analytics --
function Bars({ rows, max }: { rows: [string, number][]; max?: number }) {
  const m = max ?? Math.max(1, ...rows.map(([, v]) => v))
  return (
    <div className="space-y-1">
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-center gap-2 text-[12px]">
          <span className="w-28 shrink-0 text-mute truncate">{k}</span>
          <span className="flex-1 h-2 rounded-full bg-well overflow-hidden">
            <span className="block h-full bg-ember/70" style={{ width: `${(v / m) * 100}%` }} />
          </span>
          <span className="w-10 text-right tabular-nums text-faint">{v}</span>
        </div>
      ))}
    </div>
  )
}

function Spark({ values }: { values: number[] }) {
  const m = Math.max(1, ...values)
  return (
    <span className="inline-flex items-end gap-px h-5 w-24 align-middle">
      {values.map((v, i) => (
        <span key={i} className="flex-1 bg-ember/70 rounded-sm" style={{ height: `${Math.max(v ? 15 : 4, (v / m) * 100)}%` }} />
      ))}
    </span>
  )
}

function AnalyticsTab() {
  const { data: a, reload } = useFetch(getAnalytics)
  const { data: t } = useFetch(() => getTrends(12))
  const [summarizing, setSummarizing] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const summarize = async () => {
    setSummarizing(true)
    setHint(null)
    try {
      await api.post('/api/inspiration/analytics/summary')
      toastSuccess('Trend brief updated')
      reload()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setHint('No AI provider configured (or the daily budget is spent) — the deterministic trends stay available.')
      else toastError((e as Error).message)
    } finally {
      setSummarizing(false)
    }
  }
  if (!a) return <Spinner />
  const trends = t as Trends | null
  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="card p-3.5">
          <h3 className="label">Inspiration score</h3>
          <Bars rows={a.inspiration_histogram.map((h) => [h.range, h.count])} />
        </div>
        <div className="card p-3.5">
          <h3 className="label">By platform</h3>
          <Bars rows={Object.entries(a.by_platform)} />
        </div>
        <div className="card p-3.5">
          <h3 className="label">AI status</h3>
          <Bars rows={Object.entries(a.by_ai_status)} />
        </div>
        <div className="card p-3.5">
          <h3 className="label">Provenance</h3>
          <Bars rows={[...Object.entries(a.prompt_sources).map(([k, v]) => [`prompt: ${k}`, v] as [string, number]), ...Object.entries(a.model_sources).map(([k, v]) => [`model: ${k}`, v] as [string, number])]} />
        </div>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-[12.5px] tabular-nums">
          <thead className="text-faint text-[11px]">
            <tr>
              {['source', 'runs', 'discovered', 'kept', 'yield', 'dupes', 'prompts', 'metadata', 'AI', 'LLM calls', 'reliability', 'efficiency', 'recommendation'].map((h) => (
                <th key={h} className="text-left px-3 py-2 whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {a.sources.map((s) => (
              <tr key={s.name} className="border-t border-line">
                <td className="px-3 py-1.5 font-medium">{s.name}</td>
                <td className="px-3 py-1.5">{s.runs}</td>
                <td className="px-3 py-1.5">{s.discovered}</td>
                <td className="px-3 py-1.5">{s.kept}</td>
                <td className="px-3 py-1.5">{pct(s.discovery_yield)}</td>
                <td className="px-3 py-1.5">{pct(s.duplicate_rate)}</td>
                <td className="px-3 py-1.5">{pct(s.prompt_yield)}</td>
                <td className="px-3 py-1.5">{pct(s.metadata_yield)}</td>
                <td className="px-3 py-1.5">{pct(s.ai_rate)}</td>
                <td className="px-3 py-1.5">{s.llm_calls ?? 0}</td>
                <td className="px-3 py-1.5">{pct(s.reliability)}</td>
                <td className="px-3 py-1.5 text-ember">{s.efficiency}</td>
                <td className="px-3 py-1.5 text-mute whitespace-nowrap">{s.recommendation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card p-3.5 space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="font-display font-medium text-[14.5px]">Trends</h3>
          <span className="text-[11.5px] text-faint">weekly counts over the last {trends?.weeks.length ?? 12} weeks · deterministic</span>
          <button className="btn h-7 py-0 text-[12px] ml-auto" onClick={summarize} disabled={summarizing}>
            {summarizing ? <Spinner /> : 'Summarize with AI'}
          </button>
        </div>
        {hint && <p className="text-[12px] text-amber-200">{hint}</p>}
        {a.summary && (
          <p className="text-[13px] text-mute bg-well border border-line rounded-el p-3 max-w-measure">
            {a.summary.text} <span className="text-faint text-[11px]">— {timeAgo(a.summary.at)}, grounded in the numbers below</span>
          </p>
        )}
        {trends && (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(['models', 'techniques', 'styles', 'topics', 'creators', 'formats'] as const).map((kind) => (
              <div key={kind}>
                <h4 className="text-[11px] text-faint uppercase tracking-wide mb-1">{kind}</h4>
                {Object.keys(trends.series[kind] ?? {}).length === 0 ? (
                  <p className="text-[12px] text-faint">nothing yet</p>
                ) : (
                  <ul className="space-y-0.5">
                    {Object.entries(trends.series[kind]).map(([key, vals]) => (
                      <li key={key} className="flex items-center gap-2 text-[12px]">
                        <span className="w-28 truncate text-mute" title={key}>
                          {key}
                        </span>
                        <Spark values={vals} />
                        <span className="tabular-nums text-faint">{vals.reduce((x, y) => x + y, 0)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
        {trends?.rising.length ? (
          <div>
            <h4 className="text-[11px] text-faint uppercase tracking-wide mb-1">Rising</h4>
            <div className="flex flex-wrap gap-1.5">
              {trends.rising.map((r) => (
                <span key={`${r.kind}-${r.key}`} className="chip">
                  {r.key} <span className="text-faint">{r.kind}</span> <span className="text-emerald-300">×{r.ratio}</span>
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------- page ---
export function InspirationPage() {
  return (
    <div className="space-y-4 fade-in">
      <div className="flex items-end gap-4 flex-wrap">
        <div>
          <h1 className="font-display font-medium text-[19px]">Inspiration</h1>
          <p className="text-[12.5px] text-faint">Discover → verify → enrich → score → cluster → learn. Evidence-driven, never just “more posts”.</p>
        </div>
        <nav className="flex items-center gap-0.5 ml-auto overflow-x-auto scrollbar-none" aria-label="Inspiration sections">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                `px-2.5 py-1.5 text-[13px] rounded-el whitespace-nowrap ${isActive ? 'bg-well text-fg font-medium' : 'text-mute hover:text-fg'}`
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <Routes>
        <Route path="/" element={<OverviewTab />} />
        <Route path="/sources" element={<ScrapersPage />} />
        <Route path="/creators" element={<CreatorsTab />} />
        <Route path="/creators/:id" element={<CreatorDetail />} />
        <Route path="/clusters" element={<ClustersTab />} />
        <Route path="/clusters/:id" element={<ClusterDetail />} />
        <Route path="/queue" element={<QueueTab />} />
        <Route path="/analytics" element={<AnalyticsTab />} />
      </Routes>
    </div>
  )
}

export type { CreatorInfo }
