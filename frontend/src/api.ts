// Typed API client. Shapes mirror backend/promptforge/schemas.py.

export interface PostCard {
  id: number
  platform: string
  media_type: 'image' | 'video'
  media_url: string | null
  thumb_url: string | null
  width: number | null
  height: number | null
  duration_s: number | null
  prompt: string | null
  model_name: string | null
  model_family: string | null
  model_family_label: string | null
  favorite: boolean
  nsfw: boolean
  origin: 'scraped' | 'generated'
  posted_at: string | null
  scraped_at: string | null
}

export interface PostDetail extends PostCard {
  negative_prompt: string | null
  model_version: string | null
  params: Record<string, unknown>
  technique_tags: string[]
  tags: string[]
  collections: { id: number; name: string }[]
  author: string | null
  source_url: string | null
  original_media_url: string | null
  synced_to_baserow: boolean
  posted_to_discord: boolean
  original_bytes: number | null
  stored_bytes: number | null
}

export interface Page<T> {
  items: T[]
  next_cursor: number | null
  total?: number | null
}

export interface CollectionSummary {
  id: number
  name: string
  description: string | null
  model_family: string | null
  model_family_label: string | null
  allow_mixed_models: boolean
  count: number
  image_count?: number
  video_count?: number
  cover_urls: string[]
  created_at: string | null
}

export interface ModelFamilyMeta {
  family: string
  label: string
  post_count: number
  image_count: number
  video_count: number
  versions: string[]
  first_seen: string | null
  last_seen: string | null
  is_new: boolean
}

export interface ScraperInfo {
  name: string
  label: string
  tier: number
  experimental: boolean
  requires_auth: boolean
  status: 'ok' | 'needs_setup' | 'experimental' | 'error'
  status_detail: string | null
  enabled: boolean
  interval_minutes: number
  min_interval_minutes: number
  last_run_at: string | null
  last_status: string | null
  last_error: string | null
  last_found: number
  last_new: number
  next_run_at: string | null
  running: boolean
  session_status?: 'valid' | 'expired' | 'missing' | 'unknown' | null
}

export interface Suggestions {
  models: { family: string; label: string; count: number }[]
  tags: { name: string; count: number }[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = await resp.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* keep statusText */
    }
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '' && v !== false)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  return parts.length ? `?${parts.join('&')}` : ''
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export interface SearchParams {
  q?: string
  cursor?: number
  limit?: number
  platform?: string
  model?: string
  media_type?: string
  nsfw?: boolean
  favorite?: boolean
  origin?: string
  technique?: string
  collection_id?: number
  date_from?: string
  date_to?: string
}

export const searchPosts = (p: SearchParams) => api.get<Page<PostCard>>(`/api/search${qs(p as never)}`)
export const getSuggestions = (q: string) => api.get<Suggestions>(`/api/suggest${qs({ q })}`)
export const getPost = (id: number) => api.get<PostDetail>(`/api/posts/${id}`)
export const patchPost = (id: number, body: { favorite?: boolean; nsfw?: boolean }) =>
  api.patch<PostDetail>(`/api/posts/${id}`, body)
export const deletePost = (id: number) => api.delete<{ deleted: number }>(`/api/posts/${id}`)
export const addTag = (postId: number, name: string) =>
  api.post<{ tags: string[] }>(`/api/posts/${postId}/tags`, { name })
export const removeTag = (postId: number, name: string) =>
  api.delete<{ tags: string[] }>(`/api/posts/${postId}/tags/${encodeURIComponent(name)}`)
export const listTags = (q = '') => api.get<{ tags: { name: string; count: number }[] }>(`/api/tags${qs({ q })}`)
export const listScrapers = () => api.get<{ scrapers: ScraperInfo[] }>('/api/scrapers')

// ---- Collections ----
export const listCollections = () =>
  api.get<{ model_collections: CollectionSummary[]; user_collections: CollectionSummary[] }>(
    '/api/collections',
  )
export const getCollection = (id: number) => api.get<CollectionSummary>(`/api/collections/${id}`)
export const createCollection = (body: { name: string; description?: string }) =>
  api.post<CollectionSummary>('/api/collections', body)
export const updateCollection = (
  id: number,
  body: { name?: string; description?: string; allow_mixed_models?: boolean; cover_post_id?: number },
) => api.patch<CollectionSummary>(`/api/collections/${id}`, body)
export const deleteCollection = (id: number) => api.delete<{ deleted: number }>(`/api/collections/${id}`)
export const saveToCollection = (collectionId: number, postId: number) =>
  api.post<{ saved: boolean }>(`/api/collections/${collectionId}/posts/${postId}`)
export const removeFromCollection = (collectionId: number, postId: number) =>
  api.delete<{ removed: boolean }>(`/api/collections/${collectionId}/posts/${postId}`)
export const getModelsMeta = () => api.get<{ models: ModelFamilyMeta[] }>('/api/models/meta')
