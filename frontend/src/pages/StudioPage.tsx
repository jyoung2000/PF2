import { useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, ApiError } from '../api'
import { EmptyState, Modal, Spinner } from '../components/Primitives'
import { GeneratePanel } from '../components/GeneratePanel'
import { useDebounced, useFetch } from '../lib/hooks'
import { timeAgo } from '../lib/format'
import { toastError, toastSuccess } from '../lib/toast'

// ---------------------------------------------------------------- types ----
export interface TemplateSlot {
  key: string
  label: string
  type: 'text' | 'select' | 'chips' | 'slider'
  options?: string[]
  default?: string | string[]
  placeholder?: string
  required?: boolean
  min?: number
  max?: number
}

export interface StudioTemplate {
  id: number
  name: string
  version: number
  collection_id: number | null
  collection_name: string | null
  schema: { slots: TemplateSlot[]; video?: boolean; user_edited?: boolean }
  text_template: string
  ref_slots: { key: string; label: string; role: string; required: boolean }[]
  recommended_model: string | null
  recommended_model_label: string | null
  user_edited: boolean
  cover_urls: string[]
  updated_at: string | null
}

interface SavedPromptItem {
  kind: 'saved' | 'post'
  id: number
  text: string
  negative?: string | null
  model_family: string | null
  model_family_label: string | null
  origin: string
  starred: boolean
  thumb_url?: string | null
  created_at: string | null
  collection_id?: number | null
}

// ---------------------------------------------------------------- shell ----
const TABS = [
  { to: '/studio', label: 'Templates', end: true },
  { to: '/studio/enhance', label: 'Enhance', end: false },
  { to: '/studio/saved', label: 'Saved prompts', end: false },
]

export function StudioPage() {
  return (
    <div className="max-w-5xl mx-auto fade-in">
      <div className="text-center pt-4 pb-6">
        <h1 className="font-display font-bold text-[24px] tracking-tight">Prompt Studio</h1>
        <p className="text-[13px] text-faint mt-1">
          Create with learned templates, upscale any prompt, keep the good ones.
        </p>
        <nav className="inline-flex mt-4 border border-line rounded-el overflow-hidden" aria-label="Studio tabs">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                `px-4 py-1.5 text-[13px] transition-colors duration-fast ${
                  isActive ? 'bg-well text-fg font-medium' : 'text-mute hover:text-fg'
                }`
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <Routes>
        <Route path="/" element={<TemplatesTab />} />
        <Route path="/enhance" element={<EnhanceTab />} />
        <Route path="/saved" element={<SavedTab />} />
      </Routes>
    </div>
  )
}

// ------------------------------------------------------------ templates ----
function TemplatesTab() {
  const { data, loading, reload } = useFetch(() =>
    api.get<{ templates: StudioTemplate[] }>('/api/studio/templates'),
  )
  const [open, setOpen] = useState<StudioTemplate | null>(null)

  if (loading)
    return (
      <div className="flex justify-center py-16">
        <Spinner className="w-6 h-6" />
      </div>
    )
  const templates = data?.templates ?? []
  const byCollection = new Map<string, StudioTemplate[]>()
  for (const t of templates) {
    const key = t.collection_name ?? 'Unassigned'
    byCollection.set(key, [...(byCollection.get(key) ?? []), t])
  }

  return (
    <div className="space-y-6">
      {templates.length === 0 && (
        <EmptyState
          icon="▤"
          title="No templates yet"
          hint="Templates are generated from your collections' style profiles. Create a collection, save a few posts into it, and its template appears here."
        />
      )}
      {[...byCollection.entries()].map(([group, items]) => (
        <section key={group}>
          <h2 className="text-[12px] uppercase tracking-wide text-faint mb-2">{group}</h2>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {items.map((t) => (
              <button
                key={t.id}
                className="card overflow-hidden text-left group hover:border-mute/50 transition-colors duration-fast"
                onClick={() => setOpen(t)}
              >
                <div className="grid grid-cols-4 gap-px bg-line h-20 overflow-hidden">
                  {Array.from({ length: 4 }, (_, i) =>
                    t.cover_urls[i] ? (
                      <img key={i} src={t.cover_urls[i]} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <div key={i} className="bg-well" />
                    ),
                  )}
                </div>
                <div className="p-3">
                  <div className="flex items-center gap-2">
                    <h3 className="font-display font-medium text-[14px] truncate">{t.name}</h3>
                    {t.user_edited && <span className="chip !text-[10px]">edited</span>}
                  </div>
                  <p className="text-[11.5px] text-faint mt-0.5">
                    {t.recommended_model_label ?? 'any model'} · v{t.version} · updated {timeAgo(t.updated_at)}
                  </p>
                </div>
              </button>
            ))}
          </div>
        </section>
      ))}
      {open && <TemplateRunner template={open} onClose={() => setOpen(null)} onChanged={reload} />}
    </div>
  )
}

