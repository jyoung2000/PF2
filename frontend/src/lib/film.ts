// Film Studio client (S4): types + helpers for /api/film. Shapes mirror the
// dict builders in backend/promptforge/film/*. Multipart uploads go through
// `upload()`; everything else through the shared JSON client.
import { api, ApiError } from '../api'
import { InspirationContext } from './inspiration'

// ---------------------------------------------------------------- types ----
export type AssetType = 'character' | 'location' | 'prop' | 'vehicle' | 'outfit' | 'style'
export const ASSET_TYPES: AssetType[] = ['character', 'location', 'prop', 'vehicle', 'outfit', 'style']

export interface SchemaField { key: string; label: string; type: string; options?: string[]; asset_type?: string }
export interface SchemaSection { key: string; label: string; fields: SchemaField[] }
export interface LockGroup { key: string; label: string; default: boolean; fields: string[]; shot_level?: boolean }
export interface AssetSchema {
  label: string
  plural: string
  sections: SchemaSection[]
  lock_groups: LockGroup[]
  ref_kinds: string[]
  children?: string
  parent?: string
}
export interface FilmSchema {
  asset_types: AssetType[]
  schemas: Record<AssetType, AssetSchema>
  media_strategies: string[]
  transition_kinds: string[]
  shot_statuses: string[]
  project_statuses: string[]
  default_settings: ProjectSettings
}

export interface AssetRef {
  id: number
  asset_id: number
  version_id: number | null
  kind: string
  label: string | null
  url: string | null
  thumb_url: string | null
  width: number | null
  height: number | null
  source: string
  source_post_id: number | null
  provenance: Record<string, unknown>
  created_at: string | null
}
export interface AssetVersion {
  id: number
  asset_id: number
  number: number
  label: string
  data: Record<string, unknown>
  locks: string[]
  identity_anchors: string[]
  continuity_rules: string[]
  negative_constraints: string[]
  primary_ref_id: number | null
  primary_thumb_url: string | null
  frozen: boolean
  provenance: Record<string, unknown>
  note: string | null
  refs: AssetRef[]
  usage?: { shots: number[]; takes: number[]; scenes: number[]; in_use: boolean }
  created_at: string | null
  updated_at: string | null
}
export interface Asset {
  id: number
  type: AssetType
  name: string
  description: string | null
  tags: string[]
  notes: string | null
  favorite: boolean
  pinned: boolean
  approved: boolean
  project_id: number | null
  owner_asset_id: number | null
  provenance: Record<string, unknown>
  current_version_id: number
  current_version: AssetVersion
  version_count: number
  ref_count: number
  thumb_url: string | null
  outfits?: Asset[]
  versions?: AssetVersion[]
  usage?: { shots: { shot_id: number; scene_id: number; project_id: number; title: string | null; version_id: number }[]; scene_ids: number[]; project_ids: number[]; in_use: boolean }
  context?: AssetContext
  created_at: string | null
  updated_at: string | null
}
export interface AssetContext {
  asset_id: number
  version_id: number
  version: number
  version_label: string
  type: AssetType
  name: string
  identity_anchors: string[]
  visual_description: Record<string, unknown>
  references: { id: number; kind: string; url: string | null; thumb_url: string | null; primary: boolean }[]
  locked_groups: string[]
  locked_attributes: { group: string; field: string; label: string; value: unknown }[]
  variable_attributes: { field: string; label: string; value: unknown; group: string | null }[]
  continuity_rules: string[]
  negative_constraints: string[]
}
export interface AssetTool { key: string; label: string; mode: string; what?: string; supported: boolean; reason: string | null; families: string[] }

