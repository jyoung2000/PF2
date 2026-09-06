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

/** I11: where a prompt actually came from (§20/§121). `kind` is the honest
 *  three-way label the GUI must show — observed | reconstructed | inferred. */
export interface PromptFragment {
  text: string
  source: string
  location: string
  confidence: number
  ref: string | null
  author_is_creator: boolean | null
}

export interface PromptProvenance {
  source: string | null
  rank: string | null
  label: string
  kind: 'observed' | 'reconstructed' | 'inferred' | null
  explicit: boolean
  ai_written: boolean
  confidence: number | null
  evidence: string | null
  fragments: PromptFragment[]
  notes: string[]
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
  prompt_provenance: PromptProvenance | null
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
    // I12
    prompt_quality?: {
      explicit_prompts: number
      avg_words?: number
      median_words?: number
      with_parameters?: number
      with_negative?: number
      structured?: number
      score: number
      detail?: string
    }
    workflow_richness?: {
      with_workflow?: number
      with_embedded_metadata?: number
      with_named_model?: number
      workflow_ratio?: number
      score: number
    }
    prompt_sources?: { source: string; count: number }[]
    cross_platform?: { linked_platforms: string[]; links: number; note: string }
  }
  links?: CreatorLink[]
  top_posts?: PostCard[]
  recent_posts?: PostCard[]
}

/** I12: an evidence-carrying edge between two platform identities. PF2 shows
 *  them together and never merges the rows. */
export interface CreatorLink {
  link_id: number
  creator_id: number
  platform: string
  handle: string
  display_name: string | null
  profile_url: string | null
  confidence: number
  kind: string | null
  evidence: Record<string, unknown>
  created_by: string
}

export interface CreatorIdentity {
  creator_id: number
  platforms: string[]
  members: {
    creator_id: number
    platform: string
    handle: string
    display_name: string | null
    posts: number
    followers: number | null
    avg_engagement: number | null
    prompt_availability: number | null
  }[]
  total_posts: number
  links: (CreatorLink & { from: number })[]
  merged: boolean
  note: string
}

export interface LinkSuggestion {
  creator_a: { id: number; platform: string; handle: string }
  creator_b: { id: number; platform: string; handle: string }
  kind: string
  confidence: number
  evidence: Record<string, unknown> & { detail?: string }
  corroborated_by: string[]
  auto_linkable: boolean
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

// ---- I14: cross-source signals + discovery shelves ---------------------
export interface CrossSignal {
  kind: string
  key: string
  total: number
  platforms: Record<string, number>
  platform_count: number
  series: number[]
  velocity: number
  acceleration: number
  direction: 'rising' | 'falling' | 'steady' | 'cooling' | 'unknown'
  score: number
  example_post_ids: number[]
  why: string
}

export interface PromptPattern {
  phrases: string[]
  posts: number
  lift: number
  notable: boolean
  platforms: string[]
  platform_count: number
  avg_engagement: number | null
  example_post_ids: number[]
  why: string
}

export interface GrowthRow {
  post_id: number
  gain: number
  per_day: number
  hours_observed: number
  snapshots: number
  from: number
  to: number
  why: string
}

export interface SignalSummary {
  cross_platform: { weeks: string[]; signals: CrossSignal[]; cross_platform_count: number; posts_considered: number }
  prompt_patterns: { patterns: PromptPattern[]; prompts_considered: number; notable: number; basis: string }
  engagement_growth: { growing: GrowthRow[]; posts_with_history: number; posts_seen_once: number; note: string }
  rising: CrossSignal[]
  requires_ai: boolean
}

export interface DiscoverShelf {
  mode: string
  modes: string[]
  detail: string
  ranked_by: string
  query: string | null
  considered: number
  results: { post_id: number; platform: string; score: number; relevance: number | null; why: string[] }[]
  items: (PostCard & { why: string[]; rank_score: number; relevance?: number | null })[]
}

export const getSignalSummary = (weeks = 8) =>
  api.get<SignalSummary>(`/api/inspiration/analytics/signals/summary?weeks=${weeks}`)
export const discover = (mode = 'trending', opts: { q?: string; platform?: string; limit?: number } = {}) => {
  const p = new URLSearchParams({ mode, limit: String(opts.limit ?? 40) })
  if (opts.q) p.set('q', opts.q)
  if (opts.platform) p.set('platform', opts.platform)
  return api.get<DiscoverShelf>(`/api/inspiration/discover?${p}`)
}
export const listClusters = (kind?: string) =>
  api.get<{ clusters: ClusterInfo[] }>(`/api/inspiration/clusters${kind ? `?kind=${kind}` : ''}`)
export const getCluster = (id: number, cursor = 0, order = 'score') =>
  api.get<ClusterInfo & { items: PostCard[]; next_cursor: number | null; top_posts: PostCard[]; newest_posts: PostCard[] }>(
    `/api/inspiration/clusters/${id}?cursor=${cursor}&order=${order}`,
  )
export const listCreators = (sort = 'posts', q = '') =>
  api.get<{ creators: CreatorInfo[] }>(`/api/inspiration/creators?sort=${sort}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
export const getCreator = (id: number) => api.get<CreatorInfo>(`/api/inspiration/creators/${id}`)
export const getCreatorIdentity = (id: number) =>
  api.get<CreatorIdentity>(`/api/inspiration/creators/${id}/identity`)
export const getLinkSuggestions = (creatorId?: number) =>
  api.get<{ suggestions: LinkSuggestion[]; evidence_kinds: string[]; note: string }>(
    `/api/inspiration/creators/links/suggestions${creatorId ? `?creator_id=${creatorId}` : ''}`,
  )
export const createCreatorLink = (creator_a: number, creator_b: number, kind = 'user', detail?: string) =>
  api.post<{ link_id: number; confidence: number }>('/api/inspiration/creators/links', {
    creator_a,
    creator_b,
    kind,
    detail,
  })
export const deleteCreatorLink = (linkId: number) =>
  api.delete<{ ok: boolean }>(`/api/inspiration/creators/links/${linkId}`)

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
