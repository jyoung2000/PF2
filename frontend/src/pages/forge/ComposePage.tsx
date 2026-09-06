// Compose (spec §3–§4, §14): the primary flow. A big idea box, explainable
// model choices, the compiled package, generation with live status.
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api'
import { Spinner } from '../../components/Primitives'
import { forge, fmtUsd, JobStatus, PromptPackage, RouteCandidate, RouteResult } from '../../lib/forge'
import { toastError, toastSuccess } from '../../lib/toast'

function IntentChips({ intent }: { intent: RouteResult['intent'] }) {
  const entries: [string, string][] = []
  const push = (k: string, v: unknown) => v != null && v !== false && entries.push([k, String(v)])
  push('modality', intent.modality)
  push('duration', intent.duration_s ? `${intent.duration_s}s` : null)
  push('aspect', intent.aspect_ratio)
  push('styles', Array.isArray(intent.styles) ? (intent.styles as string[]).join(', ') : null)
  push('consistency', intent.character_consistency ? 'character' : null)
  push('budget', intent.budget_cap_usd ? `≤$${intent.budget_cap_usd}` : intent.budget_sensitive ? 'sensitive' : null)
  push('avoid', Array.isArray(intent.avoid) ? (intent.avoid as string[]).join(', ') : null)
  const evidence = (intent.evidence ?? {}) as Record<string, unknown>
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([k, v]) => (
        <span key={k} className="chip" title={evidence[k === 'aspect' ? 'aspect_ratio' : k === 'duration' ? 'duration_s' : k] ? `evidence: ${JSON.stringify(evidence[k === 'aspect' ? 'aspect_ratio' : k === 'duration' ? 'duration_s' : k])}` : 'inferred'}>
          <span className="text-faint">{k}</span> {v}
        </span>
      ))}
    </div>
  )
}

function CandidateCard({ c, selected, onPick }: { c: RouteCandidate; selected: boolean; onPick: () => void }) {
  return (
    <button
      className={`card p-3 w-full text-left transition-colors duration-fast ${selected ? 'border-ember' : 'hover:border-mute/50'}`}
      onClick={onPick}
    >
      <div className="flex items-center gap-2">
        <h3 className="font-display font-medium text-[14px]">{c.display_name ?? c.family}</h3>
        <span className="chip !text-[10.5px]">{c.provider}</span>
        <span className="ml-auto font-display text-[14px] tabular-nums text-ember">{Math.round(c.total * 100)}</span>
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11.5px]">
        {c.connected ? (
          <span className="text-emerald-300">connected</span>
        ) : (
          <span className="text-amber-300">not connected</span>
        )}
        <span className="text-faint tabular-nums">{fmtUsd(c.estimate)}</span>
        <span className="text-faint">{c.basis === 'history' ? `${c.history.successes}/${c.history.attempts} here` : 'priors'}</span>
      </div>
      <ul className="mt-1.5 space-y-0.5 text-[11.5px] text-mute">
        {c.reasons.slice(0, 3).map((r, i) => (
          <li key={i}>· {r}</li>
        ))}
      </ul>
      {c.unsupported_constraints.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-[11.5px] text-amber-300">
          {c.unsupported_constraints.map((u, i) => (
            <li key={i}>⚠ {u}</li>
          ))}
        </ul>
      )}
      {c.provenance && (
        <p className="mt-1 text-[11px] text-faint" title={c.provenance.evidence ?? ''}>
          model facts: {Math.round((c.provenance.confidence ?? 0) * 100)}% confidence
          {c.provenance.source_urls.length > 0 ? ' · sourced' : ' · unverified seed'}
          {c.provenance.last_verified ? ` · ${c.provenance.last_verified}` : ''}
        </p>
      )}
    </button>
  )
}

