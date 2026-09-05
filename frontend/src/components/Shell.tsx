import { ReactNode, useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { api } from '../api'
import { Toasts } from '../lib/toast'
import { StatusDot } from './Primitives'

interface IntegrationStatus {
  baserow: { status: string }
  discord: { status: string }
  llm: { status: string }
  companion?: { status: string }
}

const NAV = [
  { to: '/', label: 'Gallery', end: true },
  { to: '/collections', label: 'Collections' },
  { to: '/models', label: 'Models' },
  { to: '/inspiration', label: 'Inspiration' },
  { to: '/studio', label: 'Studio' },
  { to: '/settings', label: 'Settings' },
]

function HeaderStatus() {
  const [status, setStatus] = useState<IntegrationStatus | null>(null)
  useEffect(() => {
    let mounted = true
    const load = () =>
      api
        .get<IntegrationStatus>('/api/integrations/status')
        .then((s) => mounted && setStatus(s))
        .catch(() => undefined) // header stays quiet if endpoint unavailable
    load()
    const t = window.setInterval(load, 60_000)
    return () => {
      mounted = false
      window.clearInterval(t)
    }
  }, [])
  if (!status) return null
  const dot = (s: string) =>
    s === 'connected' ? 'ok' : s === 'error' ? 'error' : 'off'
  return (
    <div className="hidden md:flex items-center gap-3 text-[12px] text-faint" aria-label="Integration status">
      <StatusDot status={dot(status.baserow.status)} label="Baserow" />
      <StatusDot status={dot(status.discord.status)} label="Discord" />
      <StatusDot status={dot(status.llm.status)} label="AI" />
    </div>
  )
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-40 bg-ink/85 backdrop-blur border-b border-line">
        <div className="mx-auto max-w-[1700px] px-3 sm:px-5 h-12 flex items-center gap-4">
          <NavLink to="/" className="font-display font-bold text-[16px] tracking-tight shrink-0">
            Prompt<span className="text-ember">Forge</span>
          </NavLink>
          <nav className="flex items-center gap-0.5 overflow-x-auto scrollbar-none -mb-px h-full" aria-label="Main">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `px-2.5 h-full inline-flex items-center text-[13px] whitespace-nowrap border-b-2 transition-colors duration-fast ${
                    isActive
                      ? 'border-ember text-fg font-medium'
                      : 'border-transparent text-mute hover:text-fg'
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <HeaderStatus />
          </div>
        </div>
      </header>
      <main className="flex-1 mx-auto max-w-[1700px] w-full px-3 sm:px-5 py-4">{children}</main>
      <Toasts />
    </div>
  )
}