function TemplateRunner({
  template,
  onClose,
  onChanged,
}: {
  template: StudioTemplate
  onClose: () => void
  onChanged: () => void
}) {
  const [values, setValues] = useState<Record<string, string | string[]>>(() => {
    const initial: Record<string, string | string[]> = {}
    for (const slot of template.schema.slots ?? []) {
      if (slot.default !== undefined && slot.default !== '') initial[slot.key] = slot.default
    }
    return initial
  })
  const [refs, setRefs] = useState<Record<string, { ref_id: number; url: string }>>({})
  const [preview, setPreview] = useState('')
  const [editing, setEditing] = useState(false)
  const debouncedValues = useDebounced(values, 200)

  useEffect(() => {
    api
      .post<{ prompt: string }>(`/api/studio/templates/${template.id}/assemble`, { values: debouncedValues })
      .then((r) => setPreview(r.prompt))
      .catch(() => undefined)
  }, [debouncedValues, template.id])

  const setValue = (key: string, v: string | string[]) => setValues((prev) => ({ ...prev, [key]: v }))

  const uploadRef = async (slotKey: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    try {
      const resp = await fetch('/api/studio/refs', { method: 'POST', body: form })
      const body = await resp.json()
      if (!resp.ok) throw new Error(body.detail ?? 'Upload failed')
      setRefs((prev) => ({ ...prev, [slotKey]: { ref_id: body.ref_id, url: body.url } }))
      toastSuccess('Reference added')
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const savePrompt = async () => {
    if (!preview.trim()) return
    try {
      await api.post('/api/studio/prompts', {
        text: preview,
        model_family: template.recommended_model,
        collection_id: template.collection_id,
        template_id: template.id,
        origin: 'template',
        refs: Object.entries(refs).map(([slotKey, r]) => ({
          ref_id: r.ref_id,
          role: template.ref_slots.find((s) => s.key === slotKey)?.role ?? 'style',
        })),
      })
      toastSuccess('Saved to your prompts')
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const missingRequired = (template.schema.slots ?? [])
    .filter((s) => s.required && !String(values[s.key] ?? '').trim())
    .map((s) => s.label)

  return (
    <Modal title={template.name} onClose={onClose} wide>
      <div className="space-y-4">
        <p className="text-[12px] text-faint -mt-1">
          {template.recommended_model_label
            ? `Learned for ${template.recommended_model_label}`
            : 'Model-agnostic'}{' '}
          · from “{template.collection_name}” ·{' '}
          <button className="underline underline-offset-2 hover:text-fg" onClick={() => setEditing(true)}>
            edit template
          </button>
        </p>

        {(template.schema.slots ?? []).map((slot) => (
          <div key={slot.key}>
            <label className="label" htmlFor={`slot-${slot.key}`}>
              {slot.label}
              {slot.required && <span className="text-ember ml-1">*</span>}
            </label>
            {slot.type === 'text' && (
              <input
                id={`slot-${slot.key}`}
                className="input"
                placeholder={slot.placeholder}
                value={String(values[slot.key] ?? '')}
                onChange={(e) => setValue(slot.key, e.target.value)}
              />
            )}
            {slot.type === 'select' && (
              <select
                id={`slot-${slot.key}`}
                className="input"
                value={String(values[slot.key] ?? '')}
                onChange={(e) => setValue(slot.key, e.target.value)}
              >
                <option value="">— skip —</option>
                {(slot.options ?? []).map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            )}
            {slot.type === 'chips' && (
              <div className="flex flex-wrap gap-1.5">
                {(slot.options ?? []).map((o) => {
                  const selected = Array.isArray(values[slot.key]) && (values[slot.key] as string[]).includes(o)
                  return (
                    <button
                      key={o}
                      aria-pressed={selected}
                      className={`chip !text-[12px] transition-colors duration-fast ${
                        selected ? '!text-ember border-ember/60 bg-ember/10' : 'hover:border-mute/50'
                      }`}
                      onClick={() => {
                        const current = Array.isArray(values[slot.key]) ? (values[slot.key] as string[]) : []
                        setValue(slot.key, selected ? current.filter((x) => x !== o) : [...current, o])
                      }}
                    >
                      {o}
                    </button>
                  )
                })}
              </div>
            )}
            {slot.type === 'slider' && (
              <input
                id={`slot-${slot.key}`}
                type="range"
                min={slot.min ?? 1}
                max={slot.max ?? 10}
                className="w-full accent-[#FF6A3D]"
                value={Number(values[slot.key] ?? slot.default ?? 5)}
                onChange={(e) => setValue(slot.key, e.target.value)}
              />
            )}
          </div>
        ))}

        {template.ref_slots.length > 0 && (
          <div>
            <span className="label">Reference images</span>
            <div className="flex gap-2 flex-wrap">
              {template.ref_slots.map((slot) => (
                <label
                  key={slot.key}
                  className="w-24 h-24 border border-dashed border-line rounded-el flex flex-col items-center justify-center text-center cursor-pointer hover:border-mute/60 transition-colors duration-fast relative overflow-hidden"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault()
                    const f = e.dataTransfer.files?.[0]
                    if (f) uploadRef(slot.key, f)
                  }}
                >
                  {refs[slot.key] ? (
                    <img src={refs[slot.key].url} alt={slot.label} className="absolute inset-0 w-full h-full object-cover" />
                  ) : (
                    <>
                      <span className="text-[16px] text-faint" aria-hidden>
                        ＋
                      </span>
                      <span className="text-[10.5px] text-faint px-1 leading-tight">
                        {slot.label}
                        {slot.required ? ' *' : ''}
                      </span>
                    </>
                  )}
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    className="hidden"
                    aria-label={slot.label}
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) uploadRef(slot.key, f)
                    }}
                  />
                </label>
              ))}
            </div>
          </div>
        )}

        <div>
          <span className="label">Assembled prompt (live)</span>
          <p className="bg-well border border-line rounded-el p-3 text-[13.5px] leading-relaxed min-h-[3.5rem] whitespace-pre-wrap">
            {preview || <span className="text-faint">Fill the form — the prompt assembles here.</span>}
          </p>
          {missingRequired.length > 0 && (
            <p className="text-[12px] text-amber-300 mt-1">Still needed: {missingRequired.join(', ')}</p>
          )}
        </div>

        <div className="flex gap-2 flex-wrap">
          <button
            className="btn"
            disabled={!preview}
            onClick={() => navigator.clipboard.writeText(preview).then(() => toastSuccess('Copied'))}
          >
            Copy
          </button>
          <button className="btn" disabled={!preview || missingRequired.length > 0} onClick={savePrompt}>
            Save
          </button>
          <GeneratePanel
            prompt={preview}
            modelFamily={template.recommended_model}
            collectionId={template.collection_id}
            templateId={template.id}
            refIds={Object.values(refs).map((r) => r.ref_id)}
            disabled={!preview || missingRequired.length > 0}
          />
        </div>
      </div>
      {editing && (
        <TemplateEditor
          template={template}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false)
            onChanged()
            onClose()
          }}
        />
      )}
    </Modal>
  )
}

