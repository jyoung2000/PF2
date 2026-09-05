// Assets workspace (spec §3–§11): tabs per type, image-forward grid, visual
// editors driven by the attribute schema with per-group locks, references
// (upload / gallery import / generated), immutable versions with
// restore / duplicate / compare / use-as-current, propagation to shots,
// AI tools gated by real provider capabilities, canonical context preview.
import { useEffect, useMemo, useRef, useState } from 'react'
import { Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api'
import { ConfirmModal, EmptyState, Modal, Spinner } from '../../components/Primitives'
import { timeAgo } from '../../lib/format'
import { Asset, AssetSchema, AssetTool, AssetType, ASSET_TYPES, errorMessage, film, fmtUsd } from '../../lib/film'
import { useDebounced } from '../../lib/hooks'
import { toastError, toastSuccess } from '../../lib/toast'
import { useFilm } from './FilmPage'

const TYPE_ICON: Record<AssetType, string> = { character: '👤', location: '🏙', prop: '🔦', vehicle: '🚗', outfit: '🧥', style: '🎨' }

export function AssetsPage() {
  return (
    <Routes>
      <Route index element={<AssetGrid />} />
      <Route path=":id" element={<AssetEditor />} />
    </Routes>
  )
}

function AssetGrid() {
  const { schema } = useFilm()
  const navigate = useNavigate()
  const [type, setType] = useState<AssetType>('character')
  const [q, setQ] = useState('')
  const dq = useDebounced(q, 200)
  const [assets, setAssets] = useState<Asset[] | null>(null)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const load = () => {
    setAssets(null)
    film.listAssets({ type, q: dq || undefined }).then((r) => setAssets(r.assets)).catch((e) => toastError(errorMessage(e)))
  }
  useEffect(load, [type, dq]) // eslint-disable-line react-hooks/exhaustive-deps
  const create = async () => {
    if (!name.trim()) return
    try {
      const a = await film.createAsset({ type, name: name.trim() })
      setCreating(false)
      setName('')
      navigate(`/film/assets/${a.id}`)
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const sch = schema?.schemas[type]
  return (
    <div className="space-y-3" data-testid="assets-grid">
      <div className="flex items-center gap-1 flex-wrap">
        {ASSET_TYPES.map((t) => (
          <button key={t} className={`px-2.5 py-1.5 rounded-el text-[13px] ${type === t ? 'bg-well text-fg font-medium' : 'text-mute hover:text-fg'}`} onClick={() => setType(t)} data-asset-tab={t}>
            {TYPE_ICON[t]} {schema?.schemas[t]?.plural ?? t}
          </button>
        ))}
        <input className="input !w-56 !h-8 ml-auto" placeholder={`Search ${sch?.plural.toLowerCase() ?? ''}…`} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search assets" />
        <button className="btn-accent" onClick={() => setCreating(true)}>+ New {sch?.label.toLowerCase()}</button>
      </div>
      {type === 'outfit' && <p className="text-[12px] text-faint">Outfits usually live inside a character (open a character → Clothing). Standalone outfits listed here can be pinned to any shot.</p>}
      {creating && (
        <Modal title={`New ${sch?.label.toLowerCase()}`} onClose={() => setCreating(false)}>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && create()} placeholder="Name" />
          <div className="flex justify-end gap-2 mt-3"><button className="btn" onClick={() => setCreating(false)}>Cancel</button><button className="btn-accent" onClick={create} disabled={!name.trim()}>Create</button></div>
        </Modal>
      )}
      {assets === null ? (
        <div className="py-16 flex justify-center"><Spinner className="w-6 h-6" /></div>
      ) : assets.length === 0 ? (
        <EmptyState icon={TYPE_ICON[type]} title={`No ${sch?.plural.toLowerCase()} yet`} hint="Assets are reusable across every project: canonical description, references, locked attributes, versions." action={<button className="btn-accent" onClick={() => setCreating(true)}>Create one</button>} />
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2.5">
          {assets.map((a) => (
            <button key={a.id} className="card p-2 text-left hover:border-ember/60 group" onClick={() => navigate(`/film/assets/${a.id}`)} data-asset-card={a.id}>
              <div className="aspect-[4/5] rounded-el overflow-hidden bg-well flex items-center justify-center">
                {a.thumb_url ? <img src={a.thumb_url} alt="" className="w-full h-full object-cover group-hover:scale-[1.02] transition-transform" loading="lazy" /> : <span className="font-display text-[30px] text-faint">{a.name.slice(0, 1)}</span>}
              </div>
              <div className="mt-1.5 flex items-center gap-1">
                <span className="font-display text-[13px] font-medium truncate">{a.name}</span>
                {a.favorite && <span className="text-ember text-[11px]">★</span>}
                {a.approved && <span className="text-emerald-300 text-[11px]" title="approved">✓</span>}
              </div>
              <div className="text-[10.5px] text-faint">{a.current_version.label} · {a.version_count} version{a.version_count === 1 ? '' : 's'} · {a.ref_count} ref{a.ref_count === 1 ? '' : 's'}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ editor -
function useAsset(id: number) {
  const [asset, setAsset] = useState<Asset | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reload = () => film.getAsset(id).then(setAsset).catch((e) => setError(errorMessage(e)))
  useEffect(() => {
    reload()
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  return { asset, setAsset, error, reload }
}

function AssetEditor() {
  const { id } = useParams()
  const aid = Number(id)
  const { schema } = useFilm()
  const navigate = useNavigate()
  const { asset, setAsset, error, reload } = useAsset(aid)
  const [tab, setTab] = useState<'attributes' | 'references' | 'versions' | 'ai' | 'usage'>('attributes')
  const [confirmDelete, setConfirmDelete] = useState(false)
  if (error) return <EmptyState icon="⚠" title="Asset not found" hint={error} action={<button className="btn" onClick={() => navigate('/film/assets')}>Back to assets</button>} />
  if (!asset || !schema) return <div className="py-16 flex justify-center"><Spinner className="w-6 h-6" /></div>
  const sch = schema.schemas[asset.type]
  const v = asset.current_version
  const patch = async (body: Parameters<typeof film.patchAsset>[1]) => {
    try {
      setAsset(await film.patchAsset(asset.id, body))
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const remove = async (force = false) => {
    try {
      await film.deleteAsset(asset.id, force)
      toastSuccess('Asset deleted')
      navigate('/film/assets')
    } catch (e) {
      const msg = errorMessage(e)
      if (!force && /used by/.test(msg) && window.confirm(`${msg}\n\nDelete anyway and unpin it everywhere?`)) return remove(true)
      toastError(msg)
    }
  }
  return (
    <div className="space-y-3 fade-in" data-testid="asset-editor">
      <div className="flex items-center gap-2 flex-wrap">
        <button className="btn-ghost text-[12px]" onClick={() => navigate('/film/assets')}>← {sch.plural}</button>
        <span className="text-[18px]">{TYPE_ICON[asset.type]}</span>
        <input className="input !w-64 font-display text-[16px] font-medium" defaultValue={asset.name} onBlur={(e) => e.target.value.trim() && e.target.value !== asset.name && patch({ name: e.target.value })} aria-label="Asset name" />
        <span className="chip">{v.label}{v.frozen ? ' · frozen' : ' · draft'}</span>
        <label className="flex items-center gap-1 text-[12px] text-mute"><input type="checkbox" checked={asset.approved} onChange={(e) => patch({ approved: e.target.checked })} /> approved</label>
        <button className={`btn-ghost text-[14px] ${asset.favorite ? 'text-ember' : ''}`} onClick={() => patch({ favorite: !asset.favorite })} aria-label="favourite">★</button>
        <button className={`btn-ghost text-[12px] ${asset.pinned ? 'text-ember' : ''}`} onClick={() => patch({ pinned: !asset.pinned })}>{asset.pinned ? 'pinned' : 'pin'}</button>
        <button className="btn-danger text-[12px] ml-auto" onClick={() => setConfirmDelete(true)}>Delete</button>
      </div>
      <div className="grid lg:grid-cols-[300px_1fr] gap-3">
        <aside className="space-y-3">
          <div className="card p-2.5">
            <div className="aspect-[4/5] rounded-el overflow-hidden bg-well flex items-center justify-center">
              {v.primary_thumb_url ? <img src={v.refs.find((r) => r.id === v.primary_ref_id)?.url ?? v.primary_thumb_url} alt="" className="w-full h-full object-cover" /> : <span className="text-[12px] text-faint px-4 text-center">No reference yet — upload or generate one.</span>}
            </div>
            <textarea className="input mt-2 min-h-[64px] text-[12.5px]" placeholder="Description" defaultValue={asset.description ?? ''} onBlur={(e) => e.target.value !== (asset.description ?? '') && patch({ description: e.target.value })} />
            <input className="input mt-1.5 text-[12px]" placeholder="tags, comma separated" defaultValue={asset.tags.join(', ')} onBlur={(e) => patch({ tags: e.target.value.split(',').map((t) => t.trim()).filter(Boolean) })} />
          </div>
          <ContextPreview asset={asset} />
        </aside>
        <main className="space-y-3 min-w-0">
          <div className="flex gap-1 flex-wrap">
            {(['attributes', 'references', 'versions', 'ai', 'usage'] as const).map((t) => (
              <button key={t} className={`px-2.5 py-1.5 rounded-el text-[13px] ${tab === t ? 'bg-well text-fg font-medium' : 'text-mute hover:text-fg'}`} onClick={() => setTab(t)} data-asset-tab={t}>
                {t === 'ai' ? 'AI tools' : t[0].toUpperCase() + t.slice(1)}{t === 'references' ? ` (${asset.ref_count})` : t === 'versions' ? ` (${asset.version_count})` : ''}
              </button>
            ))}
          </div>
          {tab === 'attributes' && <AttributesEditor asset={asset} sch={sch} onChanged={setAsset} />}
          {tab === 'references' && <ReferencesPanel asset={asset} sch={sch} onChanged={reload} />}
          {tab === 'versions' && <VersionsPanel asset={asset} onChanged={setAsset} />}
          {tab === 'ai' && <AiToolsPanel asset={asset} sch={sch} onChanged={reload} />}
          {tab === 'usage' && <UsagePanel asset={asset} onChanged={reload} />}
        </main>
      </div>
      {confirmDelete && <ConfirmModal title={`Delete ${asset.name}?`} message="Versions and references are removed. Shots pinned to it must be unpinned first (you will be asked)." onConfirm={() => remove(false)} onClose={() => setConfirmDelete(false)} />}
    </div>
  )
}

function ContextPreview({ asset }: { asset: Asset }) {
  const [open, setOpen] = useState(false)
  const [prose, setProse] = useState<string | null>(null)
  useEffect(() => {
    if (open) film.assetContext(asset.id).then((r) => setProse(r.prose)).catch(() => setProse(null))
  }, [open, asset.id, asset.current_version])
  const ctx = asset.context
  return (
    <div className="card p-2.5 text-[12px]">
      <button className="w-full flex items-center justify-between" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="font-display">Canonical context</span><span className="text-faint">{open ? '▾' : '▸'}</span>
      </button>
      {ctx && (
        <div className="mt-1.5 text-faint">{ctx.locked_attributes.length} locked · {ctx.variable_attributes.length} variable · {ctx.references.length} refs</div>
      )}
      {open && (
        <div className="mt-2 space-y-1.5 fade-in">
          {ctx && ctx.identity_anchors.length > 0 && <div><span className="text-faint">anchors:</span> {ctx.identity_anchors.join(' · ')}</div>}
          {prose && <p className="text-mute leading-snug">{prose}</p>}
          <details className="text-[11px]"><summary className="text-faint cursor-pointer">JSON</summary><pre className="whitespace-pre-wrap text-[10.5px] text-faint max-h-60 overflow-auto">{JSON.stringify(ctx, null, 1)}</pre></details>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------- attributes ----
function AttributesEditor({ asset, sch, onChanged }: { asset: Asset; sch: AssetSchema; onChanged: (a: Asset) => void }) {
  const v = asset.current_version
  const [data, setData] = useState<Record<string, unknown>>(v.data)
  const [locks, setLocks] = useState<string[]>(v.locks)
  const [rules, setRules] = useState(v.continuity_rules.join('\n'))
  const [negs, setNegs] = useState(v.negative_constraints.join('\n'))
  const [anchors, setAnchors] = useState(v.identity_anchors.join('\n'))
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    setData(v.data)
    setLocks(v.locks)
    setRules(v.continuity_rules.join('\n'))
    setNegs(v.negative_constraints.join('\n'))
    setAnchors(v.identity_anchors.join('\n'))
    setDirty(false)
  }, [v.id, v.updated_at]) // eslint-disable-line react-hooks/exhaustive-deps
  const lockOf = useMemo(() => {
    const m: Record<string, string> = {}
    sch.lock_groups.forEach((g) => g.fields.forEach((f) => (m[f] = g.key)))
    return m
  }, [sch])
  const save = async (asNew = false) => {
    setBusy(true)
    try {
      const changes: Record<string, unknown> = {}
      for (const k of new Set([...Object.keys(data), ...Object.keys(v.data)])) if (JSON.stringify(data[k]) !== JSON.stringify(v.data[k])) changes[k] = data[k] ?? null
      const lines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean)
      const r = await film.editVersion(asset.id, { changes, locks, continuity_rules: lines(rules), negative_constraints: lines(negs), identity_anchors: lines(anchors), new_version: asNew })
      onChanged(r.asset)
      setDirty(false)
      toastSuccess(r.created ? `Saved as ${r.version.label}${!asNew ? ` — ${v.label} was in use, so it stays exactly as it was` : ''}` : `Saved ${r.version.label}`)
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const set = (k: string, val: unknown) => {
    setData((d) => ({ ...d, [k]: val }))
    setDirty(true)
  }
  const toggleLock = (g: string) => {
    setLocks((l) => (l.includes(g) ? l.filter((x) => x !== g) : [...l, g]))
    setDirty(true)
  }
  return (
    <div className="space-y-3" data-testid="attributes-editor">
      <div className="card p-3">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="label mr-1">Locks</span>
          {sch.lock_groups.map((g) => {
            const on = locks.includes(g.key)
            return (
              <button key={g.key} className={`chip ${on ? '!border-ember text-fg' : ''}`} onClick={() => toggleLock(g.key)} title={g.shot_level ? 'Shot-level lock: the Director never changes this on shots' : `Locks: ${g.fields.join(', ') || g.label}`} aria-pressed={on} data-lock={g.key}>
                {on ? '🔒' : '🔓'} {g.label}
              </button>
            )
          })}
        </div>
        <p className="text-[11px] text-faint mt-1.5">Locked groups are constraints for the Director and every regeneration. Unlocked groups may vary per shot.</p>
      </div>
      {sch.sections.map((sec) => (
        <section key={sec.key} className="card p-3">
          <h4 className="font-display text-[13.5px] mb-2">{sec.label}</h4>
          <div className="grid sm:grid-cols-2 gap-2.5">
            {sec.fields.map((f) => {
              const g = lockOf[f.key]
              const locked = g ? locks.includes(g) : false
              const val = data[f.key]
              const common = 'input' + (locked ? ' !border-ember/50' : '')
              return (
                <label key={f.key} className={`text-[12px] text-mute flex flex-col gap-1 ${f.type === 'textarea' || f.type === 'list' ? 'sm:col-span-2' : ''}`}>
                  <span className="flex items-center gap-1">{f.label}{g && <span className="text-[10px]" title={locked ? `locked (${g})` : `unlocked (${g})`}>{locked ? '🔒' : ''}</span>}</span>
                  {f.type === 'textarea' ? (
                    <textarea className={common + ' min-h-[60px]'} value={(val as string) ?? ''} onChange={(e) => set(f.key, e.target.value)} />
                  ) : f.type === 'select' ? (
                    <select className={common} value={(val as string) ?? ''} onChange={(e) => set(f.key, e.target.value)}>
                      <option value="">—</option>
                      {(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : f.type === 'bool' ? (
                    <input type="checkbox" checked={Boolean(val)} onChange={(e) => set(f.key, e.target.checked)} className="self-start" />
                  ) : f.type === 'list' ? (
                    <input className={common} value={Array.isArray(val) ? (val as string[]).join(', ') : ((val as string) ?? '')} placeholder="comma separated" onChange={(e) => set(f.key, e.target.value.split(',').map((x) => x.trim()).filter(Boolean))} />
                  ) : f.type === 'asset' ? (
                    <OutfitField asset={asset} value={val as number | undefined} onChange={(id) => set(f.key, id)} />
                  ) : f.type === 'ref' ? (
                    <select className={common} value={(val as number) ?? ''} onChange={(e) => set(f.key, e.target.value ? Number(e.target.value) : '')}>
                      <option value="">— pick a reference (map / diagram) —</option>
                      {v.refs.map((r) => <option key={r.id} value={r.id}>{r.kind} #{r.id}{r.label ? ` · ${r.label}` : ''}</option>)}
                    </select>
                  ) : (
                    <input className={common} value={(val as string) ?? ''} onChange={(e) => set(f.key, e.target.value)} />
                  )}
                </label>
              )
            })}
          </div>
        </section>
      ))}
      <section className="card p-3 grid sm:grid-cols-3 gap-2.5">
        <label className="text-[12px] text-mute flex flex-col gap-1">Identity anchors (one per line; derived from locks when empty)<textarea className="input min-h-[70px]" value={anchors} onChange={(e) => { setAnchors(e.target.value); setDirty(true) }} /></label>
        <label className="text-[12px] text-mute flex flex-col gap-1">Continuity rules<textarea className="input min-h-[70px]" value={rules} placeholder="scar always on the left cheek" onChange={(e) => { setRules(e.target.value); setDirty(true) }} /></label>
        <label className="text-[12px] text-mute flex flex-col gap-1">Never (negative constraints)<textarea className="input min-h-[70px]" value={negs} placeholder="no beard" onChange={(e) => { setNegs(e.target.value); setDirty(true) }} /></label>
      </section>
      <div className="sticky bottom-2 flex items-center gap-2 card !bg-panel/95 backdrop-blur p-2.5">
        <span className="text-[12px] text-faint">{dirty ? 'Unsaved changes' : 'All changes saved'}{v.frozen ? ` · ${v.label} is in use — saving creates a new version` : ''}</span>
        <button className="btn ml-auto" disabled={!dirty || busy} onClick={() => save(true)}>Save as new version</button>
        <button className="btn-accent" disabled={!dirty || busy} onClick={() => save(false)} data-testid="save-attributes">{busy ? <Spinner /> : 'Save'}</button>
      </div>
    </div>
  )
}

function OutfitField({ asset, value, onChange }: { asset: Asset; value: number | undefined; onChange: (id: number | '') => void }) {
  const [name, setName] = useState('')
  const outfits = asset.outfits ?? []
  const navigate = useNavigate()
  const create = async () => {
    if (!name.trim()) return
    try {
      const o = await film.createAsset({ type: 'outfit', name: name.trim(), owner_asset_id: asset.id, data: { is_default: outfits.length === 0 } })
      toastSuccess(`Outfit “${o.name}” added`)
      navigate(`/film/assets/${o.id}`)
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  return (
    <div className="space-y-1.5">
      <select className="input" value={value ?? ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : '')}>
        <option value="">— no default outfit —</option>
        {outfits.map((o) => <option key={o.id} value={o.id}>{o.name}{o.current_version.data.is_default ? ' (default)' : ''}</option>)}
      </select>
      <div className="flex flex-wrap gap-1">
        {outfits.map((o) => <button key={o.id} className="chip" onClick={() => navigate(`/film/assets/${o.id}`)}>🧥 {o.name}</button>)}
        <input className="input !w-40 !h-7 text-[12px]" placeholder="new outfit name" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && create()} />
        <button className="btn text-[11.5px] py-0.5" onClick={create} disabled={!name.trim()}>+ outfit</button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------- references ----
function ReferencesPanel({ asset, sch, onChanged }: { asset: Asset; sch: AssetSchema; onChanged: () => void }) {
  const v = asset.current_version
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [kind, setKind] = useState(sch.ref_kinds[0])
  const [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState(false)
  const [gallery, setGallery] = useState(false)
  const uploadFiles = async (files: FileList | File[]) => {
    setBusy(true)
    try {
      for (const f of Array.from(files)) {
        const r = await film.uploadRef(asset.id, f, { kind })
        if (r.deduped) toastSuccess('Already attached (identical file)')
      }
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const act = async (fn: () => Promise<unknown>, msg?: string) => {
    try {
      await fn()
      if (msg) toastSuccess(msg)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  return (
    <div className="space-y-3" data-testid="references-panel">
      <div
        className={`card p-4 border-dashed text-center text-[12.5px] ${drag ? 'border-ember bg-well' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); uploadFiles(e.dataTransfer.files) }}
      >
        <p className="text-mute">Drop reference images here, or</p>
        <div className="flex items-center justify-center gap-2 mt-2 flex-wrap">
          <select className="input !w-40 !h-8" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Reference kind">
            {sch.ref_kinds.map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
          </select>
          <button className="btn" onClick={() => fileRef.current?.click()} disabled={busy}>{busy ? <Spinner /> : 'Choose files'}</button>
          <button className="btn" onClick={() => setGallery(true)}>Import from Gallery</button>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={(e) => e.target.files && uploadFiles(e.target.files)} />
        </div>
        <p className="text-[11px] text-faint mt-2">Originals are kept untouched; thumbnails are derived. Generated images land here too.</p>
      </div>
      {v.refs.length === 0 ? (
        <p className="text-[12.5px] text-faint text-center py-4">No references yet.</p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2.5">
          {v.refs.map((r) => (
            <div key={r.id} className={`card p-1.5 ${r.id === v.primary_ref_id ? 'border-ember' : ''}`} data-ref-id={r.id}>
              <a href={r.url ?? '#'} target="_blank" rel="noreferrer" className="block aspect-square rounded-el overflow-hidden bg-well">
                {r.thumb_url && <img src={r.thumb_url} alt="" className="w-full h-full object-cover" loading="lazy" />}
              </a>
              <div className="mt-1.5 flex items-center gap-1 text-[11px]">
                <select className="input !h-6 !py-0 !text-[11px] !w-auto" value={r.kind} onChange={(e) => act(() => film.patchRef(r.id, { kind: e.target.value }))}>
                  {sch.ref_kinds.map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
                </select>
                {r.id === v.primary_ref_id ? <span className="text-ember ml-auto">primary</span> : <button className="btn-ghost text-[11px] px-1 ml-auto" onClick={() => act(() => film.primaryRef(r.id), 'Primary reference set')}>make primary</button>}
              </div>
              <div className="text-[10.5px] text-faint truncate mt-0.5" title={JSON.stringify(r.provenance)}>
                {r.source.startsWith('generation') ? `generated · ${String(r.provenance.model_family ?? '')} · ${fmtUsd(r.provenance.cost_usd as number)}` : r.source.startsWith('post') ? `gallery · ${String(r.provenance.platform ?? '')}${r.provenance.author ? ` · ${String(r.provenance.author)}` : ''}` : 'upload'} · {r.width}×{r.height}
              </div>
              <div className="flex gap-1 mt-1">
                <input className="input !h-6 !py-0 !text-[11px] flex-1" defaultValue={r.label ?? ''} placeholder="label" onBlur={(e) => e.target.value !== (r.label ?? '') && act(() => film.patchRef(r.id, { label: e.target.value }))} />
                <button className="btn-ghost text-[11px] px-1 text-red-300" onClick={() => window.confirm('Remove this reference?') && act(() => film.deleteRef(r.id), 'Reference removed')}>remove</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {gallery && <GalleryImport onClose={() => setGallery(false)} onPick={(postId) => act(() => film.importRef(asset.id, { post_id: postId, kind }), 'Imported from the Gallery with attribution').then(() => setGallery(false))} />}
    </div>
  )
}

export function GalleryImport({ onClose, onPick, videoToo = false }: { onClose: () => void; onPick: (postId: number) => void; videoToo?: boolean }) {
  const [q, setQ] = useState('')
  const dq = useDebounced(q, 250)
  const [items, setItems] = useState<{ id: number; thumb_url: string | null; prompt: string | null; media_type: string; platform: string }[] | null>(null)
  useEffect(() => {
    setItems(null)
    api.get<{ items: any[] }>(`/api/search?q=${encodeURIComponent(dq)}&limit=48${videoToo ? '' : '&media_type=image'}`).then((r) => setItems(r.items)).catch((e) => toastError(errorMessage(e)))
  }, [dq, videoToo])
  return (
    <Modal title="Import from Gallery" onClose={onClose} wide>
      <input className="input mb-2" autoFocus placeholder="Search your library (prompt, tag:x, model:y)…" value={q} onChange={(e) => setQ(e.target.value)} />
      {items === null ? <Spinner /> : items.length === 0 ? <p className="text-[12.5px] text-faint py-6 text-center">Nothing found.</p> : (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-1.5 max-h-[50vh] overflow-y-auto">
          {items.map((p) => (
            <button key={p.id} className="aspect-square rounded-el overflow-hidden bg-well border border-line hover:border-ember" onClick={() => onPick(p.id)} title={p.prompt ?? ''}>
              {p.thumb_url && <img src={p.thumb_url} alt="" className="w-full h-full object-cover" loading="lazy" />}
            </button>
          ))}
        </div>
      )}
    </Modal>
  )
}

// ------------------------------------------------------------- versions ----
function VersionsPanel({ asset, onChanged }: { asset: Asset; onChanged: (a: Asset) => void }) {
  const versions = asset.versions ?? []
  const [cmp, setCmp] = useState<{ a: number; b: number } | null>(null)
  const [diff, setDiff] = useState<any>(null)
  useEffect(() => {
    if (cmp) film.compareVersions(asset.id, cmp.a, cmp.b).then(setDiff).catch((e) => toastError(errorMessage(e)))
  }, [cmp, asset.id])
  const act = async (vid: number, action: 'restore' | 'duplicate' | 'use') => {
    try {
      const r = await film.versionAction(asset.id, vid, action)
      onChanged(r.asset)
      toastSuccess(action === 'restore' ? `Restored as ${r.version.label}` : action === 'duplicate' ? `Duplicated as ${r.version.label}` : `${r.version.label} is now current`)
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  return (
    <div className="space-y-3" data-testid="versions-panel">
      <div className="flex gap-2 overflow-x-auto pb-1">
        {versions.map((v) => (
          <div key={v.id} className={`shrink-0 w-44 card p-2 ${v.id === asset.current_version_id ? 'border-ember' : ''}`} data-version={v.number}>
            <div className="aspect-[4/5] rounded-el overflow-hidden bg-well flex items-center justify-center">{v.primary_thumb_url ? <img src={v.primary_thumb_url} alt="" className="w-full h-full object-cover" /> : <span className="text-faint text-[11px]">no image</span>}</div>
            <div className="mt-1.5 flex items-center gap-1"><span className="font-display text-[13px]">{v.label}</span>{v.id === asset.current_version_id && <span className="chip !text-[9.5px] text-ember">current</span>}</div>
            <div className="text-[10.5px] text-faint">{v.frozen ? 'frozen' : 'editable'} · {v.usage?.shots.length ?? 0} shot{(v.usage?.shots.length ?? 0) === 1 ? '' : 's'} · {timeAgo(v.created_at)}</div>
            <div className="text-[10.5px] text-faint truncate">{String(v.provenance.source ?? 'manual')}{v.provenance.from_version_id ? ` ← v${versions.find((x) => x.id === v.provenance.from_version_id)?.number ?? '?'}` : ''}</div>
            <div className="text-[10.5px] text-mute">🔒 {v.locks.join(', ') || 'none'}</div>
            <div className="flex flex-wrap gap-1 mt-1.5">
              {v.id !== asset.current_version_id && <button className="btn-ghost text-[11px] px-1" onClick={() => act(v.id, 'use')}>use as current</button>}
              <button className="btn-ghost text-[11px] px-1" onClick={() => act(v.id, 'restore')}>restore</button>
              <button className="btn-ghost text-[11px] px-1" onClick={() => act(v.id, 'duplicate')}>duplicate</button>
              <button className="btn-ghost text-[11px] px-1" onClick={() => setCmp({ a: v.id, b: asset.current_version_id })} disabled={v.id === asset.current_version_id}>compare</button>
            </div>
          </div>
        ))}
      </div>
      {cmp && diff && (
        <div className="card p-3 text-[12px] fade-in">
          <div className="flex items-center justify-between"><span className="font-display">v{diff.a.number} → v{diff.b.number}{diff.identical ? ' · identical' : ''}</span><button className="btn-ghost text-[11px]" onClick={() => { setCmp(null); setDiff(null) }}>close</button></div>
          <div className="grid sm:grid-cols-2 gap-2 mt-2">
            <div className="rounded-el overflow-hidden bg-well aspect-[4/3]">{versions.find((x) => x.id === diff.a.id)?.primary_thumb_url && <img src={versions.find((x) => x.id === diff.a.id)!.primary_thumb_url!} alt="" className="w-full h-full object-cover" />}</div>
            <div className="rounded-el overflow-hidden bg-well aspect-[4/3]">{versions.find((x) => x.id === diff.b.id)?.primary_thumb_url && <img src={versions.find((x) => x.id === diff.b.id)!.primary_thumb_url!} alt="" className="w-full h-full object-cover" />}</div>
          </div>
          <ul className="mt-2 space-y-0.5">
            {Object.entries(diff.changed as Record<string, { a: unknown; b: unknown }>).map(([k, v]) => <li key={k}><span className="text-mute">{k}:</span> <span className="line-through text-faint">{String(v.a)}</span> → {String(v.b)}</li>)}
            {Object.entries(diff.added as Record<string, unknown>).map(([k, v]) => <li key={k} className="text-emerald-300">+ {k}: {String(v)}</li>)}
            {Object.entries(diff.removed as Record<string, unknown>).map(([k, v]) => <li key={k} className="text-red-300">− {k}: {String(v)}</li>)}
            {diff.locks.locked_in_b.length > 0 && <li>🔒 locked: {diff.locks.locked_in_b.join(', ')}</li>}
            {diff.locks.unlocked_in_b.length > 0 && <li>🔓 unlocked: {diff.locks.unlocked_in_b.join(', ')}</li>}
          </ul>
        </div>
      )}
      <p className="text-[11.5px] text-faint">Versions used by a shot or scene are frozen forever; shots keep the exact version they were made with until you propagate a new one (Usage tab).</p>
    </div>
  )
}

// ------------------------------------------------------------- AI tools ----
function AiToolsPanel({ asset, sch, onChanged }: { asset: Asset; sch: AssetSchema; onChanged: () => void }) {
  const [tools, setTools] = useState<AssetTool[] | null>(null)
  const [gens, setGens] = useState<any[]>([])
  const [instruction, setInstruction] = useState('')
  const [strength, setStrength] = useState(0.55)
  const [kind, setKind] = useState(sch.ref_kinds[0])
  const [busy, setBusy] = useState<string | null>(null)
  const load = () => film.assetTools(asset.id).then((r) => { setTools(r.tools); setGens(r.generations) }).catch((e) => toastError(errorMessage(e)))
  useEffect(() => {
    load()
    const t = window.setInterval(load, 5000)
    return () => window.clearInterval(t)
  }, [asset.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const run = async (tool: AssetTool) => {
    setBusy(tool.key)
    try {
      const r = await film.assetGenerate(asset.id, { tool: tool.key, instruction: instruction || undefined, strength: tool.key === 'edit' ? strength : undefined, kind })
      toastSuccess(`${tool.label} queued on ${r.provider} · ${r.family}${r.estimate_usd != null ? ` · ${fmtUsd(r.estimate_usd)}` : ''}`)
      load()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  if (!tools) return <Spinner />
  return (
    <div className="space-y-3" data-testid="ai-tools">
      <div className="card p-3 space-y-2">
        <label className="label block">Direction (optional)<textarea className="input mt-1 min-h-[60px]" value={instruction} placeholder={`e.g. “rain on ${asset.type === 'character' ? 'his face, streetlight from the left' : 'the wet asphalt, neon reflections'}”`} onChange={(e) => setInstruction(e.target.value)} /></label>
        <div className="flex items-center gap-2 flex-wrap text-[12px]">
          <span className="text-mute">Save result as</span>
          <select className="input !w-40 !h-8" value={kind} onChange={(e) => setKind(e.target.value)}>{sch.ref_kinds.map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}</select>
          <span className="text-mute ml-2">Edit strength</span>
          <input type="range" min="0.2" max="0.9" step="0.05" value={strength} onChange={(e) => setStrength(Number(e.target.value))} /><span className="text-faint tabular-nums">{strength.toFixed(2)}</span>
        </div>
        <div className="grid sm:grid-cols-3 gap-2">
          {tools.map((t) => (
            <button key={t.key} className={`card !bg-well p-2.5 text-left ${t.supported ? 'hover:border-ember/60' : 'opacity-60 cursor-not-allowed'}`} disabled={!t.supported || busy != null} onClick={() => run(t)} title={t.reason ?? t.what ?? ''} data-tool={t.key}>
              <div className="font-display text-[13px] flex items-center gap-1">{t.label}{busy === t.key && <Spinner />}</div>
              <div className="text-[11px] text-mute">{t.supported ? t.what : t.reason}</div>
              {t.supported && t.families.length > 0 && <div className="text-[10.5px] text-faint mt-0.5">{t.mode.replace(/_/g, ' ')} · {t.families.join(', ')}</div>}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-faint">Only tools a connected provider actually declares are enabled. Prompts are built from the canonical context: locked attributes first, then your direction.</p>
      </div>
      {gens.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="font-display text-[13px]">Recent generations</h4>
          {gens.map((g) => (
            <div key={g.generation_id} className="flex items-center gap-2 text-[12px] card p-2">
              {g.ref?.thumb_url ? <img src={g.ref.thumb_url} alt="" className="w-12 h-12 rounded-el object-cover" /> : <span className="w-12 h-12 rounded-el bg-well flex items-center justify-center text-faint">{g.status === 'failed' ? '✕' : <Spinner />}</span>}
              <div className="min-w-0 flex-1">
                <div><span className="chip !text-[10px]">{g.tool}</span> {g.provider} · {g.model_family} · <span className={g.status === 'failed' ? 'text-red-300' : g.status === 'succeeded' ? 'text-emerald-300' : 'text-amber-300'}>{g.status}</span> · {fmtUsd(g.cost_actual ?? g.cost_estimate)}</div>
                <div className="text-faint truncate" title={g.prompt ?? ''}>{g.error ?? g.prompt}</div>
              </div>
              {g.ref && <button className="btn-ghost text-[11px]" onClick={() => film.primaryRef(g.ref.id).then(onChanged)}>make primary</button>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- usage ----
function UsagePanel({ asset, onChanged }: { asset: Asset; onChanged: () => void }) {
  const { projects } = useFilm()
  const usage = asset.usage
  const versions = asset.versions ?? []
  const [scope, setScope] = useState<'selected' | 'future' | 'project'>('project')
  const [versionId, setVersionId] = useState(asset.current_version_id)
  const [projectId, setProjectId] = useState<number | ''>(usage?.project_ids[0] ?? '')
  const [shotIds, setShotIds] = useState<number[]>([])
  const [fromShot, setFromShot] = useState<number | ''>('')
  if (!usage) return <Spinner />
  const propagate = async () => {
    try {
      const r = await film.propagate(asset.id, { version_id: versionId, scope, project_id: projectId || undefined, shot_ids: shotIds, from_shot_id: fromShot || undefined })
      toastSuccess(`Applied to ${r.updated_shots.length} shot(s) and ${r.updated_scenes.length} scene default(s)`)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  return (
    <div className="space-y-3" data-testid="usage-panel">
      <div className="card p-3">
        <h4 className="font-display text-[13.5px] mb-1.5">Linked shots</h4>
        {usage.shots.length === 0 && usage.scene_ids.length === 0 ? <p className="text-[12.5px] text-faint">Not used by any shot or scene yet.</p> : (
          <ul className="text-[12.5px] space-y-0.5">
            {usage.shots.map((sh) => (
              <li key={sh.shot_id} className="flex items-center gap-2">
                <input type="checkbox" checked={shotIds.includes(sh.shot_id)} onChange={(e) => setShotIds((s) => (e.target.checked ? [...s, sh.shot_id] : s.filter((x) => x !== sh.shot_id)))} />
                <span>{projects.find((p) => p.id === sh.project_id)?.title ?? `project ${sh.project_id}`} · shot {sh.shot_id}{sh.title ? ` “${sh.title}”` : ''}</span>
                <span className="text-faint">pinned {versions.find((v) => v.id === sh.version_id)?.label ?? `#${sh.version_id}`}</span>
              </li>
            ))}
            {usage.scene_ids.length > 0 && <li className="text-faint">+ scene defaults in {usage.scene_ids.length} scene(s)</li>}
          </ul>
        )}
      </div>
      <div className="card p-3 space-y-2">
        <h4 className="font-display text-[13.5px]">Update shots to a version</h4>
        <p className="text-[12px] text-faint">Changing the current version never rewrites old shots. Push a version explicitly:</p>
        <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
          <select className="input !w-40 !h-8" value={versionId} onChange={(e) => setVersionId(Number(e.target.value))}>{versions.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}</select>
          <select className="input !w-44 !h-8" value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
            <option value="selected">Update selected shots</option>
            <option value="future">Update future shots (from a shot on)</option>
            <option value="project">Update entire project</option>
          </select>
          {scope !== 'selected' && (
            <select className="input !w-44 !h-8" value={projectId} onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : '')}>
              <option value="">project…</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
            </select>
          )}
          {scope === 'future' && (
            <select className="input !w-44 !h-8" value={fromShot} onChange={(e) => setFromShot(e.target.value ? Number(e.target.value) : '')}>
              <option value="">from shot…</option>
              {usage.shots.filter((s) => !projectId || s.project_id === projectId).map((s) => <option key={s.shot_id} value={s.shot_id}>shot {s.shot_id}{s.title ? ` “${s.title}”` : ''}</option>)}
            </select>
          )}
          <button className="btn-accent" onClick={propagate} disabled={(scope === 'selected' && !shotIds.length) || (scope !== 'selected' && !projectId) || (scope === 'future' && !fromShot)}>Apply</button>
        </div>
      </div>
      <p className="text-[11.5px] text-faint">Provenance: {String(asset.provenance.origin ?? 'manual')} · created {timeAgo(asset.created_at)}</p>
    </div>
  )
}
