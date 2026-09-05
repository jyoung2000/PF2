// "Why this post is inspiring" (I7.2): score breakdown, detected fields,
// structured generation metadata, evidence/provenance, enrichment, related
// posts + clusters, and the handoff actions (Studio / Inspiration / creator).
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PostCard, PostDetail } from '../api'
import {
  buildInspirationContext,
  EvidenceRow,
  getPostIntel,
  getSimilar,
  PostIntel,
  saveInspirationContext,
} from '../lib/inspiration'
import { toastError, toastSuccess } from '../lib/toast'
import { Spinner } from './Primitives'

const LABELS: Record<string, string> = {
  visual_quality: 'Visual quality',
  prompt_quality: 'Prompt quality',
  technical_detail: 'Technical detail',
  novelty: 'Novelty',
  engagement: 'Engagement',
  model_relevance: 'Model relevance',
  metadata_richness: 'Metadata richness',
}
const AI_LABEL: Record<string, string> = {
  definitely_ai: 'Definitely AI',
  probably_ai: 'Probably AI',
  uncertain: 'Uncertain',
  probably_not_ai: 'Probably not AI',
  definitely_not_ai: 'Definitely not AI',
}
const SOURCE_LABEL: Record<string, string> = {
  observed: 'observed',
  metadata: 'embedded metadata',
  extracted: 'extracted from text',
  inferred: 'inferred',
  ai: 'AI analysis',
  user: 'you',
  explicit: 'explicit',
}

function ScoreBar({ row }: { row: { component: string; value: number; contribution: number } }) {
  return (
    <div className="flex items-center gap-2 text-[12px]">
      <span className="w-32 shrink-0 text-mute">{LABELS[row.component] ?? row.component}</span>
      <span className="flex-1 h-1.5 rounded-full bg-well overflow-hidden">
        <span className="block h-full bg-ember/80" style={{ width: `${Math.round(row.value * 100)}%` }} />
      </span>
      <span className="w-10 text-right tabular-nums text-faint">+{row.contribution}</span>
    </div>
  )
}

function fmtValue(v: unknown): string {
  if (v == null) return ''
  if (Array.isArray(v)) return v.map(fmtValue).join(', ')
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>
    return Object.entries(o)
      .map(([k, val]) => `${k}: ${fmtValue(val)}`)
      .join(' · ')
  }
  return String(v)
}

function GenerationView({ generation }: { generation: Record<string, unknown> }) {
  const scalars = Object.entries(generation).filter(
    ([k, v]) => v != null && v !== '' && typeof v !== 'object' && !['engagement', 'hashtags', 'metadata_formats'].includes(k),
  )
  const loras = (generation.loras as { name?: string; weight?: unknown }[] | undefined) ?? []
  const controlnet = (generation.controlnet as Record<string, unknown>[] | undefined) ?? []
  const video = generation.video as Record<string, unknown> | undefined
  const hires = generation.hires as Record<string, unknown> | undefined
  const refs = (generation.references as string[] | undefined) ?? []
  if (!scalars.length && !loras.length && !controlnet.length && !video && !refs.length) return null
  return (
    <div className="space-y-1.5 text-[12px]">
      <div className="flex flex-wrap gap-1.5">
        {scalars.map(([k, v]) => (
          <span key={k} className="chip">
            <span className="text-faint">{k}</span> {String(v)}
          </span>
        ))}
      </div>
      {loras.length > 0 && (
        <p>
          <span className="text-faint">LoRA:</span>{' '}
          {loras.map((l) => `${l.name ?? '?'}${l.weight != null ? ` ×${l.weight}` : ''}`).join(', ')}
        </p>
      )}
      {controlnet.length > 0 && (
        <p>
          <span className="text-faint">ControlNet:</span> {controlnet.map((c) => fmtValue(c)).join(' | ')}
        </p>
      )}
      {video && (
        <p>
          <span className="text-faint">Video:</span> {fmtValue(video)}
        </p>
      )}
      {hires && (
        <p>
          <span className="text-faint">Hires:</span> {fmtValue(hires)}
        </p>
      )}
      {refs.length > 0 && (
        <p>
          <span className="text-faint">References:</span> {refs.join(', ')}
        </p>
      )}
      {'workflow' in generation && <p className="text-faint">ComfyUI workflow JSON stored (full graph preserved).</p>}
    </div>
  )
}

function EvidenceList({ rows }: { rows: EvidenceRow[] }) {
  if (!rows.length) return <p className="text-[12px] text-faint">No provenance recorded yet.</p>
  return (
    <ul className="space-y-1 text-[12px]">
      {rows.map((r) => (
        <li key={r.field} className="flex gap-2">
          <span className="w-24 shrink-0 text-faint">{r.field}</span>
          <span className="min-w-0 flex-1">
            <span className="break-words">{fmtValue(r.value).slice(0, 140)}</span>{' '}
            <span className="chip !text-[10.5px] align-middle">{SOURCE_LABEL[r.source] ?? r.source}</span>{' '}
            <span className="text-faint tabular-nums">{Math.round((r.confidence ?? 0) * 100)}%</span>
            {r.evidence && <span className="block text-faint italic truncate">“{r.evidence}”</span>}
          </span>
        </li>
      ))}
    </ul>
  )
}

