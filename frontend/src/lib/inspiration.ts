// Inspiration Intelligence client helpers (I7): typed API calls + the
// structured "Use as Inspiration" handoff (localStorage, provenance kept).
import { api, PostCard } from '../api'

export interface ScoreRow {
  component: string
  value: number
  weight: number
  contribution: number
}

export interface EvidenceRow {
  field: string
  value: unknown
  source: string
  confidence: number
  evidence?: string | null
}

export interface PostIntel {
  id: number
  scores: {
    inspiration: number | null
    candidate: number | null
    inspiration_breakdown: ScoreRow[]
    candidate_breakdown: ScoreRow[]
  }
  ai: { status?: string | null; confidence?: number | null; reason?: string; source?: string }
  detected: {
    model: { name: string | null; family: string | null; version: string | null; source: string | null }
    techniques: string[]
    camera: { lens_mm?: number[]; shot_size?: { value: string }[]; angle?: { value: string }[] } | null
    lighting: string[] | null
    composition: string[] | null
    descriptors: Record<string, string>
  }
  generation: Record<string, unknown>
  raw_metadata_keys: string[]
  evidence: EvidenceRow[]
  alternates: Record<string, EvidenceRow[]>
  prompt_source: string | null
  observed: Record<string, unknown>
  enrichment: {
    comments?: { id: string; author: string; text: string; likes: number; technical?: boolean; by_author?: boolean }[]
    thread?: { id: string; author: string; text: string }[]
    related?: { platform_post_id: string; known: boolean }[]
    author?: Record<string, unknown>
    fetched_at?: string
    comment_count?: number
  }
  links: { post_id: number; kind: string; score: number | null }[]
  clusters: { id: number; kind: string; key: string; label: string; post_count: number }[]
  pipeline_state: string | null
  creator: CreatorInfo | null
}

export interface CreatorInfo {
  id: number
  platform: string
  handle: string
  display_name: string | null
  profile_url: string | null
  avatar_url: string | null
  verified: boolean | null
  followers: number | null
  following: number | null
  bio: string | null
  monitored_account_id: number | null
  stats: {
    posts?: number
    images?: number
    videos?: number
    avg_engagement?: number | null
    posts_per_week?: number | null
    ai_ratio?: number
    prompt_availability?: number
    models?: { family: string; count: number }[]
    techniques?: { slug: string; count: number }[]
    styles?: { style: string; count: number }[]
    trend?: string | null
    engagement_trajectory?: { week: string; posts: number; avg_engagement: number }[]
    avg_inspiration?: number | null
    metadata_richness?: number
    top_post_ids?: number[]
    recent_post_ids?: number[]
  }
  top_posts?: PostCard[]
  recent_posts?: PostCard[]
}

export interface SourceReport {
  name: string
  runs: number
  discovered: number
  kept: number
  duplicates: number
  filtered: number
  discovery_yield: number
  duplicate_rate: number
  reliability: number | null
  efficiency: number
  recommendation: string
  last_runs: { at: string; found: number; new: number; dupes: number; filtered: number; errors: number; ok: boolean; duration_s: number | null }[]
  posts: number
  prompt_yield?: number
  metadata_yield?: number
  ai_rate?: number
  enrichment_yield?: number
  avg_inspiration?: number
  llm_calls?: number
}

export interface QueueStats {
  stages: Record<string, Record<string, number>>
  errors: { id: number; post_id: number | null; stage: string; state: string; attempts: number; error: string | null }[]
  pending: number
}

export interface Analytics {
  posts: number
  by_platform: Record<string, number>
  by_ai_status: Record<string, number>
  by_pipeline_state: Record<string, number>
  with_prompt: number
  with_metadata: number
  with_workflow: number
  prompt_sources: Record<string, number>
  model_sources: Record<string, number>
  inspiration_histogram: { range: string; count: number }[]
  queue_pending: number
  sources: SourceReport[]
  queue: QueueStats
  summary: { at: string; text: string } | null
}

export interface Trends {
  weeks: string[]
  series: Record<string, Record<string, number[]>>
  rising: { kind: string; key: string; recent: number; prior_avg: number; ratio: number }[]
  posts_considered: number
}

export interface ClusterInfo {
  id: number
  kind: string
  key: string
  label: string
  description: string | null
  post_count: number
  data: {
    top_post_ids?: number[]
    strongest_prompts?: { post_id: number; prompt: string; score: number | null }[]
    models?: { family: string; label: string; count: number }[]
    techniques?: { slug: string; count: number }[]
    creators?: { handle: string; count: number }[]
    avg_inspiration?: number
    videos?: number
  }
}