export interface ProjectSettings {
  aspect_ratio: string
  fps: number
  target_runtime_s: number
  default_scene_gap_s: number
  default_transition: { kind: string; duration_s: number }
  pacing_profile: string
  continuity_mode: 'flexible' | 'balanced' | 'strict'
  budget: { mode: 'observe' | 'warn' | 'approve' | 'cap'; threshold_usd: number | null; cap_usd: number | null }
  pipeline_template: string
  chain_frames: boolean
  visual_style: string
  tone: string
  audience: string
  objective: string
  [k: string]: unknown
}
export interface Take {
  id: number
  shot_id: number
  number: number
  kind: string
  status: string
  mode: string | null
  generation_id: number | null
  provider: string | null
  model_family: string | null
  prompt: string | null
  negative: string | null
  params: Record<string, unknown>
  context: Record<string, unknown>
  decision: { selected?: Record<string, unknown>; reason?: string; basis?: string; alternatives?: Record<string, unknown>[]; user_override?: boolean }
  cost_estimate: number | null
  cost_actual: number | null
  duration_s: number | null
  media_url: string | null
  thumb_url: string | null
  width: number | null
  height: number | null
  post_id: number | null
  qa: QaResult | null
  review: { status: 'approved' | 'rejected'; note?: string | null; at?: string; actor?: string } | null
  error: string | null
  created_at: string | null
  finished_at: string | null
}
export interface QaCheck { key: string; status: 'PASS' | 'WARN' | 'FAIL'; message: string; heuristic: boolean }
export interface QaResult { verdict: 'PASS' | 'WARN' | 'FAIL'; checks: QaCheck[]; [k: string]: unknown }
export interface Frame { kind: string; path: string | null; take_id?: number | null; source_shot_id?: number | null; locked?: boolean; post_id?: number | null; ref_id?: number | null }
export interface EffectiveAsset { asset_id: number; version_id: number; role: string; source: 'scene' | 'shot'; name: string; type: AssetType; version: number; version_label: string; is_current: boolean; thumb_url: string | null }
export interface Warning { kind: string; severity: 'info' | 'warn' | 'block'; message: string; shot_ids: number[]; heuristic: boolean; fix?: string | null; overridden?: boolean }
export interface Shot {
  id: number
  project_id: number
  scene_id: number
  position: number
  number: number
  label: string
  title: string | null
  status: string
  duration_s: number
  transition: { kind: string; duration_s: number } | null
  media_strategy: string
  overrides: Record<string, any>
  locks: string[]
  start_frame: Frame | null
  end_frame: Frame | null
  chain_from_previous: boolean
  selected_take_id: number | null
  selected_take: Take | null
  approved: boolean
  qa: QaResult | null
  warnings: Warning[]
  notes: string | null
  assets: EffectiveAsset[]
  take_count: number
  thumb_url: string | null
  takes?: Take[]
}
export interface Scene {
  id: number
  project_id: number
  position: number
  number: number
  act: string | null
  title: string
  intent: string | null
  summary: string | null
  script_text: string | null
  defaults: Record<string, any>
  gap_after_s: number | null
  transition: { kind: string; duration_s: number } | null
  approved: boolean
  shots: Shot[]
}
export interface Project {
  id: number
  title: string
  logline: string | null
  synopsis: string | null
  script: string | null
  status: string
  settings: ProjectSettings
  plan: Record<string, any>
  reference: Record<string, any>
  scene_count: number
  shot_count: number
  scenes?: Scene[]
  created_at: string | null
  updated_at: string | null
}
export interface Presets {
  shot_types: ShotType[]
  lenses: { key: string; label: string; mm: number; fov_deg: number; depth: string; macro?: boolean }[]
  camera_moves: { key: string; label: string; what: string; speed: string | null }[]
  move_speeds: string[]
  angles: string[]
  shot_sizes: string[]
  lighting_presets: LightingPreset[]
  pacing_profiles: Record<string, { label: string; base_s: number; min_s: number; max_s: number }>
  pipeline_templates: Record<string, { label: string; media_strategy: string; pacing_profile: string; audio: string[]; aspect_ratio: string; default_scene_gap_s: number }>
  transitions: { key: string; label: string; duration_s: number }[]
  favorites: string[]
}
export interface ShotType {
  key: string
  label: string
  abbr: string
  what: string
  use: string
  camera: { shot_size: string; angle: string; lens_mm: number; height_m: number; movement: string }
  figure: number
  figures?: number
  foreground?: boolean
  object?: boolean
  tilt_deg?: number
  favorite?: boolean
  customized?: boolean
  custom?: boolean
}
export interface LightingPreset {
  key: string
  label: string
  key_intensity: number
  fill_intensity: number
  rim_intensity: number
  direction: string
  color_temp_k: number
  contrast: string
  ambient: number
  practicals: string
  mood: string
}
export interface Proposal {
  id: number
  kind: string
  project_id: number
  stage: string | null
  target: Record<string, number>
  proposal: any
  source: 'llm' | 'fallback' | null
  applied: boolean
  rejected: boolean
  applied_result: Record<string, unknown> | null
  note: string | null
  status: string
  created_at: string | null
}
export interface TimelineShot { id: number; label: string; title: string | null; start_s: number; end_s: number; duration_s: number; status: string; media_strategy: string; transition: { kind: string; duration_s: number } | null; tc_in: string; tc_out: string }
export interface TimelineScene { id: number; number: number; title: string; start_s: number; end_s: number; duration_s: number; tc_in: string; tc_out: string; gap_after_s: number | null; gap_inherited: boolean; transition: { kind: string; duration_s: number } | null; shot_count: number; shots: TimelineShot[]; approved: boolean }
export interface Timeline { project_id: number; runtime_s: number; runtime_tc: string; target_runtime_s: number; target_tc: string; default_scene_gap_s: number; default_transition: { kind: string; duration_s: number }; fps: number; scene_count: number; shot_count: number; scenes: TimelineScene[] }
export interface Gate { kind: string; label: string; scene_id: number | null; status: 'pending' | 'approved' | 'rejected'; stale: boolean; note: string | null; decided_at: string | null; order: number; invalidated?: Record<string, unknown> }
export interface BoardStage { key: string; label: string; status: string; current: string | null; progress: { done: number; total: number }; failures: number; waiting: string[]; cost: Record<string, number>; detail: string | null }
export interface Board { project_id: number; stages: BoardStage[]; jobs: Job[]; cost: { estimated_usd: number; actual_usd: number; budget: ProjectSettings['budget'] }; recent_events: FilmEvent[] }
export interface Job { id: number; project_id: number | null; kind: string; status: string; stage: string | null; progress: { done: number; total: number; current?: string | null }; checkpoint: Record<string, unknown>; payload: Record<string, any>; result: Record<string, any> | null; error: string | null; created_at: string | null; finished_at: string | null }
export interface FilmEvent { id: number; at: string | null; kind: string; stage: string | null; actor: string; entity_type: string | null; entity_id: number | null; title: string; reason: string | null; data: Record<string, any> }
export interface Capabilities {
  providers: Record<string, { label: string; connected: boolean; key_url: string }>
  modes: { key: string; label: string; kind: string; needs: string[]; supported: boolean; families: string[]; reason: string | null }[]
  extra: Record<string, { supported: boolean; reason: string }>
  local: Record<string, { supported: boolean; what: string }>
  ffmpeg: boolean
}
export interface Spend { estimated_usd: number; actual_usd: number; reserved_usd: number; spent_usd: number; committed_usd: number; remaining_usd: number | null; by_scene: Record<string, number>; by_shot: Record<string, number>; by_provider: Record<string, number>; budget: ProjectSettings['budget']; unknown_takes: number }
export interface ShotContext { context: Record<string, any>; prompt: { prompt: string; negative: string; constraints: string[]; locks: string[] } }
export interface AudioTrack { id: number; kind: string; label: string | null; url: string | null; source: string; anchor_kind: string; anchor_id: number | null; offset_s: number; duration_s: number | null; gain_db: number; muted: boolean; loop: boolean; fade_in_s: number; fade_out_s: number; start_s?: number | null; end_s?: number | null; orphaned?: boolean }
export interface Subtitles { id?: number; cues: { id: number; start_s: number; end_s: number; text: string; shot_id?: number }[]; style: Record<string, any>; source: string | null; burn_in: boolean; language: string; validation?: { status: string; message: string; cues: number } }
export interface Clip { id: number; source: string; source_id: string; url: string | null; title: string | null; description: string | null; license: { name: string; url: string | null } | null; media_type: string; duration_s: number | null; width: number | null; height: number | null; file_url: string | null; thumb_url: string | null; segments: { index: number; start_s: number; end_s: number; duration_s: number; thumb?: string }[]; pacing: Record<string, number> | null; notes: Record<string, string> }
export interface FootageResult { source: string; source_id: string; url: string | null; page_url: string | null; title: string | null; description: string | null; media_type: string; download_url: string; thumb_url: string | null; duration_s: number | null; width: number | null; height: number | null; license: { name: string; url: string | null } | null; attribution: string | null }

