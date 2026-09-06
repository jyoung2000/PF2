// Typed helpers for the Forge API (spec §2–§13). Shapes mirror
// backend/promptforge/forge/*.
import { api } from '../api'

export interface ModelOffer {
  provider: string
  provider_model_id: string | null
  modes: string[]
  price_estimate: number | null
  connected: boolean
}

export interface ModelEntry {
  family: string
  display_name: string | null
  modality: string
  tasks: string[]
  availability: string
  latency_class: string | null
  quality_prior: number | null
  aspect_ratios: string[] | null
  resolutions: string[] | null
  max_duration_s: number | null
  supports: Record<string, boolean>
  licensing: string | null
  commercial_use: string | null
  local_hardware: string | null
  prompt: { style: string; camera_language: boolean; max_terms: number | null; notes: string | null }
  strengths: string[]
  weaknesses: string[]
  fallback_families: string[]
  last_verified: string | null
  deprecation: string | null
  api_available: boolean | null
  source_urls: string[]
  evidence: string | null
  confidence: number | null
  offers: ModelOffer[]
  generatable: boolean
  observed: { post_count: number; last_seen: string | null } | null
  knowledge_file: boolean
}

export interface ProviderInfo {
  name: string
  label: string
  kind: 'generation' | 'llm' | 'local'
  free: boolean
  local: boolean
  configured: boolean
  key_setting: string | null
  key_url: string | null
}

export interface RouteCandidate {
  family: string
  display_name: string | null
  provider: string
  provider_model_id: string | null
  connected: boolean
  estimate: number | null
  total: number
  scores: Record<string, number>
  reasons: string[]
  basis: string
  unsupported_constraints: string[]
  parameter_recommendations: Record<string, unknown>
  prompt_recommendation: { style: string; notes: string | null }
  history: { attempts: number; successes: number }
  provenance?: { confidence: number | null; source_urls: string[]; evidence: string | null; last_verified: string | null }
}

export interface RouteResult {
  intent: Record<string, unknown> & { evidence?: Record<string, unknown> }
  recommended: RouteCandidate | null
  alternatives: RouteCandidate[]
  candidates: RouteCandidate[]
  policy: string
  unsupported?: string
}

export interface PromptPackage {
  original: string
  optimized_prompt: string
  negative_prompt: string | null
  structured: Record<string, unknown>
  intent: Record<string, unknown>
  family: string
  display_name: string
  provider: string
  provider_model_id: string | null
  connected: boolean
  kind: string
  params: Record<string, unknown>
  expected_output: string
  estimated_cost: number | null
  evaluation_criteria: { key: string; check: string }[]
  optimization_notes: string[]
  llm_polish: { applied: boolean; reason?: string } | null
  warnings: string[]
  route: {
    policy: string
    reasons: string[]
    basis: string
    unsupported_constraints: string[]
    alternatives: { family: string; display_name: string; provider: string; total: number; estimate: number | null; connected: boolean }[]
  }
  error?: string
}

export interface ToolInfo {
  name: string
  label: string
  mode: string
  kind: string
  supported: boolean
  families: string[]
  reason?: string
}

export interface JobStatus {
  job_id: number
  status: string
  tool: string | null
  provider: string
  family: string | null
  estimate: number | null
  cost_actual: number | null
  output_post_id: number | null
  error?: { message: string; provider: string; recoverable: boolean; fallback_options: string[]; next_action: string }
  fallback_of?: number
}

export interface MultimodalView {
  available: boolean
  mode: string
  backend?: string
  reason?: string
  frames_examined?: number
  overall_score?: number | null
  dimensions?: Record<string, number>
  issues?: string[]
  recommendations?: string[]
  evidence?: string[]
  confidence?: number
  transcript?: string | null
}

export interface EvaluationView {
  findings?: { kind: string; severity: string; message: string }[]
  verdict?: string
  unavailable?: string[]
  multimodal?: MultimodalView
  overall_score?: number | null
  dimensions?: Record<string, number>
  recommendations?: string[]
  evidence?: string[]
  confidence?: number
  mode?: string
}

export interface VariantRunView {
  id: number
  generation_id: number | null
  status: string
  family: string | null
  provider: string | null
  user_score: number | null
  user_notes: string | null
  evaluation: EvaluationView
  cost: number | null
  latency_s: number | null
  output_post_id: number | null
  thumb_url: string | null
  error: string | null
}

export interface VariantView {
  id: number
  version: number
  label: string | null
  origin: string
  parent_id: number | null
  prompt: string
  negative: string | null
  family: string | null
  provider: string | null
  params: Record<string, unknown>
  winner: boolean
  runs: VariantRunView[]
}