// --------------------------------------------------------- template editor -
function TemplateEditor({
  template,
  onClose,
  onSaved,
}: {
  template: StudioTemplate
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(template.name)
  const [model, setModel] = useState(template.recommended_model ?? '')
  const [textTemplate, setTextTemplate] = useState(template.text_template)
  const [slotsJson, setSlotsJson] = useState(() =>
    JSON.stringify(template.schema.slots ?? [], null, 2),
  )
  const [refsJson, setRefsJson] = useState(() => JSON.stringify(template.ref_slots ?? [], null, 2))
  const [busy, setBusy] = useState(false)

  const save = async () => {
    let slots, refSlots
    try {
      slots = JSON.parse(slotsJson)
      refSlots = JSON.parse(refsJson)
    } catch {
      toastError('Slots/refs JSON is invalid — fix the syntax first.')
      return
    }
    setBusy(true)
    try {
      await api.put(`/api/studio/templates/${template.id}`, {
        name,
        recommended_model: model,
        text_template: textTemplate,
        template_schema: { ...template.schema, slots },
        ref_slots: refSlots,
      })
      toastSuccess('Template saved (marked as user-edited)')
      onSaved()
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const regenerate = async () => {
    setBusy(true)
    try {
      await api.post(`/api/studio/templates/${template.id}/regenerate`)
      toastSuccess('Template rebuilt from the collection style profile')
      onSaved()
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={`Edit “${template.name}”`} onClose={onClose} wide>
      <div className="space-y-3 text-[13px]">
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="tpl-name">
              Name
            </label>
            <input id="tpl-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="tpl-model">
              Recommended model (family slug)
            </label>
            <input id="tpl-model" className="input font-mono" value={model} onChange={(e) => setModel(e.target.value)} />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="tpl-text">
            Text skeleton — <span className="font-mono">{'{slot_key}'}</span> placeholders
          </label>
          <textarea
            id="tpl-text"
            className="input font-mono min-h-[60px]"
            value={textTemplate}
            onChange={(e) => setTextTemplate(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="tpl-slots">
            Slots (JSON: key, label, type text|select|chips|slider, options, default, required)
          </label>
          <textarea
            id="tpl-slots"
            className="input font-mono min-h-[160px] text-[12px]"
            value={slotsJson}
            onChange={(e) => setSlotsJson(e.target.value)}
            spellCheck={false}
          />
        </div>
        <div>
          <label className="label" htmlFor="tpl-refs">
            Reference slots (JSON: key, label, role style|character|composition|other, required)
          </label>
          <textarea
            id="tpl-refs"
            className="input font-mono min-h-[80px] text-[12px]"
            value={refsJson}
            onChange={(e) => setRefsJson(e.target.value)}
            spellCheck={false}
          />
        </div>
        <div className="flex gap-2 items-center flex-wrap pt-1">
          <button className="btn-accent" onClick={save} disabled={busy}>
            {busy ? <Spinner /> : 'Save changes'}
          </button>
          <button className="btn" onClick={regenerate} disabled={busy}>
            Rebuild from style profile
          </button>
          <span className="ml-auto flex gap-2">
            <a className="btn" href={`/api/studio/templates/${template.id}/export.json`}>
              Export JSON
            </a>
            <a className="btn" href={`/api/studio/templates/${template.id}/export.txt`}>
              Export text
            </a>
          </span>
        </div>
      </div>
    </Modal>
  )
}

// -------------------------------------------------------------- enhance ----
function EnhanceTab() {
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('')
  const [collectionId, setCollectionId] = useState<number | ''>('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{
    before: string
    enhanced: string
    negative: string
    notes: { change: string; why: string }[]
  } | null>(null)
  const [needsSetup, setNeedsSetup] = useState<string | null>(null)
  const { data: models } = useFetch(() =>
    api.get<{ models: { family: string; label: string }[] }>('/api/suggest'),
  )
  const { data: collections } = useFetch(() =>
    api.get<{ user_collections: { id: number; name: string }[] }>('/api/collections'),
  )

  const run = async () => {
    setBusy(true)
    setNeedsSetup(null)
    setResult(null)
    try {
      const r = await api.post<typeof result>('/api/studio/enhance', {
        prompt,
        model_family: model || undefined,
        collection_id: collectionId || undefined,
      })
      setResult(r)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setNeedsSetup(e.message)
      else toastError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const saveEnhanced = async () => {
    if (!result) return
    try {
      await api.post('/api/studio/prompts', {
        text: result.enhanced,
        negative: result.negative || undefined,
        model_family: model || undefined,
        collection_id: collectionId || undefined,
        origin: 'enhanced',
      })
      toastSuccess('Enhanced prompt saved')
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <textarea
        className="input min-h-[110px] text-[14px]"
        placeholder="Paste any prompt — PromptForge upscales it with the model's knowledge file, the collection style and the prompting foundation."
        value={prompt}
        aria-label="Prompt to enhance"
        onChange={(e) => setPrompt(e.target.value)}
      />
      <div className="flex gap-2 flex-wrap items-center">
        <select className="input !w-auto" aria-label="Target model" value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">Target model…</option>
          {models?.models.map((m) => (
            <option key={m.family} value={m.family}>
              {m.label}
            </option>
          ))}
        </select>
        <select
          className="input !w-auto"
          aria-label="Collection style"
          value={collectionId}
          onChange={(e) => setCollectionId(e.target.value ? Number(e.target.value) : '')}
        >
          <option value="">No collection style</option>
          {collections?.user_collections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <button className="btn-accent ml-auto" disabled={busy || !prompt.trim()} onClick={run}>
          {busy ? <Spinner /> : '✨ Enhance'}
        </button>
      </div>

      {needsSetup && (
        <div className="card p-4 text-[13px] text-amber-200 border-amber-400/40">
          {needsSetup}{' '}
          <a href="/settings#knowledge" className="underline underline-offset-2">
            Open Settings → Knowledge engine
          </a>
        </div>
      )}

      {result && (
        <div className="space-y-3 fade-in">
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <span className="label">Before</span>
              <p className="bg-well/60 border border-line rounded-el p-3 text-[13px] text-mute whitespace-pre-wrap">
                {result.before}
              </p>
            </div>
            <div>
              <span className="label">After</span>
              <p className="bg-well border border-ember/30 rounded-el p-3 text-[13.5px] whitespace-pre-wrap">
                {result.enhanced}
              </p>
            </div>
          </div>
          {result.negative && (
            <p className="text-[12.5px] text-mute">
              <span className="text-faint">Suggested negative: </span>
              <span className="font-mono">{result.negative}</span>
            </p>
          )}
          {result.notes.length > 0 && (
            <ul className="space-y-1">
              {result.notes.map((n, i) => (
                <li key={i} className="text-[12.5px]">
                  <span className="text-ember-soft font-medium">{n.change}</span>
                  <span className="text-faint"> — {n.why}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="flex gap-2">
            <button
              className="btn"
              onClick={() => navigator.clipboard.writeText(result.enhanced).then(() => toastSuccess('Copied'))}
            >
              Copy
            </button>
            <button className="btn" onClick={saveEnhanced}>
              Save
            </button>
            <GeneratePanel prompt={result.enhanced} modelFamily={model || null} collectionId={collectionId || null} />
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- saved ----
function SavedTab() {
  const [q, setQ] = useState('')
  const [origin, setOrigin] = useState('')
  const [model, setModel] = useState('')
  const [starred, setStarred] = useState(false)
  const debouncedQ = useDebounced(q, 250)
  const [items, setItems] = useState<SavedPromptItem[]>([])
  const [loading, setLoading] = useState(true)
  const { data: models } = useFetch(() =>
    api.get<{ models: { family: string; label: string }[] }>('/api/suggest'),
  )

  const params = useMemo(
    () =>
      new URLSearchParams(
        Object.entries({ q: debouncedQ, origin, model, starred: starred ? 'true' : '' }).filter(
          ([, v]) => v,
        ) as [string, string][],
      ).toString(),
    [debouncedQ, origin, model, starred],
  )

  useEffect(() => {
    let live = true
    setLoading(true)
    api
      .get<{ items: SavedPromptItem[] }>(`/api/studio/prompts?${params}`)
      .then((r) => live && setItems(r.items))
      .catch((e: Error) => toastError(e.message))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [params])

  const toggleStar = async (item: SavedPromptItem) => {
    try {
      if (item.kind === 'saved') {
        const r = await api.post<{ starred: boolean }>(`/api/studio/prompts/${item.id}/star`)
        setItems((prev) => prev.map((x) => (x === item ? { ...x, starred: r.starred } : x)))
      } else {
        await api.patch(`/api/posts/${item.id}`, { favorite: !item.starred })
        setItems((prev) => prev.map((x) => (x === item ? { ...x, starred: !x.starred } : x)))
      }
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-3">
      <input
        type="search"
        className="input h-10 bg-panel"
        placeholder="Search saved prompts and every scraped prompt…"
        aria-label="Search prompts"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="flex gap-1.5 flex-wrap">
        <select className="input !w-auto h-8 py-0 text-[12.5px]" aria-label="Origin" value={origin} onChange={(e) => setOrigin(e.target.value)}>
          <option value="">All origins</option>
          <option value="manual">Saved manually</option>
          <option value="enhanced">Enhanced</option>
          <option value="template">From templates</option>
          <option value="scraped">Scraped</option>
          <option value="generated">Generated</option>
        </select>
        <select className="input !w-auto h-8 py-0 text-[12.5px]" aria-label="Model" value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">All models</option>
          {models?.models.map((m) => (
            <option key={m.family} value={m.family}>
              {m.label}
            </option>
          ))}
        </select>
        <button
          aria-pressed={starred}
          className={`btn h-8 py-0 text-[12.5px] ${starred ? '!border-ember/70 text-ember bg-ember/10' : ''}`}
          onClick={() => setStarred(!starred)}
        >
          ★ Starred
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon="✎"
          title="Nothing here yet"
          hint="Save prompts from templates, Enhance, or the gallery — they all become searchable here."
        />
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={`${item.kind}-${item.id}`} className="card p-3 flex gap-3">
              {item.thumb_url && (
                <img src={item.thumb_url} alt="" className="w-14 h-14 rounded-el object-cover shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-[13px] leading-snug line-clamp-3 whitespace-pre-wrap">{item.text}</p>
                <p className="text-[11.5px] text-faint mt-1">
                  {item.model_family_label ?? 'no model'} · {item.origin} · {timeAgo(item.created_at)}
                </p>
              </div>
              <div className="flex flex-col gap-1 shrink-0">
                <button
                  aria-label={item.starred ? 'Unstar' : 'Star'}
                  className={`btn-ghost px-2 py-0.5 ${item.starred ? 'text-ember' : 'text-faint'}`}
                  onClick={() => toggleStar(item)}
                >
                  {item.starred ? '★' : '☆'}
                </button>
                <button
                  aria-label="Copy prompt"
                  className="btn-ghost px-2 py-0.5 text-faint hover:text-fg"
                  onClick={() => navigator.clipboard.writeText(item.text).then(() => toastSuccess('Copied'))}
                >
                  ⧉
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
