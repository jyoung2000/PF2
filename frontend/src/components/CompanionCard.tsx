// Settings → Companion (9.4): download → run → pair. Pairing code with
// countdown, paired-device list with revoke, live online status + detected
// Ollama models, queued-job count, cloud-fallback toggle.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { timeAgo } from '../lib/format'
import { useFetch } from '../lib/hooks'
import { SettingsMap } from '../lib/settings'
import { toastError, toastSuccess } from '../lib/toast'
import { ConnBadge, Section, ToggleSetting } from './SettingsKit'
import { ConfirmModal, Spinner } from './Primitives'

interface CompanionStatus {
  companions: { id: number; name: string; created_at: string | null; last_seen: string | null }[]
  online: boolean
  name: string | null
  models: string[]
  queued_jobs: number
}

export function CompanionCard({
  settings,
  save,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
}) {
  const { data, reload } = useFetch(() => api.get<CompanionStatus>('/api/companion'))
  const [code, setCode] = useState<{ code: string; expires_in_s: number } | null>(null)
  const [countdown, setCountdown] = useState(0)
  const [revoking, setRevoking] = useState<{ id: number; name: string } | null>(null)

  useEffect(() => {
    const t = window.setInterval(reload, 10_000)
    return () => window.clearInterval(t)
  }, [reload])

  useEffect(() => {
    if (!code) return
    setCountdown(code.expires_in_s)
    const t = window.setInterval(() => setCountdown((c) => Math.max(0, c - 1)), 1000)
    return () => window.clearInterval(t)
  }, [code])

  const issueCode = async () => {
    try {
      setCode(await api.post<{ code: string; expires_in_s: number }>('/api/companion/pairing-code'))
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const revoke = async (id: number) => {
    try {
      await api.delete(`/api/companion/${id}`)
      toastSuccess('Companion revoked — its connection was closed')
      reload()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  return (
    <Section
      title="Companion — desktop GPU bridge"
      hint="Your Unraid box stays light: the companion app runs on your PC, connects outbound to this server (no port forwarding, works over LAN/Tailscale) and lends its Ollama to the knowledge engine for free analysis. It proxies Ollama only — nothing else."
      id="companion"
    >
      <div className="flex items-center gap-2 flex-wrap -mt-1">
        <ConnBadge status={data?.online ? 'connected' : data?.companions.length ? 'offline' : 'not_configured'} />
        {data?.online && data.name && <span className="chip">{data.name}</span>}
        {data && data.queued_jobs > 0 && (
          <span className="chip text-amber-300 border-amber-400/40">
            {data.queued_jobs} analysis job{data.queued_jobs === 1 ? '' : 's'} queued — drain on reconnect
          </span>
        )}
        {data?.online && data.models.length > 0 && (
          <span className="text-[11.5px] text-faint">
            Ollama models: {data.models.slice(0, 4).join(', ')}
            {data.models.length > 4 && ` +${data.models.length - 4}`}
          </span>
        )}
      </div>

      <ol className="text-[13px] space-y-2.5 list-none">
        <li className="flex items-start gap-2">
          <span className="w-5 h-5 rounded-full bg-well border border-line text-[11px] flex items-center justify-center text-mute shrink-0 mt-0.5">1</span>
          <span>
            <a href="/api/companion/download" className="btn-accent mr-2">
              ⬇ Download companion
            </a>
            <span className="text-mute">
              source zip — run <span className="font-mono text-[12px]">python app.py</span>, or build the
              Windows .exe with the included <span className="font-mono text-[12px]">build_companion.ps1</span>
            </span>
          </span>
        </li>
        <li className="flex items-start gap-2">
          <span className="w-5 h-5 rounded-full bg-well border border-line text-[11px] flex items-center justify-center text-mute shrink-0 mt-0.5">2</span>
          <span className="flex items-center gap-2 flex-wrap">
            <button className="btn" onClick={issueCode}>
              {code ? 'New pairing code' : 'Generate pairing code'}
            </button>
            {code && countdown > 0 && (
              <>
                <span className="font-mono text-[20px] tracking-[0.3em] text-ember">{code.code}</span>
                <span className="text-[11.5px] text-faint tabular-nums">expires in {countdown}s · single use</span>
              </>
            )}
            {code && countdown === 0 && <span className="text-[12px] text-amber-300">Code expired — generate a fresh one.</span>}
          </span>
        </li>
        <li className="flex items-start gap-2">
          <span className="w-5 h-5 rounded-full bg-well border border-line text-[11px] flex items-center justify-center text-mute shrink-0 mt-0.5">3</span>
          <span className="text-mute">
            On your PC:{' '}
            <span className="font-mono text-[12px] text-fg">
              python app.py --server http://{window.location.host} --code {code?.code ?? '123456'}
            </span>{' '}
            — then pick “Companion (desktop GPU)” as the AI provider above.
          </span>
        </li>
      </ol>

      {data && data.companions.length > 0 && (
        <div className="border border-line rounded-el divide-y divide-line">
          {data.companions.map((c) => (
            <div key={c.id} className="px-3 py-2 flex items-center gap-2 text-[12.5px]">
              <span className="font-medium">{c.name}</span>
              <span className="text-faint">
                paired {timeAgo(c.created_at)} · last seen {timeAgo(c.last_seen)}
              </span>
              <button className="btn-danger h-6 py-0 text-[11.5px] ml-auto" onClick={() => setRevoking({ id: c.id, name: c.name })}>
                Revoke
              </button>
            </div>
          ))}
        </div>
      )}
      {!data && <Spinner />}

      <ToggleSetting
        settings={settings}
        k="llm_cloud_fallback"
        save={save}
        label="Fall back to the cloud LLM when the companion is offline (needs Anthropic/OpenAI configured)"
      />
      {revoking && (
        <ConfirmModal
          title={`Revoke “${revoking.name}”?`}
          message="Its token stops working immediately and any live connection is closed. Re-pair with a fresh code to reconnect."
          confirmLabel="Revoke"
          onConfirm={() => revoke(revoking.id)}
          onClose={() => setRevoking(null)}
        />
      )}
    </Section>
  )
}