export interface ExperimentView {
  id: number
  name: string
  brief: string | null
  intent: Record<string, unknown>
  variants: VariantView[]
}

export interface PlanAssetView {
  id: number
  order: number
  purpose: string
  kind: string
  depends_on: number[]
  family: string | null
  provider: string | null
  prompt: string | null
  params: Record<string, unknown>
  status: string
  locked: boolean
  generation_id: number | null
  cost_estimate: number | null
  error: string | null
  output_post_id: number | null
  thumb_url: string | null
}

export interface PlanView {
  id: number
  name: string
  brief: string | null
  status: string
  meta: Record<string, unknown>
  estimated_total: number
  assets: PlanAssetView[]
}

export interface WfNode { id: string; type: string; config: Record<string, unknown> }
export interface WfEdge { from: string; to: string; when?: string }
export interface WfGraph { nodes: WfNode[]; edges: WfEdge[] }
export interface WorkflowView {
  id: number
  name: string
  description: string | null
  graph: WfGraph
  validation?: { ok: boolean; errors: string[]; order: string[] }
  availability?: { id: string; type: string; supported: boolean; reason: string | null }[]
}
export interface WorkflowRunView {
  id: number
  workflow_id: number
  status: string
  inputs: Record<string, unknown>
  node_states: Record<string, { status?: string; output?: Record<string, unknown>; error?: string }>
  error: string | null
}

export interface UsageReport {
  totals: { generations: number; succeeded: number; failed: number; fallbacks: number; estimated_spend: number; recorded_spend: number }
  by_provider_spend: Record<string, number>
  models: { provider: string; family: string; attempts: number; succeeded: number; failed: number; est_cost: number; actual_cost: number; success_rate: number | null; avg_latency_s: number | null; avg_score: number | null; score_per_dollar: number | null; fallbacks_in: number }[]
  recent: { id: number; provider: string; family: string | null; status: string; cost: number | null; tool: string | null; fallback_of: number | null; created_at: string | null }[]
}

