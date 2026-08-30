// Generate flow (8.6): recommended model preselected, per-model+provider
// prices up front, cheapest-provider auto-routing with override, gentle
// off-recommendation note, live progress, result lands in the library.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'
import { formatMoney } from '../lib/format'
import { toastError } from '../lib/toast'
import { Modal, Spinner } from './Primitives'

export interface GenOffer {
  provider: string
  provider_model_id: string
  kind: 'image' | 'video'
  price_estimate: number | null
  connected: boolean
}

export interface GenModelOption {
  family: string
  label: string
  kind: 'image' | 'video'
  offers: GenOffer[]
}

interface GenOptions {
  connected_providers: string[]
  models: GenModelOption[]
}

interface GenStatus {
  id: number
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  error: string | null
  cost_estimate: number | null
  cost_actual: number | null
  output_post_id: number | null
  provider: string
  provider_model_id: string
}

const IMAGE_SIZES = ['1024x1024', '832x1216', '1216x832', '1024x1536', '1536x1024']

export function GeneratePanel({
  prompt,
  negative,
  modelFamily,
  collectionId,
  templateId,
  savedPromptId,
  refIds = [],
  disabled = false,
  buttonLabel = '⚡ Generate',
}: {
  prompt: string
  negative?: string | null
  modelFamily?: string | null
  collectionId?: number | null
  templateId?: number | null
  savedPromptId?: number | null
  refIds?: number[]
  disabled?: boolean
  buttonLabel?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button className="btn-accent" disabled={disabled || !prompt.trim()} onClick={() => setOpen(true)}>
        {buttonLabel}
      </button>
      {open && (
        <GenerateModal
          prompt={prompt}
          negative={negative}
          modelFamily={modelFamily ?? null}
          collectionId={collectionId ?? null}
          templateId={templateId ?? null}
          savedPromptId={savedPromptId ?? null}
          refIds={refIds}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}

function GenerateModal({
  prompt,
  negative,
  modelFamily,
  collectionId,
  templateId,
  savedPromptId,
  refIds,
  onClose,
}: {
  prompt: string
  negative?: string | null
  modelFamily: string | null
  collectionId: number | null
  templateId: number | null
  savedPromptId: number | null
  refIds: number[]
  onClose: () => void
}) {
  const [options, setOptions] = useState<GenOptions | null>(null)
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const [family, setFamily] = useState(modelFamily ?? '')
  const [provider, setProvider] = useState('') // '' = auto (cheapest)
  const [size, setSize] = useState('1024x1024')
  const [duration, setDuration] = useState(5)
  const [estimate, setEstimate] = useState<number | null>(null)
  const [gen, setGen] = useState<GenStatus | null>(null)
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    api
      .get<GenOptions>('/api/generation/options')
      .then((r) => {
        setOptions(r)
        if (!modelFamily && r.models.length) setFamily(r.models[0].family)
      })
      .catch((e: Error) => setOptionsError(e.message))
  }, [modelFamily])

  const model = options?.models.find((m) => m.family === family)
  const connectedOffers = (model?.offers ?? []).filter((o) => o.connected)
  const isVideo = model?.kind === 'video'

  useEffect(() => {
    if (!family || !options) return
    const params = new URLSearchParams({ model_family: family })
    if (provider) params.set('provider', provider)
    if (isVideo) params.set('duration', String(duration))
    else params.set('size', size)
    api
      .get<{ estimate: number | null }>(`/api/generation/estimate?${params}`)
      .then((r) => setEstimate(r.estimate))
      .catch(() => setEstimate(null))
  }, [family, provider, size, duration, isVideo, options])

  // poll status while a generation runs
  useEffect(() => {
    if (!gen || gen.status === 'succeeded' || gen.status === 'failed') return
    const t = window.setInterval(() => {
      api
        .get<GenStatus>(`/api/generation/${gen.id}`)
        .then(setGen)
        .catch(() => undefined)
    }, 1500)
    return () => window.clearInterval(t)
  }, [gen])

  const start = async () => {
    setStarting(true)
    try {
      const r = await api.post<GenStatus>('/api/generation/start', {
        prompt,
        negative: negative || undefined,
        model_family: family,
        provider: provider || undefined,
        params: isVideo ? { duration_s: duration } : { size },
        collection_id: collectionId ?? undefined,
        template_id: templateId ?? undefined,
        saved_prompt_id: savedPromptId ?? undefined,
        ref_ids: refIds,
      })
      setGen(r)
    } catch (e) {
      toastError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setStarting(false)
    }
  }

  const offRecommendation = modelFamily && family && family !== modelFamily

  return (
    <Modal title="Generate" onClose={onClose}>
      {!options && !optionsError && (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      )}
      {optionsError && <p className="text-[13px] text-red-300">{optionsError}</p>}
      {options && options.connected_providers.length === 0 && (
        <div className="text-[13px] text-mute space-y-2">
          <p>No generation providers connected yet.</p>
          <p>
            Add fal.ai, Replicate or WaveSpeed keys in{' '}
            <Link to="/settings#providers" className="underline underline-offset-2 text-fg" onClick={onClose}>
              Settings → AI providers
            </Link>{' '}
            — each has a guided setup with a test button.
          </p>
        </div>
      )}
      {options && options.connected_providers.length > 0 && !gen && (
        <div className="space-y-3">
          <p className="text-[12.5px] text-mute bg-well/60 border border-line rounded-el p-2.5 max-h-24 overflow-y-auto whitespace-pre-wrap">
            {prompt}
          </p>
          <div>
            <label className="label" htmlFor="gen-model">
              Model — prices shown per {isVideo ? 'clip' : 'image'}
            </label>
            <select
              id="gen-model"
              className="input"
              value={family}
              onChange={(e) => {
                setFamily(e.target.value)
                setProvider('')
              }}
            >
              {options.models.map((m) => {
                const cheapest = m.offers.filter((o) => o.connected && o.price_estimate != null)
                const min = cheapest.length
                  ? Math.min(...cheapest.map((o) => o.price_estimate as number))
                  : null
                return (
                  <option key={m.family} value={m.family}>
                    {m.label}
                    {min != null ? ` — from ${formatMoney(min)}` : ' — no connected provider'}
                    {modelFamily === m.family ? '  ★ recommended' : ''}
                  </option>
                )
              })}
            </select>
          </div>
          {offRecommendation && (
            <p className="text-[12px] text-amber-200/90">
              This collection's style was learned on{' '}
              {options.models.find((m) => m.family === modelFamily)?.label ?? modelFamily} — results may
              differ.
            </p>
          )}
          <div>
            <label className="label" htmlFor="gen-provider">
              Provider
            </label>
            <select id="gen-provider" className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="">Auto — cheapest connected provider</option>
              {connectedOffers.map((o) => (
                <option key={o.provider} value={o.provider}>
                  {o.provider} · {o.provider_model_id} · {formatMoney(o.price_estimate)}
                </option>
              ))}
            </select>
          </div>
          {isVideo ? (
            <div>
              <label className="label" htmlFor="gen-duration">
                Duration: {duration}s
              </label>
              <input
                id="gen-duration"
                type="range"
                min={2}
                max={10}
                value={duration}
                className="w-full accent-[#FF6A3D]"
                onChange={(e) => setDuration(Number(e.target.value))}
              />
            </div>
          ) : (
            <div>
              <label className="label" htmlFor="gen-size">
                Size
              </label>
              <select id="gen-size" className="input" value={size} onChange={(e) => setSize(e.target.value)}>
                {IMAGE_SIZES.map((sz) => (
                  <option key={sz} value={sz}>
                    {sz}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex items-center justify-between border-t border-line pt-3">
            <span className="text-[13px]">
              Expected cost:{' '}
              <strong className="tabular-nums text-fg">{formatMoney(estimate)}</strong>
            </span>
            <button className="btn-accent" onClick={start} disabled={starting || connectedOffers.length === 0}>
              {starting ? <Spinner /> : 'Generate'}
            </button>
          </div>
          {connectedOffers.length === 0 && (
            <p className="text-[12px] text-amber-300">
              No connected provider offers this model — pick another model or connect a provider.
            </p>
          )}
        </div>
      )}
      {gen && (
        <div className="space-y-3 text-center py-2">
          {gen.status === 'queued' || gen.status === 'running' ? (
            <>
              <Spinner className="w-6 h-6 mx-auto" />
              <p className="text-[13px] text-mute capitalize">{gen.status}…</p>
              <p className="text-[12px] text-faint">
                {gen.provider} · {gen.provider_model_id} · est {formatMoney(gen.cost_estimate)}
              </p>
            </>
          ) : gen.status === 'succeeded' ? (
            <>
              <p className="text-[15px]">✓ Done — added to your library</p>
              {gen.output_post_id && (
                <img
                  src={`/api/posts/${gen.output_post_id}/thumb`}
                  alt=""
                  className="mx-auto max-h-52 rounded-el border border-line"
                  onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
                />
              )}
              <div className="flex justify-center gap-2">
                {gen.output_post_id && (
                  <Link to={`/?post=${gen.output_post_id}`} className="btn-accent" onClick={onClose}>
                    Open in gallery
                  </Link>
                )}
                <button
                  className="btn"
                  onClick={() => {
                    setGen(null)
                  }}
                >
                  Generate another
                </button>
              </div>
              <p className="text-[12px] text-faint">
                Cost: {formatMoney(gen.cost_actual ?? gen.cost_estimate)} — fed back into the knowledge
                engine
              </p>
            </>
          ) : (
            <>
              <p className="text-[14px] text-red-300">Generation failed</p>
              <p className="text-[12.5px] text-mute break-words">{gen.error}</p>
              <button className="btn" onClick={() => setGen(null)}>
                Back
              </button>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}
