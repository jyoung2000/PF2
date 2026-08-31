import { useEffect, useRef, useState } from 'react'
import { api, listScrapers, ScraperInfo } from '../api'
import { Spinner, StatusDot } from '../components/Primitives'
import { timeAgo, timeUntil } from '../lib/format'
import { useFetch } from '../lib/hooks'
import { toastError, toastSuccess } from '../lib/toast'

interface LogEvent {
  ts: number
  source: string
  level: 'info' | 'warn' | 'error'
  message: string
}

function LogPanel() {
  const [events, setEvents] = useState<LogEvent[]>([])
  const [connected, setConnected] = useState(false)
  const boxRef = useRef<HTMLDivElement | null>(null)
  const stick = useRef(true)

  useEffect(() => {
    let ws: WebSocket | null = null
    let closed = false
    let retry: number | undefined
    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${window.location.host}/api/ws/logs`)
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retry = window.setTimeout(connect, 2500)
      }
      ws.onmessage = (m) => {
        try {
          const data = JSON.parse(m.data)
          if (data.type === 'history') setEvents(data.events)
          else if (data.type === 'event') setEvents((prev) => [...prev.slice(-499), data.event])
        } catch {
          /* ignore malformed frames */
        }
      }
    }
    connect()
    return () => {
      closed = true
      if (retry) window.clearTimeout(retry)
      ws?.close()
    }
  }, [])

  useEffect(() => {
    if (stick.current && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
  }, [events])

  return (
    <section className="card overflow-hidden">
      <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-line">
        <h2 className="font-display font-medium text-[14px]">Live log</h2>
        <StatusDot status={connected ? 'ok' : 'off'} label={connected ? 'streaming' : 'reconnecting…'} />
      </div>
      <div
        ref={boxRef}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        }}
        className="h-64 overflow-y-auto px-3.5 py-2 font-mono text-[11.5px] leading-[1.7] bg-ink"
      >
        {events.length === 0 && <p className="text-faint">Waiting for activity — run a scraper to see it live.</p>}
        {events.map((e, i) => (
          <div key={i} className="whitespace-pre-wrap break-all">
            <span className="text-faint">{new Date(e.ts * 1000).toLocaleTimeString()} </span>
            <span className={e.level === 'error' ? 'text-red-300' : e.level === 'warn' ? 'text-amber-300' : 'text-mute'}>
              [{e.source}]
            </span>{' '}
            <span className={e.level === 'error' ? 'text-red-200' : 'text-fg/90'}>{e.message}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

function ScraperCard({ s, onChanged }: { s: ScraperInfo; onChanged: () => void }) {
  const [running, setRunning] = useState(false)
  const [interval, setIntervalMin] = useState(s.interval_minutes)

  const runNow = async () => {
    setRunning(true)
    try {
      await api.post(`/api/scrapers/${s.name}/run`)
      toastSuccess(`${s.label} run started — watch the live log`)
      window.setTimeout(onChanged, 1500)
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      window.setTimeout(() => setRunning(false), 1200)
    }
  }

  const toggle = async () => {
    try {
      await api.patch(`/api/scrapers/${s.name}`, { enabled: !s.enabled })
      onChanged()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const saveInterval = async () => {
    if (interval === s.interval_minutes) return
    try {
      await api.patch(`/api/scrapers/${s.name}`, { interval_minutes: interval })
      toastSuccess(`${s.label}: every ${Math.max(interval, s.min_interval_minutes)} min`)
      onChanged()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const statusLabel =
    s.status === 'ok' ? 'OK' : s.status === 'needs_setup' ? 'Needs setup' : s.status === 'experimental' ? 'Experimental' : 'Error'

  return (
    <div className="card p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="font-display font-medium text-[15px]">{s.label}</h3>
          {s.tier === 2 && <span className="chip !text-[10.5px]">browser</span>}
          {s.experimental && <span className="chip !text-[10.5px] text-amber-300 border-amber-400/40">experimental</span>}
        </div>
        <StatusDot
          status={s.status === 'needs_setup' ? 'off' : s.status === 'experimental' ? 'experimental' : s.status}
          label={statusLabel}
        />
      </div>

      {s.status_detail && <p className="text-[12px] text-mute -mt-1.5">{s.status_detail}</p>}
      {s.session_status && s.session_status !== 'unknown' && (
        <p className="text-[12px] -mt-1.5">
          <span className="text-faint">Login session: </span>
          <span className={s.session_status === 'valid' ? 'text-emerald-300' : 'text-amber-300'}>
            {s.session_status}
          </span>
        </p>
      )}

      <dl className="grid grid-cols-3 gap-2 text-[12px]">
        <div>
          <dt className="text-faint">Last run</dt>
          <dd className="tabular-nums">{timeAgo(s.last_run_at)}</dd>
        </div>
        <div>
          <dt className="text-faint">Found / new</dt>
          <dd className="tabular-nums">
            {s.last_found} / {s.last_new}
          </dd>
        </div>
        <div>
          <dt className="text-faint">Next run</dt>
          <dd className="tabular-nums">{s.enabled ? timeUntil(s.next_run_at) : 'paused'}</dd>
        </div>
      </dl>
      {s.last_error && <p className="text-[12px] text-red-300 break-all">Last error: {s.last_error}</p>}

      <div className="flex items-center gap-2 mt-auto pt-1">
        <button
          role="switch"
          aria-checked={s.enabled}
          aria-label={`${s.label} enabled`}
          onClick={toggle}
          className={`shrink-0 relative w-9 h-5 rounded-full transition-colors duration-fast ${s.enabled ? 'bg-ember' : 'bg-well border border-line'}`}
        >
          <span
            className={`absolute left-0 top-0.5 w-4 h-4 rounded-full bg-fg transition-transform duration-fast ${s.enabled ? 'translate-x-4' : 'translate-x-0.5'}`}
          />
        </button>
        <label className="flex items-center gap-1 text-[12px] text-mute">
          every
          <input
            type="number"
            min={s.min_interval_minutes}
            aria-label={`${s.label} interval minutes`}
            className="input !w-16 h-7 text-[12px] tabular-nums"
            value={interval}
            onChange={(e) => setIntervalMin(Number(e.target.value))}
            onBlur={saveInterval}
            onKeyDown={(e) => e.key === 'Enter' && saveInterval()}
          />
          min
        </label>
        <button className="btn ml-auto" onClick={runNow} disabled={running || s.status === 'needs_setup'}>
          {running ? <Spinner /> : '▶ Run now'}
        </button>
      </div>
    </div>
  )
}

export function ScrapersPage() {
  const { data, loading, reload } = useFetch(listScrapers)
  useEffect(() => {
    const t = window.setInterval(reload, 20_000)
    return () => window.clearInterval(t)
  }, [reload])

  return (
    <div className="space-y-4 fade-in">
      <div>
        <h1 className="font-display font-medium text-[19px]">Scrapers</h1>
        <p className="text-[12.5px] text-faint">
          One site runs at a time; adapters fail independently and never take the app down.
        </p>
      </div>
      {loading && !data ? (
        <div className="flex justify-center py-16">
          <Spinner className="w-6 h-6" />
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {data?.scrapers.map((s) => <ScraperCard key={s.name} s={s} onChanged={reload} />)}
        </div>
      )}
      <LogPanel />
    </div>
  )
}