export const getPostIntel = (id: number) => api.get<PostIntel>(`/api/inspiration/posts/${id}/intel`)
export const getSimilar = (id: number, mode = 'all', limit = 12) =>
  api.get<Record<string, { rows: unknown[]; items: PostCard[] } | unknown>>(
    `/api/inspiration/similar/${id}?mode=${mode}&limit=${limit}`,
  )
export const listSources = () => api.get<{ sources: SourceReport[] }>('/api/inspiration/sources')
export const getQueue = () => api.get<QueueStats>('/api/inspiration/queue')
export const getAnalytics = () => api.get<Analytics>('/api/inspiration/analytics')
export const getTrends = (weeks = 12) => api.get<Trends>(`/api/inspiration/analytics/trends?weeks=${weeks}`)
export const listClusters = (kind?: string) =>
  api.get<{ clusters: ClusterInfo[] }>(`/api/inspiration/clusters${kind ? `?kind=${kind}` : ''}`)
export const getCluster = (id: number, cursor = 0, order = 'score') =>
  api.get<ClusterInfo & { items: PostCard[]; next_cursor: number | null; top_posts: PostCard[]; newest_posts: PostCard[] }>(
    `/api/inspiration/clusters/${id}?cursor=${cursor}&order=${order}`,
  )
export const listCreators = (sort = 'posts', q = '') =>
  api.get<{ creators: CreatorInfo[] }>(`/api/inspiration/creators?sort=${sort}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
export const getCreator = (id: number) => api.get<CreatorInfo>(`/api/inspiration/creators/${id}`)

// ---- "Use as Inspiration" handoff -------------------------------------
export interface InspirationContext {
  post_id: number
  platform: string
  source_url: string | null
  author: string | null
  prompt: string | null
  prompt_source: string | null
  model: { name: string | null; family: string | null; version: string | null; source: string | null }
  techniques: string[]
  camera: string[]
  lighting: string[]
  composition: string[]
  subject: string | null
  style: string | null
  prompt_structure: string | null
  references: string[]
  inspiration_score: number | null
  captured_at: string
}

const KEY = 'pf.inspiration.context'

export function buildInspirationContext(
  intel: PostIntel,
  post: { id: number; platform: string; source_url: string | null; author: string | null; prompt: string | null },
): InspirationContext {
  const cam = intel.detected.camera ?? {}
  const cameraBits = [
    ...(cam.lens_mm ?? []).map((mm) => `${mm}mm`),
    ...(cam.shot_size ?? []).map((s) => s.value),
    ...(cam.angle ?? []).map((a) => a.value),
  ]
  const refs = (intel.generation.references as string[] | undefined) ?? []
  const p = post.prompt ?? ''
  const commas = (p.match(/,/g) ?? []).length
  return {
    post_id: post.id,
    platform: post.platform,
    source_url: post.source_url,
    author: post.author,
    prompt: post.prompt,
    prompt_source: intel.prompt_source,
    model: intel.detected.model,
    techniques: intel.detected.techniques,
    camera: cameraBits,
    lighting: intel.detected.lighting ?? [],
    composition: intel.detected.composition ?? [],
    subject: intel.detected.descriptors.subject ?? null,
    style: intel.detected.descriptors.style ?? null,
    prompt_structure: p ? (commas / Math.max(1, p.split(/\s+/).length) > 0.12 ? 'tag-list' : 'natural') : null,
    references: refs,
    inspiration_score: intel.scores.inspiration,
    captured_at: new Date().toISOString(),
  }
}

export function saveInspirationContext(ctx: InspirationContext) {
  try {
    localStorage.setItem(KEY, JSON.stringify(ctx))
  } catch {
    /* storage unavailable */
  }
}

export function loadInspirationContext(): InspirationContext | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as InspirationContext) : null
  } catch {
    return null
  }
}

export function clearInspirationContext() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}

/** Compact prompt-ready phrase list from a context (no source text copied). */
export function contextToPhrases(ctx: InspirationContext): string[] {
  const out: string[] = []
  if (ctx.subject) out.push(ctx.subject)
  out.push(...ctx.camera, ...ctx.lighting, ...ctx.composition)
  if (ctx.style) out.push(ctx.style)
  out.push(...ctx.techniques.map((t) => t.replace(/-/g, ' ')))
  return Array.from(new Set(out.filter(Boolean)))
}
