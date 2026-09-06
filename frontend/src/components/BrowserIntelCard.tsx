// Settings → Browser intelligence (Inspiration 2.0, I8/I15).
//
// The determinism ladder, made visible: PF2 always prefers the cheapest level
// that works — a source's own JSON API, then deterministic selectors, then a
// cached workflow replayed by Playwright, and only then an AI browser engine
// to DISCOVER or REPAIR a workflow. This card is where the user sees which
// engines exist, what today's AI budget has been spent on, and which cached
// workflows are healthy — and where they can turn the whole AI layer off
// without losing any deterministic source.
import { useState } from 'react'
import { ApiError } from '../api'
import { useFetch } from '../lib/hooks'
import {
  BrowserWorkflowInfo,
  disableWorkflow,
  getBrowserStatus,
  repairWorkflow,
} from '../lib/inspiration'
import { SettingsMap } from '../lib/settings'
import { toastError, toastSuccess } from '../lib/toast'
import { Spinner } from './Primitives'
import { Field, NumberSetting, Section, ToggleSetting } from './SettingsKit'

const MODES = [
  { value: 'auto', label: 'Auto — deterministic first, AI only to learn or repair a workflow' },
  { value: 'deterministic', label: 'Deterministic only — replay cached workflows, never call an AI' },
  { value: 'stagehand', label: 'Stagehand (pinned)' },
  { value: 'browser_use', label: 'Browser Use (pinned)' },
  { value: 'off', label: 'Off — no browser tier at all' },
]
const ENGINE_LABEL: Record<string, string> = {
  playwright: 'Playwright (deterministic replay)',
  stagehand: 'Stagehand (AI act/observe/extract)',
  browser_use: 'Browser Use (AI agent)',
}
const HEALTH_STYLE: Record<string, string> = {
  healthy: 'text-emerald-300',
  unreliable: 'text-amber-300',
  needs_repair: 'text-rose-300',
  disabled: 'text-faint',
  superseded: 'text-faint',
}