export const forge = {
  models: (modality?: string) =>
    api.get<{ models: ModelEntry[]; providers: ProviderInfo[] }>(
      `/api/forge/models${modality ? `?modality=${modality}` : ''}`),
  route: (body: { brief?: string; intent?: Record<string, unknown>; family?: string; provider?: string; connected_only?: boolean }) =>
    api.post<RouteResult>('/api/forge/route', body),
  compile: (body: { idea?: string; package?: PromptPackage; family?: string; provider?: string; params?: Record<string, unknown>; use_llm?: boolean }) =>
    api.post<PromptPackage>('/api/forge/compile', body),
  tools: () => api.get<{ tools: ToolInfo[] }>('/api/forge/tools'),
  invokeTool: (name: string, body: Record<string, unknown>) =>
    api.post<{ job_id: number; status: string; estimate: number | null; warnings: string[] }>(`/api/forge/tools/${name}`, body),
  job: (id: number) => api.get<JobStatus>(`/api/forge/jobs/${id}`),
  experiments: () => api.get<{ experiments: { id: number; name: string; brief: string | null; variant_count: number }[] }>('/api/forge/experiments'),
  experiment: (id: number) => api.get<ExperimentView>(`/api/forge/experiments/${id}`),
  createExperiment: (name: string, brief?: string) =>
    api.post<ExperimentView>('/api/forge/experiments', { name, brief }),
  addVariant: (expId: number, body: Record<string, unknown>) =>
    api.post<ExperimentView>(`/api/forge/experiments/${expId}/variants`, body),
  forkVariant: (variantId: number, changes: Record<string, unknown>, label?: string) =>
    api.post<ExperimentView>(`/api/forge/variants/${variantId}/fork`, { changes, label }),
  runVariant: (variantId: number, allowFallback = false) =>
    api.post<{ run_id: number; generation_id: number; status: string }>(`/api/forge/variants/${variantId}/run`, { allow_fallback: allowFallback }),
  scoreRun: (runId: number, body: { score?: number; notes?: string; winner?: boolean }) =>
    api.post(`/api/forge/runs/${runId}/score`, body),
  evaluators: () => api.get<{ backends: { kind: string; name: string; detail: string }[]; vision_available: boolean; reason: string | null }>('/api/forge/evaluators'),
  nodeTypes: () => api.get<{ node_types: { type: string; label: string; category: string; supported: boolean; reason?: string; ports: { in: string[]; out: string[] } }[] }>('/api/forge/workflow-node-types'),
  refineRun: (runId: number, useLlm = false) =>
    api.post<{ evaluation: EvaluationView; proposal: { prompt: string; negative: string | null; diff: { op: string; text: string }[]; changes: string[]; unchanged: boolean }; new_variant_id: number | null }>(`/api/forge/runs/${runId}/refine`, { use_llm: useLlm }),
  plans: () => api.get<{ plans: { id: number; name: string; status: string; asset_count: number }[] }>('/api/forge/plans'),
  plan: (id: number) => api.get<PlanView>(`/api/forge/plans/${id}`),
  createPlan: (brief: string, useLlm = false) => api.post<PlanView>('/api/forge/plans', { brief, use_llm: useLlm }),
  editPlanAsset: (planId: number, assetId: number, body: Record<string, unknown>) =>
    api.patch<PlanView>(`/api/forge/plans/${planId}/assets/${assetId}`, body),
  runPlan: (planId: number, onlyFailed = false) =>
    api.post<{ queued: { id: number; purpose: string; job_id: number }[]; blocked: { purpose: string; reason: string }[]; skipped: unknown[] }>(`/api/forge/plans/${planId}/run`, { only_failed: onlyFailed }),
  runPlanAsset: (planId: number, assetId: number) =>
    api.post(`/api/forge/plans/${planId}/assets/${assetId}/run`, {}),
  forkPlan: (planId: number) => api.post<PlanView>(`/api/forge/plans/${planId}/fork`, {}),
  workflows: () => api.get<{ workflows: { id: number; name: string; description: string | null; node_count: number; run_count: number }[]; templates: { key: string; name: string; description: string }[] }>('/api/forge/workflows'),
  workflow: (id: number) => api.get<WorkflowView>(`/api/forge/workflows/${id}`),
  createWorkflow: (body: { name: string; description?: string; graph: WfGraph }) =>
    api.post<{ id: number }>('/api/forge/workflows', body),
  updateWorkflow: (id: number, body: { name?: string; graph?: WfGraph }) =>
    api.put<{ id: number; availability: WorkflowView['availability'] }>(`/api/forge/workflows/${id}`, body),
  fromTemplate: (key: string) => api.post<WorkflowView>(`/api/forge/workflows/from-template/${key}`, {}),
  startRun: (workflowId: number, inputs: Record<string, unknown>) =>
    api.post<WorkflowRunView>(`/api/forge/workflows/${workflowId}/run`, { inputs }),
  workflowRun: (runId: number, tick = false) =>
    api.get<WorkflowRunView>(`/api/forge/workflow-runs/${runId}${tick ? '?tick=true' : ''}`),
  approveNode: (runId: number, nodeId: string) =>
    api.post<WorkflowRunView>(`/api/forge/workflow-runs/${runId}/approve`, { node_id: nodeId }),
  usage: () => api.get<UsageReport>('/api/forge/usage'),
}

// ---------------------------------------------------------- pure helpers ---
/** Topological columns for the workflow editor's auto layout. */
export function layoutColumns(graph: WfGraph): string[][] {
  const incoming = new Map<string, Set<string>>()
  graph.nodes.forEach((n) => incoming.set(n.id, new Set()))
  graph.edges.forEach((e) => incoming.get(e.to)?.add(e.from))
  const placed = new Set<string>()
  const columns: string[][] = []
  let guard = 0
  while (placed.size < graph.nodes.length && guard++ < 50) {
    const col = graph.nodes
      .filter((n) => !placed.has(n.id))
      .filter((n) => [...(incoming.get(n.id) ?? [])].every((d) => placed.has(d)))
      .map((n) => n.id)
    if (col.length === 0) break // cycle — validation reports it
    col.forEach((id) => placed.add(id))
    columns.push(col)
  }
  return columns
}

/** Chip text for a model's capability badges, from real flags only. */
export function capabilityBadges(m: ModelEntry): string[] {
  const badges: string[] = [m.modality]
  if (m.availability === 'both') badges.push('open weights')
  if (m.supports.reference_images) badges.push('references')
  if (m.supports.image_to_image) badges.push('img2img')
  if (m.supports.start_end_frames) badges.push('start/end frames')
  if (m.supports.character_consistency) badges.push('consistency')
  if (m.supports.negative_prompt) badges.push('negative prompt')
  if (m.supports.audio) badges.push('audio')
  if (m.max_duration_s) badges.push(`≤${m.max_duration_s}s`)
  return badges
}

export function fmtUsd(v: number | null | undefined): string {
  if (v == null) return '—'
  return v >= 0.1 ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`
}