export function ComposePage() {
  const [idea, setIdea] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [route, setRoute] = useState<RouteResult | null>(null)
  const [pkg, setPkg] = useState<PromptPackage | null>(null)
  const [job, setJob] = useState<JobStatus | null>(null)
  const [allowFallback, setAllowFallback] = useState(false)
  const poller = useRef<number | null>(null)

  useEffect(() => () => { if (poller.current) window.clearInterval(poller.current) }, [])

  const doForge = async () => {
    setBusy('forge')
    setJob(null)
    try {
      const r = await forge.route({ brief: idea })
      setRoute(r)
      if (r.recommended) {
        setPkg(await forge.compile({ idea, family: r.recommended.family, provider: r.recommended.provider }))
      } else {
        setPkg(null)
        if (r.unsupported) toastError(r.unsupported)
      }
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const pick = async (c: RouteCandidate) => {
    if (!pkg && !idea.trim()) return
    setBusy('compile')
    try {
      setPkg(await forge.compile(pkg ? { package: pkg, family: c.family, provider: c.provider } : { idea, family: c.family, provider: c.provider }))
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const polish = async () => {
    if (!pkg) return
    setBusy('polish')
    try {
      const next = await forge.compile({ package: pkg, family: pkg.family, provider: pkg.provider, use_llm: true })
      setPkg(next)
      if (next.llm_polish && !next.llm_polish.applied) toastError(`LLM polish unavailable: ${next.llm_polish.reason}`)
      else toastSuccess('Polished with the knowledge engine')
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const generate = async () => {
    if (!pkg) return
    setBusy('generate')
    try {
      const tool = pkg.kind === 'video' ? 'generate_video' : 'generate_image'
      const r = await forge.invokeTool(tool, {
        prompt: pkg.optimized_prompt,
        negative: pkg.negative_prompt ?? undefined,
        family: pkg.family,
        provider: pkg.provider,
        params: pkg.params,
        allow_fallback: allowFallback,
      })
      const first = await forge.job(r.job_id)
      setJob(first)
      poller.current = window.setInterval(async () => {
        const j = await forge.job(r.job_id).catch(() => null)
        if (j) setJob(j)
        if (j && ['succeeded', 'failed'].includes(j.status)) {
          if (poller.current) window.clearInterval(poller.current)
        }
      }, 2500)
    } catch (e) {
      if (e instanceof ApiError) toastError(e.message)
      else toastError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const sendToLab = async () => {
    if (!pkg) return
    try {
      const exp = await forge.createExperiment(idea.slice(0, 60) || 'Forge experiment', idea)
      await forge.addVariant(exp.id, { package: pkg, label: `${pkg.display_name} compile` })
      toastSuccess('Sent to the Lab — compare it against other models there')
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const savePrompt = async () => {
    if (!pkg) return
    try {
      await api.post('/api/studio/prompts', {
        text: pkg.optimized_prompt, negative: pkg.negative_prompt || undefined,
        model_family: pkg.family, origin: 'manual',
      })
      toastSuccess('Saved to Studio → Saved prompts')
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      <div className="card p-4 space-y-3">
        <textarea
          className="input min-h-[96px] text-[14.5px]"
          placeholder="Describe what you want — “a cinematic 15-second 9:16 sci-fi trailer with the same character across shots”, “a poster with the title ‘NIGHT SHIFT’, art deco, no red”…"
          value={idea}
          aria-label="Your idea"
          onChange={(e) => setIdea(e.target.value)}
        />
        <div className="flex items-center gap-2 flex-wrap">
          {route && <IntentChips intent={route.intent} />}
          <button className="btn-accent ml-auto" disabled={!idea.trim() || busy !== null} onClick={doForge}>
            {busy === 'forge' ? <Spinner /> : '⚒ Forge'}
          </button>
        </div>
      </div>

      {route && (
        <div className="grid lg:grid-cols-[340px_1fr] gap-4 items-start">
          <aside className="space-y-2">
            <h2 className="label !mb-0">Ranked models — every pick explained</h2>
            {route.candidates.map((c) => (
              <CandidateCard
                key={`${c.family}-${c.provider}`}
                c={c}
                selected={pkg?.family === c.family && pkg?.provider === c.provider}
                onPick={() => pick(c)}
              />
            ))}
            {route.candidates.length === 0 && (
              <p className="card p-4 text-[12.5px] text-faint">{route.unsupported ?? 'No candidates.'}</p>
            )}
          </aside>

          <main className="space-y-3 min-w-0">
            {busy === 'compile' && <div className="card p-6 flex justify-center"><Spinner /></div>}
            {pkg && busy !== 'compile' && (
              <div className="card p-4 space-y-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="font-display font-medium text-[15px]">{pkg.display_name}</h2>
                  <span className="chip">{pkg.provider}</span>
                  <span className="chip">{pkg.kind}</span>
                  {Object.entries(pkg.params).filter(([k]) => !k.startsWith('_')).map(([k, v]) => (
                    <span key={k} className="chip"><span className="text-faint">{k}</span> {String(v)}</span>
                  ))}
                  <span className="ml-auto text-[12.5px] text-faint">{pkg.expected_output} · est {fmtUsd(pkg.estimated_cost)}</span>
                </div>
                <div>
                  <span className="label">Optimized prompt</span>
                  <textarea
                    className="input min-h-[110px] text-[13.5px]"
                    value={pkg.optimized_prompt}
                    aria-label="Optimized prompt"
                    onChange={(e) => setPkg({ ...pkg, optimized_prompt: e.target.value })}
                  />
                </div>
                {pkg.negative_prompt !== null && (
                  <div>
                    <span className="label">Negative prompt</span>
                    <input
                      className="input font-mono text-[12.5px]"
                      value={pkg.negative_prompt ?? ''}
                      aria-label="Negative prompt"
                      onChange={(e) => setPkg({ ...pkg, negative_prompt: e.target.value })}
                    />
                  </div>
                )}
                {pkg.optimization_notes.length > 0 && (
                  <ul className="text-[12px] text-mute space-y-0.5">
                    {pkg.optimization_notes.map((n, i) => (
                      <li key={i}><span className="text-ember-soft">◆</span> {n}</li>
                    ))}
                  </ul>
                )}
                {pkg.warnings.length > 0 && (
                  <ul className="text-[12px] text-amber-300 space-y-0.5">
                    {pkg.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
                  </ul>
                )}
                <details className="text-[12px] text-mute">
                  <summary className="cursor-pointer text-faint">Evaluation criteria ({pkg.evaluation_criteria.length}) · route reasoning</summary>
                  <ul className="mt-1 space-y-0.5">
                    {pkg.evaluation_criteria.map((c, i) => <li key={i}>☐ {c.check}</li>)}
                  </ul>
                  <p className="mt-1.5 text-faint">Routing ({pkg.route.policy}, {pkg.route.basis}): {pkg.route.reasons.join('; ')}</p>
                </details>
                <div className="flex items-center gap-2 flex-wrap border-t border-line pt-3">
                  <button className="btn-accent" disabled={busy !== null || !pkg.connected} title={pkg.connected ? '' : `${pkg.provider} is not connected — add its key in Settings → AI providers`} onClick={generate}>
                    {busy === 'generate' ? <Spinner /> : '⚡ Generate'}
                  </button>
                  {!pkg.connected && (
                    <span className="text-[12px] text-amber-300">
                      {pkg.provider} not connected — <Link className="underline underline-offset-2" to="/settings#providers">connect it</Link> or pick a connected model
                    </span>
                  )}
                  <label className="flex items-center gap-1.5 text-[12px] text-mute">
                    <input type="checkbox" checked={allowFallback} onChange={(e) => setAllowFallback(e.target.checked)} />
                    allow fallback provider on failure
                  </label>
                  <span className="ml-auto flex gap-2">
                    <button className="btn" disabled={busy !== null} onClick={polish}>✨ LLM polish</button>
                    <button className="btn" onClick={sendToLab}>Send to Lab</button>
                    <button className="btn" onClick={savePrompt}>Save</button>
                  </span>
                </div>
              </div>
            )}

            {job && (
              <div className="card p-4 flex items-center gap-3 fade-in">
                {['queued', 'running'].includes(job.status) && <Spinner />}
                <div className="text-[13px]">
                  <span className={job.status === 'failed' ? 'text-red-300' : job.status === 'succeeded' ? 'text-emerald-300' : 'text-fg'}>
                    {job.status}
                  </span>
                  <span className="text-faint"> · job #{job.job_id} on {job.provider}{job.fallback_of ? ` (fallback of #${job.fallback_of})` : ''}</span>
                  {job.error && (
                    <p className="text-[12.5px] text-red-300 mt-1">
                      {job.error.message}
                      {job.error.next_action && <span className="text-faint"> — {job.error.next_action}</span>}
                    </p>
                  )}
                </div>
                {job.status === 'succeeded' && job.output_post_id && (
                  <Link className="btn-accent ml-auto" to={`/?post=${job.output_post_id}`}>View result</Link>
                )}
              </div>
            )}
          </main>
        </div>
      )}
    </div>
  )
}