export type ShotPatch = Omit<Partial<Shot>, 'assets' | 'transition'> & { assets?: { asset_id: number; version_id?: number | null; role?: string }[]; transition?: { kind: string; duration_s: number } | string | null }

// --------------------------------------------------------------- helpers ---
export async function upload<T>(path: string, file: File, fields: Record<string, string | number | boolean | null | undefined> = {}): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== null) form.append(k, String(v))
  const resp = await fetch(path, { method: 'POST', body: form })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = await resp.json()
      detail = typeof body.detail === 'string' ? body.detail : body.detail?.message ?? JSON.stringify(body.detail)
    } catch {
      /* keep statusText */
    }
    throw new ApiError(resp.status, detail)
  }
  return (await resp.json()) as T
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message
  return e instanceof Error ? e.message : String(e)
}

export const fmtTc = (s: number | null | undefined) => {
  const v = Math.max(0, s ?? 0)
  const h = Math.floor(v / 3600)
  const m = Math.floor((v % 3600) / 60)
  const sec = v % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${sec.toFixed(1).padStart(4, '0')}`
}
export const fmtUsd = (v: number | null | undefined) => (v == null ? '—' : `$${v.toFixed(v < 1 ? 3 : 2)}`)

// ----------------------------------------------------------------- api -----
const F = '/api/film'
export const film = {
  schema: () => api.get<FilmSchema>(`${F}/schema`),
  presets: () => api.get<Presets>(`${F}/presets`),
  savePresets: (body: { favorites?: string[]; shot_type_overrides?: Record<string, unknown>; custom_shot_types?: unknown[] }) =>
    api.put<Presets>(`${F}/presets`, body),
  capabilities: () => api.get<Capabilities>(`${F}/capabilities`),
  // assets
  listAssets: (q: { type?: string; q?: string; project_id?: number; favorite?: boolean; owner_asset_id?: number } = {}) => {
    const p = new URLSearchParams()
    for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
    return api.get<{ assets: Asset[] }>(`${F}/assets?${p.toString()}`)
  },
  getAsset: (id: number) => api.get<Asset>(`${F}/assets/${id}`),
  createAsset: (body: Partial<Asset> & { type: AssetType; name: string; data?: Record<string, unknown>; locks?: string[] }) =>
    api.post<Asset>(`${F}/assets`, body),
  patchAsset: (id: number, body: Partial<Pick<Asset, 'name' | 'description' | 'tags' | 'notes' | 'favorite' | 'pinned' | 'approved' | 'project_id'>>) =>
    api.patch<Asset>(`${F}/assets/${id}`, body),
  deleteAsset: (id: number, force = false) => api.delete<{ deleted: number }>(`${F}/assets/${id}?force=${force}`),
  editVersion: (id: number, body: { changes?: Record<string, unknown>; locks?: string[]; continuity_rules?: string[]; negative_constraints?: string[]; identity_anchors?: string[]; label?: string; note?: string; new_version?: boolean; reason?: string }) =>
    api.post<{ created: boolean; version: AssetVersion; asset: Asset }>(`${F}/assets/${id}/versions`, body),
  versionAction: (id: number, vid: number, action: 'restore' | 'duplicate' | 'use') =>
    api.post<{ version: AssetVersion; asset: Asset }>(`${F}/assets/${id}/versions/${vid}/${action}`),
  compareVersions: (id: number, a: number, b: number) => api.get<any>(`${F}/assets/${id}/compare?a=${a}&b=${b}`),
  assetContext: (id: number, versionId?: number) =>
    api.get<{ context: AssetContext; prose: string }>(`${F}/assets/${id}/context${versionId ? `?version_id=${versionId}` : ''}`),
  propagate: (id: number, body: { version_id: number; scope: 'selected' | 'future' | 'project'; project_id?: number; shot_ids?: number[]; from_shot_id?: number }) =>
    api.post<{ version_id: number; updated_shots: number[]; updated_scenes: number[] }>(`${F}/assets/${id}/propagate`, body),
  uploadRef: (id: number, file: File, fields: { kind?: string; label?: string; version_id?: number; primary?: boolean }) =>
    upload<{ ref: AssetRef; deduped: boolean }>(`${F}/assets/${id}/refs`, file, fields),
  importRef: (id: number, body: { post_id: number; kind?: string; label?: string; primary?: boolean }) =>
    api.post<{ ref: AssetRef; deduped: boolean }>(`${F}/assets/${id}/refs/import`, body),
  patchRef: (rid: number, body: { kind?: string; label?: string }) => api.patch<AssetRef>(`${F}/refs/${rid}`, body),
  primaryRef: (rid: number) => api.post<{ version_id: number; primary_ref_id: number }>(`${F}/refs/${rid}/primary`),
  deleteRef: (rid: number) => api.delete<{ deleted: number }>(`${F}/refs/${rid}`),
  assetTools: (id: number) => api.get<{ tools: AssetTool[]; generations: any[] }>(`${F}/assets/${id}/tools`),
  assetGenerate: (id: number, body: { tool: string; instruction?: string; family?: string; provider?: string; strength?: number; kind?: string }) =>
    api.post<{ generation_id: number; provider: string; family: string; mode: string; estimate_usd: number | null; prompt: string }>(`${F}/assets/${id}/generate`, body),
  // projects / structure
  listProjects: () => api.get<{ projects: Project[] }>(`${F}/projects`),
  createProject: (body: { title: string; logline?: string; synopsis?: string; script?: string; settings?: Partial<ProjectSettings> }) =>
    api.post<Project>(`${F}/projects`, body),
  getProject: (id: number) => api.get<Project>(`${F}/projects/${id}`),
  patchProject: (id: number, body: { title?: string; logline?: string; synopsis?: string; script?: string; status?: string; settings?: Partial<ProjectSettings> }) =>
    api.patch<Project>(`${F}/projects/${id}`, body),
  deleteProject: (id: number) => api.delete<{ deleted: number }>(`${F}/projects/${id}`),
  events: (id: number, kind?: string, limit = 200) => api.get<{ events: FilmEvent[] }>(`${F}/projects/${id}/events?limit=${limit}${kind ? `&kind=${kind}` : ''}`),
  importScript: (id: number, text: string, mode: 'replace' | 'append' = 'replace') =>
    api.post<{ project: Project; scene_ids: number[] }>(`${F}/projects/${id}/story/import`, { text, mode }),
  parseScript: (text: string) => api.post<{ scenes: any[] }>(`${F}/story/parse`, { text }),
  createScene: (pid: number, body: Partial<Scene>) => api.post<Scene>(`${F}/projects/${pid}/scenes`, body),
  patchScene: (id: number, body: Partial<Scene> & { transition?: unknown }) => api.patch<Scene>(`${F}/scenes/${id}`, body),
  deleteScene: (id: number) => api.delete<{ deleted: number }>(`${F}/scenes/${id}`),
  reorderScenes: (pid: number, ids: number[]) => api.post<{ scenes: Scene[] }>(`${F}/projects/${pid}/scenes/reorder`, { ids }),
  getScene: (id: number) => api.get<Scene>(`${F}/scenes/${id}`),
  createShot: (sid: number, body: ShotPatch) => api.post<Shot>(`${F}/scenes/${sid}/shots`, body),
  patchShot: (id: number, body: ShotPatch) => api.patch<Shot>(`${F}/shots/${id}`, body),
  getShot: (id: number) => api.get<Shot>(`${F}/shots/${id}`),
  deleteShot: (id: number) => api.delete<{ deleted: number }>(`${F}/shots/${id}`),
  duplicateShot: (id: number) => api.post<Shot>(`${F}/shots/${id}/duplicate`),
  moveShot: (id: number, scene_id: number, position?: number) => api.post<Shot>(`${F}/shots/${id}/move`, { scene_id, position }),
  reorderShots: (sid: number, ids: number[]) => api.post<{ shots: Shot[] }>(`${F}/scenes/${sid}/shots/reorder`, { ids }),
  pinAsset: (shotId: number, body: { asset_id: number; version_id?: number; role?: string }) => api.post<Shot>(`${F}/shots/${shotId}/assets`, body),
  unpinAsset: (shotId: number, assetId: number) => api.delete<{ removed: boolean; shot: Shot }>(`${F}/shots/${shotId}/assets/${assetId}`),
  shotContext: (id: number, kind = 'video') => api.get<ShotContext>(`${F}/shots/${id}/context?kind=${kind}`),
  regenPrompt: (id: number, body: { change: string[]; preserve: string[]; instruction?: string }) => api.post<any>(`${F}/shots/${id}/context/regeneration`, body),
  // director
  directStory: (pid: number, use_llm = true) => api.post<Proposal>(`${F}/projects/${pid}/director/story`, { use_llm }),
  directPlan: (pid: number, use_llm = true) => api.post<Proposal>(`${F}/projects/${pid}/director/plan`, { use_llm }),
  directScene: (sid: number, use_llm = true) => api.post<Proposal>(`${F}/scenes/${sid}/director`, { use_llm }),
  directShot: (id: number, instruction: string, use_llm = true) => api.post<Proposal>(`${F}/shots/${id}/director`, { instruction, use_llm }),
  proposals: (pid: number, pending = false) => api.get<{ proposals: Proposal[] }>(`${F}/projects/${pid}/proposals?pending=${pending}`),
  acceptProposal: (id: number, body: { edits?: Record<string, unknown>; mode?: 'append' | 'replace' } = {}) =>
    api.post<{ result: Record<string, unknown>; proposal: Proposal }>(`${F}/proposals/${id}/accept`, body),
  rejectProposal: (id: number, note?: string) => api.post<Proposal>(`${F}/proposals/${id}/reject`, { note }),
  putPlan: (pid: number, plan: Record<string, unknown>) => api.put<Project>(`${F}/projects/${pid}/plan`, { plan }),
  estimate: (pid: number) => api.get<any>(`${F}/projects/${pid}/estimate`),
  // timeline / continuity / gates / board
  timeline: (pid: number) => api.get<Timeline>(`${F}/projects/${pid}/timeline`),
  setGap: (pid: number, body: { default_gap_s?: number; apply_to_all?: number; reset_overrides?: boolean }) => api.post<Timeline>(`${F}/projects/${pid}/timeline/gap`, body),
  setSceneGap: (sid: number, gap_after_s: number | null) => api.post<Timeline>(`${F}/scenes/${sid}/gap`, { gap_after_s }),
  continuity: (pid: number) => api.post<{ mode: string; counts: Record<string, number>; blocking: boolean; warnings: Warning[]; by_shot: Record<string, Warning[]> }>(`${F}/projects/${pid}/continuity`),
  gates: (pid: number) => api.get<{ gates: Gate[] }>(`${F}/projects/${pid}/gates`),
  decideGate: (pid: number, kind: string, body: { status: 'approved' | 'rejected' | 'pending'; scene_id?: number; note?: string; item_ids?: number[] }) =>
    api.post<Gate>(`${F}/projects/${pid}/gates/${kind}`, body),
  board: (pid: number) => api.get<Board>(`${F}/projects/${pid}/board`),
  replay: (pid: number) => api.get<{ events: FilmEvent[]; count: number }>(`${F}/projects/${pid}/replay`),
  jobs: (pid: number) => api.get<{ jobs: Job[] }>(`${F}/projects/${pid}/jobs`),
  job: (id: number) => api.get<Job>(`${F}/jobs/${id}`),
  jobAction: (id: number, action: 'pause' | 'resume' | 'cancel') => api.post<Job>(`${F}/jobs/${id}/${action}`),
  // takes / frames / local media
  createTake: (shotId: number, body: { kind?: string; mode?: string; family?: string; provider?: string; params?: Record<string, unknown>; change?: string[]; preserve?: string[]; instruction?: string; approve_cost?: boolean }) =>
    api.post<{ take: Take; shot: Shot }>(`${F}/shots/${shotId}/takes`, body),
  takes: (shotId: number) => api.get<{ takes: Take[]; selected_take_id: number | null }>(`${F}/shots/${shotId}/takes`),
  importTake: (shotId: number, file: File, kind = 'footage') => upload<{ take: Take; shot: Shot }>(`${F}/shots/${shotId}/takes/import`, file, { kind }),
  selectTake: (id: number) => api.post<Shot>(`${F}/takes/${id}/select`),
  reviewTake: (id: number, status: 'approved' | 'rejected' | null, note?: string) =>
    api.post<{ take: Take }>(`${F}/takes/${id}/review`, { status, note }),
  reviewQueue: (pid: number) => api.get<{ pending: any[]; decided: any[]; failed: any[]; counts: { pending: number; failed: number } }>(`${F}/projects/${pid}/review-queue`),
  compareTakes: (a: number, b: number) => api.get<any>(`${F}/takes/${a}/compare/${b}`),
  takeQa: (id: number) => api.post<QaResult>(`${F}/takes/${id}/qa`),
  setFrame: (shotId: number, which: 'start_frame' | 'end_frame', body: { kind: string; post_id?: number; ref_id?: number; locked?: boolean }) =>
    api.post<Shot>(`${F}/shots/${shotId}/frames/${which}`, body),
  uploadFrame: (shotId: number, which: 'start_frame' | 'end_frame', file: File) => upload<Shot>(`${F}/shots/${shotId}/frames/${which}/upload`, file),
  generateFrame: (shotId: number, which: 'start_frame' | 'end_frame', body: Record<string, unknown> = {}) =>
    api.post<{ take: Take; shot: Shot }>(`${F}/shots/${shotId}/frames/${which}/generate`, body),
  still: (shotId: number, body: { source: string; post_id?: number; ref_id?: number }) => api.post<{ take: Take; shot: Shot }>(`${F}/shots/${shotId}/still`, body),
  card: (shotId: number, body: { text: string; subtitle?: string; style?: string; background_post_id?: number; background_ref_id?: number }) =>
    api.post<{ take: Take; shot: Shot }>(`${F}/shots/${shotId}/card`, body),
  // footage
  footageSources: () => api.get<{ sources: { key: string; label: string; configured: boolean; media: string[]; needs_key: boolean; key_setting: string | null; key_url: string | null }[] }>(`${F}/footage/sources`),
  footageSearch: (q: string, media_type = 'video', sources?: string[]) =>
    api.get<{ query: string; results: FootageResult[]; errors: Record<string, string>; needs_setup: string[] }>(`${F}/footage/search?q=${encodeURIComponent(q)}&media_type=${media_type}${sources?.length ? `&sources=${sources.join(',')}` : ''}`),
  footageAttach: (shot_id: number, result: FootageResult) => api.post<{ clip: Clip; take: Take; shot: Shot }>(`${F}/footage/attach`, { shot_id, result }),
  footageUpload: (file: File, fields: { project_id?: number; title?: string; description?: string; tags?: string }) => upload<Clip>(`${F}/footage/upload`, file, fields),
  clips: (q?: string, project_id?: number) => api.get<{ clips?: Clip[]; results?: any[] }>(`${F}/footage/clips?${q ? `q=${encodeURIComponent(q)}&` : ''}${project_id ? `project_id=${project_id}` : ''}`),
  clipAttach: (clipId: number, body: { shot_id: number; start_s?: number; end_s?: number }) => api.post<{ take: Take; shot: Shot }>(`${F}/footage/clips/${clipId}/attach`, body),
  // audio / subtitles
  audio: (pid: number) => api.get<{ tracks: AudioTrack[]; mix: any; capabilities: Record<string, { supported: boolean; reason: string }>; kinds: string[] }>(`${F}/projects/${pid}/audio`),
  addAudio: (pid: number, file: File, fields: { kind?: string; label?: string; anchor_kind?: string; anchor_id?: number; offset_s?: number; gain_db?: number }) =>
    upload<AudioTrack>(`${F}/projects/${pid}/audio`, file, fields),
  patchAudio: (id: number, body: Partial<AudioTrack>) => api.patch<AudioTrack>(`${F}/audio/${id}`, body),
  deleteAudio: (id: number) => api.delete<{ deleted: number }>(`${F}/audio/${id}`),
  subtitles: (pid: number) => api.get<Subtitles>(`${F}/projects/${pid}/subtitles`),
  putSubtitles: (pid: number, body: { cues?: unknown[]; style?: Record<string, unknown>; burn_in?: boolean; language?: string }) => api.put<Subtitles>(`${F}/projects/${pid}/subtitles`, body),
  subtitlesFromScript: (pid: number) => api.post<Subtitles>(`${F}/projects/${pid}/subtitles/from-script`),
  subtitlesImport: (pid: number, text: string) => api.post<Subtitles>(`${F}/projects/${pid}/subtitles/import`, { text }),
  subtitlesResync: (pid: number) => api.post<Subtitles>(`${F}/projects/${pid}/subtitles/resync`),
  // qa / runs / export / reference / costs
  qa: (pid: number) => api.get<any>(`${F}/projects/${pid}/qa`),
  repairs: (pid: number) => api.get<{ repairs: any[] }>(`${F}/projects/${pid}/repairs`),
  startRun: (pid: number, body: { kind?: string; scene_ids?: number[]; shot_ids?: number[]; sample?: boolean; force?: boolean; approve_cost?: boolean; skip_done?: boolean }) =>
    api.post<Job>(`${F}/projects/${pid}/runs`, body),
  sampleShots: (pid: number, scene_id?: number) => api.get<{ shots: Shot[] }>(`${F}/projects/${pid}/sample-shots${scene_id ? `?scene_id=${scene_id}` : ''}`),
  startExport: (pid: number, body: { label?: string; burn_in?: boolean; include_audio?: boolean; quality?: string; force?: boolean }) =>
    api.post<Job>(`${F}/projects/${pid}/export`, body),
  exports: (pid: number) => api.get<{ exports: Job[]; plan: any }>(`${F}/projects/${pid}/exports`),
  reference: (pid: number) => api.get<{ reference: Record<string, any>; yt_dlp: boolean }>(`${F}/projects/${pid}/reference`),
  referenceUpload: (pid: number, file: File) => upload<{ reference: Record<string, any> }>(`${F}/projects/${pid}/reference/upload`, file),
  referenceFrom: (pid: number, body: { post_id?: number; clip_id?: number; url?: string }) => api.post<{ reference: Record<string, any> }>(`${F}/projects/${pid}/reference`, body),
  referencePropose: (pid: number, use_llm = true) => api.post<Proposal>(`${F}/projects/${pid}/reference/propose`, { use_llm }),
  costs: (pid: number) => api.get<Spend>(`${F}/projects/${pid}/costs`),
}

// ------------------------------------------------- current project memory --
const PKEY = 'pf.film.project'
export function loadProjectId(): number | null {
  try {
    const v = localStorage.getItem(PKEY)
    return v ? Number(v) : null
  } catch {
    return null
  }
}
export function saveProjectId(id: number | null) {
  try {
    if (id == null) localStorage.removeItem(PKEY)
    else localStorage.setItem(PKEY, String(id))
  } catch {
    /* ignore */
  }
}

// ----------------------------------------- Inspiration → Film handoff ------
/** Shot overrides suggested by an Inspiration context (spec §25). Nothing is
 *  applied until the user accepts; provenance travels along. */
export function inspirationToShotPatch(ctx: InspirationContext): { overrides: Record<string, any>; summary: string[] } {
  const overrides: Record<string, any> = {}
  const summary: string[] = []
  const lens = ctx.camera.find((c) => /^\d+mm$/.test(c))
  const size = ctx.camera.find((c) => /(wide|close|medium|full|establishing|two shot|over-the-shoulder|pov|insert)/i.test(c))
  const angle = ctx.camera.find((c) => /(low angle|high angle|dutch|top-down|eye level)/i.test(c))
  const cam: Record<string, unknown> = {}
  if (lens) cam.lens_mm = Number(lens.replace('mm', ''))
  if (angle) cam.angle = angle.includes('low') ? 'low' : angle.includes('high') ? 'high' : angle.includes('dutch') ? 'dutch' : angle.includes('top') ? 'overhead' : 'eye_level'
  if (size) {
    const map: Record<string, string> = { 'extreme close-up': 'extreme_close_up', 'close-up': 'close_up', 'medium close-up': 'medium_close', 'medium shot': 'medium', 'medium wide': 'medium_wide', 'full shot': 'full', 'wide shot': 'wide', 'extreme wide': 'extreme_wide', establishing: 'establishing', 'two shot': 'two_shot', 'over-the-shoulder': 'over_shoulder', pov: 'pov', insert: 'insert' }
    const key = map[size.toLowerCase()]
    if (key) {
      overrides.shot_type = key
      summary.push(`shot type ${key.replace(/_/g, ' ')}`)
    }
  }
  if (Object.keys(cam).length) {
    overrides.camera = cam
    summary.push(`camera ${Object.entries(cam).map(([k, v]) => `${k.replace('_mm', '')} ${v}`).join(', ')}`)
  }
  if (ctx.lighting.length) {
    overrides.lighting = { mood: ctx.lighting.join(', ') }
    summary.push(`lighting ${ctx.lighting.join(', ')}`)
  }
  const styleBits = [ctx.style, ...ctx.composition].filter(Boolean)
  if (styleBits.length) {
    overrides.style = { visual_style: styleBits.join(', ') }
    summary.push(`style ${styleBits.join(', ')}`)
  }
  if (ctx.subject) {
    overrides.subject = ctx.subject
    summary.push(`subject ${ctx.subject}`)
  }
  if (ctx.techniques.length) {
    overrides.motion = { character_motion: ctx.techniques.map((t) => t.replace(/-/g, ' ')).join(', ') }
    summary.push(`techniques ${ctx.techniques.join(', ')}`)
  }
  overrides.inspiration = { post_id: ctx.post_id, platform: ctx.platform, source_url: ctx.source_url, author: ctx.author, captured_at: ctx.captured_at, prompt_structure: ctx.prompt_structure }
  return { overrides, summary }
}
