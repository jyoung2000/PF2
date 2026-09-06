// Usage dashboard (spec §13): what actually ran, what it cost, what failed.
import { EmptyState, SkeletonGrid } from '../../components/Primitives'
import { fmtUsd, forge } from '../../lib/forge'
import { timeAgo } from '../../lib/format'
import { useFetch } from '../../lib/hooks'

export function UsagePage() {
  const { data, loading } = useFetch(() => forge.usage())
  if (loading) return <SkeletonGrid count={4} />
  if (!data) return <EmptyState title="No usage yet" icon="◇" />
  const t = data.totals
  const stats: [string, string][] = [
    ['Generations', String(t.generations)],
    ['Succeeded', String(t.succeeded)],
    ['Failed', String(t.failed)],
    ['Fallbacks used', String(t.fallbacks)],
    ['Estimated spend', fmtUsd(t.estimated_spend)],
    ['Recorded spend', fmtUsd(t.recorded_spend)],
  ]
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {stats.map(([k, v]) => (
          <div key={k} className="card !bg-well p-3">
            <div className="text-[11px] text-faint">{k}</div>
            <div className="font-display text-[20px] tabular-nums">{v}</div>
          </div>
        ))}
      </div>
      {data.models.length > 0 && (
        <div className="card p-4 overflow-x-auto">
          <h2 className="font-display font-medium text-[14.5px] mb-2">Per model × provider</h2>
          <table className="w-full text-[12px] min-w-[760px] tabular-nums">
            <thead>
              <tr className="text-left text-faint">
                {['model', 'provider', 'runs', 'success', 'avg latency', 'est cost', 'actual', 'avg score', 'score / $', 'fallbacks in'].map((h) => (
                  <th key={h} className="py-1 pr-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.models.map((m) => (
                <tr key={`${m.family}-${m.provider}`} className="border-t border-line">
                  <td className="py-1 pr-3">{m.family}</td>
                  <td className="py-1 pr-3 text-mute">{m.provider}</td>
                  <td className="py-1 pr-3">{m.attempts}</td>
                  <td className={`py-1 pr-3 ${m.success_rate != null && m.success_rate < 0.8 ? 'text-amber-300' : ''}`}>
                    {m.success_rate != null ? `${Math.round(m.success_rate * 100)}%` : '—'}
                  </td>
                  <td className="py-1 pr-3">{m.avg_latency_s != null ? `${m.avg_latency_s}s` : '—'}</td>
                  <td className="py-1 pr-3">{fmtUsd(m.est_cost)}</td>
                  <td className="py-1 pr-3">{fmtUsd(m.actual_cost)}</td>
                  <td className="py-1 pr-3">{m.avg_score ?? '—'}</td>
                  <td className="py-1 pr-3">{m.score_per_dollar ?? '—'}</td>
                  <td className="py-1 pr-3">{m.fallbacks_in || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[11.5px] text-faint mt-2">Scores come from your Lab ratings; costs are estimates where the provider reports none.</p>
        </div>
      )}
      {data.recent.length > 0 && (
        <div className="card p-4">
          <h2 className="font-display font-medium text-[14.5px] mb-2">Recent jobs</h2>
          <ul className="space-y-1 text-[12.5px]">
            {data.recent.map((r) => (
              <li key={r.id} className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full ${r.status === 'succeeded' ? 'bg-emerald-400' : r.status === 'failed' ? 'bg-red-400' : 'bg-amber-400'}`} />
                <span className="font-mono text-faint">#{r.id}</span>
                <span>{r.tool ?? 'generate'} · {r.family} · {r.provider}</span>
                {r.fallback_of && <span className="chip !text-[10.5px]">fallback of #{r.fallback_of}</span>}
                <span className="ml-auto text-faint tabular-nums">{fmtUsd(r.cost)} · {r.created_at ? timeAgo(r.created_at) : ''}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {t.generations === 0 && (
        <EmptyState title="Nothing generated yet" hint="Forge something on the Compose tab — every job lands here with its cost and outcome." icon="⚡" />
      )}
    </div>
  )
}