function WorkflowRow({ wf, onChanged }: { wf: BrowserWorkflowInfo; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    try {
      await fn()
      toastSuccess(ok)
      onChanged()
    } catch (e) {
      // an unavailable engine or a spent budget is a state, not a crash (§128)
      toastError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <li className="flex flex-wrap items-center gap-2 text-[12.5px] border-t border-line py-1.5">
      <span className="font-medium">{wf.source}</span>
      <span className="chip">{wf.task}</span>
      <span className="text-faint">v{wf.version}</span>
      <span className={HEALTH_STYLE[wf.health] ?? 'text-mute'}>{wf.health.replace('_', ' ')}</span>
      <span className="text-faint tabular-nums">
        {wf.success_count}✓ / {wf.failure_count}✗ · {wf.actions.length} steps
      </span>
      {wf.last_error && (
        <span className="text-faint truncate max-w-[18rem]" title={wf.last_error}>
          {wf.last_error}
        </span>
      )}
      <span className="ml-auto flex gap-2">
        {wf.health !== 'disabled' && (
          <>
            <button className="text-mute hover:text-ember" disabled={busy} onClick={() => run(() => repairWorkflow(wf.id), 'Repair attempted')}>
              Repair
            </button>
            <button className="text-mute hover:text-rose-300" disabled={busy} onClick={() => run(() => disableWorkflow(wf.id), 'Workflow disabled')}>
              Disable
            </button>
          </>
        )}
      </span>
    </li>
  )
}

export function BrowserIntelCard({
  settings,
  save,
}: {
  settings: SettingsMap
  save: (v: SettingsMap) => Promise<boolean>
}) {
  const { data, reload } = useFetch(getBrowserStatus)
  const mode = String(settings.browser_intel_mode ?? 'auto')
  const aiOn = mode !== 'off' && mode !== 'deterministic' && Boolean(settings.browser_intel_ai_discovery)

  return (
    <Section
      title="Browser intelligence"
      hint="Sites without a usable API are read by a browser. PF2 always takes the most deterministic route that works — a cached workflow replayed by Playwright — and only asks an AI engine to LEARN or REPAIR that workflow. Turning AI off here never disables a source that has a working workflow, and never touches Reddit, Bluesky, YouTube or Civitai, which need no browser at all."
    >
      <Field label="Mode">
        <select
          className="input"
          value={mode}
          onChange={(e) => save({ browser_intel_mode: e.target.value })}
        >
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </Field>

      {!data ? (
        <Spinner />
      ) : (
        <>
          <Field label="Engines">
            <ul className="space-y-0.5 text-[12.5px]">
              {Object.entries(data.engines).map(([name, e]) => (
                <li key={name} className="flex items-center gap-2">
                  <span className={e.available ? 'text-emerald-300' : 'text-faint'}>{e.available ? '●' : '○'}</span>
                  <span className="text-fg">{ENGINE_LABEL[name] ?? name}</span>
                  {!e.enabled && <span className="chip">off</span>}
                  {e.detail && (
                    <span className="text-faint truncate" title={e.detail}>
                      {e.detail}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </Field>

          <Field
            label="Today's AI browser budget"
            hint="Resets at 00:00 UTC. Deterministic replays are free and are never counted."
          >
            <p className="text-[12.5px] text-mute tabular-nums">
              {data.usage.ai_calls} AI call{data.usage.ai_calls === 1 ? '' : 's'} ·{' '}
              {Math.round((data.usage.browser_seconds ?? 0) / 60)} browser minutes
              <span className="text-faint">
                {' '}
                of {String(settings.browser_intel_daily_ai_calls ?? 0)} calls /{' '}
                {String(settings.browser_intel_max_minutes ?? 0)} minutes
              </span>
            </p>
          </Field>

          <div className="flex flex-wrap items-center gap-4">
            <ToggleSetting
              settings={settings}
              k="browser_intel_ai_discovery"
              save={save}
              label="Let AI discover and repair workflows"
            />
            <ToggleSetting settings={settings} k="browser_intel_stagehand_enabled" save={save} label="Stagehand" />
            <ToggleSetting settings={settings} k="browser_intel_browser_use_enabled" save={save} label="Browser Use" />
          </div>
          <div className="flex flex-wrap gap-4">
            <Field label="AI calls per day">
              <NumberSetting settings={settings} k="browser_intel_daily_ai_calls" save={save} min={0} max={5000} suffix="calls" />
            </Field>
            <Field label="Browser minutes per day">
              <NumberSetting settings={settings} k="browser_intel_max_minutes" save={save} min={0} max={600} suffix="min" />
            </Field>
            <Field label="Link-follow depth">
              <NumberSetting settings={settings} k="browser_intel_max_depth" save={save} min={0} max={5} />
            </Field>
          </div>
          {!aiOn && (
            <p className="text-[12px] text-faint">
              AI browsing is off. Cached workflows still replay deterministically; a site whose page shape changes will
              report “needs repair” instead of repairing itself.
            </p>
          )}

          <Field label={`Cached workflows (${data.workflows.length})`}>
            {data.workflows.length === 0 ? (
              <p className="text-[12.5px] text-faint">
                None yet. A browser source stays idle — and says so — until a workflow exists for it.
              </p>
            ) : (
              <ul className="text-[12.5px]">
                {data.workflows.map((wf) => (
                  <WorkflowRow key={wf.id} wf={wf} onChanged={reload} />
                ))}
              </ul>
            )}
          </Field>

          {data.diagnostics.length > 0 && (
            <Field label="Recent browser runs">
              <ul className="space-y-0.5 text-[12px] text-faint">
                {data.diagnostics.slice(0, 5).map((d, i) => (
                  <li key={i} className="truncate">
                    {d.ok === false ? '✗' : '✓'} {d.source} · {d.task} {d.detail ? `— ${d.detail}` : ''}
                  </li>
                ))}
              </ul>
            </Field>
          )}
        </>
      )}
    </Section>
  )
}