function MiniThumbs({ items, onOpen }: { items: PostCard[]; onOpen: (id: number) => void }) {
  if (!items.length) return <p className="text-[12px] text-faint">Nothing close enough yet.</p>
  return (
    <div className="grid grid-cols-4 gap-1.5">
      {items.map((p) => (
        <button
          key={p.id}
          className="aspect-square rounded-el overflow-hidden border border-line bg-well hover:border-ember/60 focus:outline-none focus:ring-2 focus:ring-ember/50"
          onClick={() => onOpen(p.id)}
          title={p.prompt ?? ''}
        >
          {p.thumb_url ? <img src={p.thumb_url} alt="" className="w-full h-full object-cover" loading="lazy" /> : null}
        </button>
      ))}
    </div>
  )
}

export function IntelPanel({ post, onOpenPost }: { post: PostDetail; onOpenPost: (id: number) => void }) {
  const navigate = useNavigate()
  const [intel, setIntel] = useState<PostIntel | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [similar, setSimilar] = useState<Record<string, PostCard[]> | null>(null)
  const [loadingSimilar, setLoadingSimilar] = useState(false)
  const [showEvidence, setShowEvidence] = useState(false)

  useEffect(() => {
    setIntel(null)
    setSimilar(null)
    setError(null)
    getPostIntel(post.id)
      .then(setIntel)
      .catch((e: Error) => setError(e.message))
  }, [post.id])

  const findSimilar = async () => {
    setLoadingSimilar(true)
    try {
      const r = (await getSimilar(post.id)) as Record<string, { items?: PostCard[] }>
      setSimilar({
        visual: r.visual?.items ?? [],
        prompt: r.prompt?.items ?? [],
        technique: r.technique?.items ?? [],
      })
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setLoadingSimilar(false)
    }
  }

  const useInStudio = () => {
    const q = new URLSearchParams({ prompt: post.prompt ?? '' })
    navigate(`/studio/enhance?${q.toString()}`)
  }

  const useInFilm = () => {
    if (!intel) return
    saveInspirationContext(buildInspirationContext(intel, post))
    toastSuccess('Inspiration context captured — pick a shot in the Storyboard to apply it')
    navigate('/film/storyboard?inspiration=1')
  }

  const useAsInspiration = () => {
    if (!intel) return
    saveInspirationContext(buildInspirationContext(intel, post))
    toastSuccess('Inspiration context captured — opening Studio')
    navigate('/studio/enhance?inspiration=1')
  }

  if (error) return <p className="text-[12px] text-red-300">Intel unavailable: {error}</p>
  if (!intel)
    return (
      <div className="py-3">
        <Spinner />
      </div>
    )

  const score = intel.scores.inspiration
  const ai = intel.ai
  const det = intel.detected
  const cam = det.camera ?? {}
  const comments = intel.enrichment.comments ?? []

  return (
    <div className="space-y-5">
      {/* actions */}
      <div className="flex flex-wrap gap-1.5">
        <button className="btn h-7 py-0 text-[12px]" onClick={useInStudio} disabled={!post.prompt}>
          Use in Studio
        </button>
        <button className="btn-accent h-7 py-0 text-[12px]" onClick={useAsInspiration}>
          ✦ Use as Inspiration
        </button>
        <button className="btn text-[12px]" onClick={useInFilm} disabled={!intel} title="Populate camera, lighting, style and subject on a storyboard shot (with attribution)">
          🎬 Use in Film
        </button>
        <button className="btn h-7 py-0 text-[12px]" onClick={findSimilar} disabled={loadingSimilar}>
          {loadingSimilar ? <Spinner /> : 'Find similar'}
        </button>
        {intel.creator && (
          <button className="btn h-7 py-0 text-[12px]" onClick={() => navigate(`/inspiration/creators/${intel.creator!.id}`)}>
            View creator
          </button>
        )}
      </div>

      {/* why inspiring */}
      <section>
        <div className="flex items-baseline justify-between mb-1.5">
          <h3 className="label !mb-0">Why this is inspiring</h3>
          <span className="font-display text-[20px] tabular-nums text-ember">{score != null ? Math.round(score) : '—'}</span>
        </div>
        <div className="space-y-1">
          {intel.scores.inspiration_breakdown.map((r) => (
            <ScoreBar key={r.component} row={r} />
          ))}
        </div>
        <p className="text-[11.5px] text-faint mt-1.5">
          {ai.status && (
            <>
              <span className={ai.status.endsWith('_ai') && !ai.status.includes('not') ? 'text-emerald-300' : 'text-amber-300'}>
                {AI_LABEL[ai.status] ?? ai.status}
              </span>{' '}
              {ai.confidence != null && <>({Math.round(ai.confidence * 100)}%)</>}
              {ai.reason && <> — {ai.reason}</>}
              {ai.source && <> · via {ai.source}</>}
            </>
          )}
          {intel.scores.candidate != null && <> · candidate score {Math.round(intel.scores.candidate)}</>}
          {intel.pipeline_state && <> · {intel.pipeline_state}</>}
        </p>
      </section>

      {/* detected */}
      <section>
        <h3 className="label">Detected</h3>
        <div className="flex flex-wrap gap-1.5 text-[12px]">
          {det.model.name && (
            <span className="chip !text-fg">
              {det.model.name}
              {det.model.version && <> {det.model.version}</>}
              {det.model.source && <span className="text-faint"> · {SOURCE_LABEL[det.model.source] ?? det.model.source}</span>}
            </span>
          )}
          {(cam.lens_mm ?? []).map((mm) => (
            <span key={`mm${mm}`} className="chip">
              {mm}mm
            </span>
          ))}
          {(cam.shot_size ?? []).map((s) => (
            <span key={s.value} className="chip">
              {s.value}
            </span>
          ))}
          {(cam.angle ?? []).map((a) => (
            <span key={a.value} className="chip">
              {a.value}
            </span>
          ))}
          {(det.lighting ?? []).map((l) => (
            <span key={`l${l}`} className="chip text-amber-200/90">
              {l}
            </span>
          ))}
          {(det.composition ?? []).map((c) => (
            <span key={`c${c}`} className="chip">
              {c}
            </span>
          ))}
          {det.techniques.map((t) => (
            <span key={t} className="chip !text-ember-soft border-ember/30">
              {t}
            </span>
          ))}
          {Object.entries(det.descriptors).map(([k, v]) => (
            <span key={k} className="chip">
              <span className="text-faint">{k}</span> {v}
            </span>
          ))}
        </div>
      </section>

      {/* generation metadata */}
      {Object.keys(intel.generation).length > 0 && (
        <section>
          <h3 className="label">Generation metadata</h3>
          <GenerationView generation={intel.generation} />
          {intel.raw_metadata_keys.length > 0 && (
            <p className="text-[11.5px] text-faint mt-1">Raw chunks kept: {intel.raw_metadata_keys.join(', ')}</p>
          )}
        </section>
      )}

      {/* evidence */}
      <section>
        <button className="label !mb-1 hover:text-fg" onClick={() => setShowEvidence(!showEvidence)}>
          Evidence &amp; provenance ({intel.evidence.length}) {showEvidence ? '▾' : '▸'}
        </button>
        {showEvidence && (
          <>
            <EvidenceList rows={intel.evidence} />
            {Object.keys(intel.alternates).length > 0 && (
              <p className="text-[11.5px] text-faint mt-1">
                Alternates kept (lower-trust sources):{' '}
                {Object.entries(intel.alternates)
                  .map(([f, rows]) => `${f} ×${rows.length}`)
                  .join(', ')}
              </p>
            )}
          </>
        )}
      </section>

      {/* enrichment */}
      {comments.length > 0 && (
        <section>
          <h3 className="label">From the thread ({intel.enrichment.comment_count ?? comments.length})</h3>
          <ul className="space-y-1 text-[12px]">
            {comments.slice(0, 6).map((c) => (
              <li key={c.id} className={c.technical ? '' : 'text-faint'}>
                <span className={c.by_author ? 'text-ember-soft' : 'text-mute'}>{c.author}</span>{' '}
                {c.technical && <span className="chip !text-[10px]">technical</span>} {c.text.slice(0, 200)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* related */}
      {(intel.clusters.length > 0 || intel.links.length > 0) && (
        <section>
          <h3 className="label">Related</h3>
          <div className="flex flex-wrap gap-1.5">
            {intel.clusters.map((c) => (
              <button
                key={c.id}
                className="chip hover:border-ember/60"
                onClick={() => navigate(`/inspiration/clusters/${c.id}`)}
                title={`${c.kind} cluster · ${c.post_count} posts`}
              >
                {c.label}
              </button>
            ))}
            {intel.links.map((l) => (
              <button key={`${l.kind}-${l.post_id}`} className="chip hover:border-ember/60" onClick={() => onOpenPost(l.post_id)}>
                {l.kind === 'near' ? 'near-duplicate' : l.kind} #{l.post_id}
              </button>
            ))}
          </div>
        </section>
      )}

      {similar && (
        <section className="space-y-2">
          <h3 className="label">Similar</h3>
          <p className="text-[11.5px] text-faint">Visually</p>
          <MiniThumbs items={similar.visual} onOpen={onOpenPost} />
          <p className="text-[11.5px] text-faint">By prompt</p>
          <MiniThumbs items={similar.prompt} onOpen={onOpenPost} />
          <p className="text-[11.5px] text-faint">By technique</p>
          <MiniThumbs items={similar.technique} onOpen={onOpenPost} />
        </section>
      )}
    </div>
  )
}
