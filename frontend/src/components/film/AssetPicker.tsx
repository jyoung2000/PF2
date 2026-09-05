// Reusable visual AssetPicker (spec §26): search, type filter, thumbnails,
// current vs exact version, primary reference, create new, selected state.
import { useEffect, useMemo, useState } from 'react'
import { Modal, Spinner } from '../Primitives'
import { Asset, AssetType, AssetVersion, ASSET_TYPES, errorMessage, film } from '../../lib/film'
import { toastError } from '../../lib/toast'

export interface PickedAsset { asset_id: number; version_id: number | null; role: string; name: string; type: AssetType; thumb_url: string | null; version_label: string }

export function AssetThumb({ url, name, size = 40, ring = false }: { url: string | null; name: string; size?: number; ring?: boolean }) {
  return (
    <span className={`inline-flex items-center justify-center overflow-hidden rounded-el bg-well border ${ring ? 'border-ember' : 'border-line'} shrink-0`} style={{ width: size, height: size }} aria-hidden>
      {url ? <img src={url} alt="" className="w-full h-full object-cover" loading="lazy" /> : <span className="text-[11px] text-faint font-display">{name.slice(0, 2).toUpperCase()}</span>}
    </span>
  )
}

export function AssetPicker({
  types,
  selected = [],
  multi = true,
  title = 'Pick assets',
  onClose,
  onPick,
}: {
  types?: AssetType[]
  selected?: PickedAsset[]
  multi?: boolean
  title?: string
  onClose: () => void
  onPick: (picked: PickedAsset[]) => void
}) {
  const [q, setQ] = useState('')
  const [type, setType] = useState<AssetType | ''>(types?.length === 1 ? types[0] : '')
  const [assets, setAssets] = useState<Asset[] | null>(null)
  const [chosen, setChosen] = useState<PickedAsset[]>(selected)
  const [versionsFor, setVersionsFor] = useState<Asset | null>(null)
  const [creating, setCreating] = useState<{ type: AssetType; name: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => {
    setAssets(null)
    film
      .listAssets({ type: type || undefined, q: q || undefined })
      .then((r) => setAssets(r.assets.filter((a) => !types || types.includes(a.type))))
      .catch((e) => toastError(errorMessage(e)))
  }
  useEffect(load, [q, type]) // eslint-disable-line react-hooks/exhaustive-deps

  const isChosen = (id: number) => chosen.some((c) => c.asset_id === id)
  const toggle = (a: Asset, version: AssetVersion | null = null) => {
    const entry: PickedAsset = {
      asset_id: a.id, version_id: version ? version.id : null, role: a.type, name: a.name, type: a.type,
      thumb_url: version?.primary_thumb_url ?? a.thumb_url, version_label: version ? version.label : `${a.current_version.label} (current)`,
    }
    if (!multi) {
      onPick([entry])
      return
    }
    setChosen((cur) => (isChosen(a.id) && !version ? cur.filter((c) => c.asset_id !== a.id) : [...cur.filter((c) => c.asset_id !== a.id), entry]))
  }
  const create = async () => {
    if (!creating?.name.trim()) return
    setBusy(true)
    try {
      const a = await film.createAsset({ type: creating.type, name: creating.name.trim() })
      setCreating(null)
      setAssets((cur) => [a, ...(cur ?? [])])
      toggle(a)
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const typeList = useMemo(() => (types?.length ? types : ASSET_TYPES), [types])

  return (
    <Modal title={title} onClose={onClose} wide>
      <div className="space-y-3" data-testid="asset-picker">
        <div className="flex gap-2 items-center flex-wrap">
          <input className="input flex-1 min-w-[160px]" placeholder="Search assets…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search assets" autoFocus />
          {typeList.length > 1 && (
            <div className="flex gap-1">
              <button className={`chip ${type === '' ? '!border-ember text-fg' : ''}`} onClick={() => setType('')}>all</button>
              {typeList.map((t) => (
                <button key={t} className={`chip ${type === t ? '!border-ember text-fg' : ''}`} onClick={() => setType(t)}>{t}</button>
              ))}
            </div>
          )}
          <button className="btn text-[12px]" onClick={() => setCreating({ type: (type || typeList[0]) as AssetType, name: q })}>+ New</button>
        </div>
        {creating && (
          <div className="card !bg-well p-2.5 flex gap-2 items-center fade-in">
            <select className="input !w-32" value={creating.type} onChange={(e) => setCreating({ ...creating, type: e.target.value as AssetType })}>
              {typeList.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <input className="input flex-1" placeholder="Name" value={creating.name} onChange={(e) => setCreating({ ...creating, name: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && create()} />
            <button className="btn-accent" onClick={create} disabled={busy}>{busy ? <Spinner /> : 'Create'}</button>
            <button className="btn-ghost" onClick={() => setCreating(null)}>Cancel</button>
          </div>
        )}
        {assets === null ? (
          <div className="py-10 flex justify-center"><Spinner /></div>
        ) : assets.length === 0 ? (
          <p className="text-[12.5px] text-faint py-8 text-center">No assets yet — create one above.</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 max-h-[46vh] overflow-y-auto pr-1">
            {assets.map((a) => {
              const on = isChosen(a.id)
              const pick = chosen.find((c) => c.asset_id === a.id)
              return (
                <div key={a.id} className={`rounded-el border ${on ? 'border-ember' : 'border-line'} bg-panel p-2 flex flex-col gap-1.5`} data-asset-id={a.id}>
                  <button className="text-left" onClick={() => toggle(a)} aria-pressed={on}>
                    <div className="aspect-[4/3] rounded-el overflow-hidden bg-well flex items-center justify-center">
                      {a.thumb_url ? <img src={a.thumb_url} alt="" className="w-full h-full object-cover" loading="lazy" /> : <span className="font-display text-[22px] text-faint">{a.name.slice(0, 1)}</span>}
                    </div>
                    <div className="mt-1.5 flex items-center gap-1.5">
                      <span className="font-display text-[12.5px] font-medium truncate">{a.name}</span>
                      <span className="chip !text-[9.5px] ml-auto">{a.type}</span>
                    </div>
                    <div className="text-[10.5px] text-faint">{pick ? pick.version_label : `${a.current_version.label} · ${a.version_count} version${a.version_count === 1 ? '' : 's'}`}</div>
                  </button>
                  {a.version_count > 1 && (
                    <button className="btn-ghost text-[11px] px-1 py-0.5 self-start" onClick={() => setVersionsFor(a)}>exact version…</button>
                  )}
                </div>
              )
            })}
          </div>
        )}
        {versionsFor && (
          <VersionChooser asset={versionsFor} onClose={() => setVersionsFor(null)} onChoose={(v) => { toggle(versionsFor, v); setVersionsFor(null) }} />
        )}
        {multi && (
          <div className="flex items-center gap-2 justify-end pt-1 border-t border-line">
            <span className="text-[12px] text-faint mr-auto">{chosen.length} selected</span>
            <button className="btn" onClick={onClose}>Cancel</button>
            <button className="btn-accent" onClick={() => onPick(chosen)}>Use selection</button>
          </div>
        )}
      </div>
    </Modal>
  )
}

function VersionChooser({ asset, onClose, onChoose }: { asset: Asset; onClose: () => void; onChoose: (v: AssetVersion) => void }) {
  const [full, setFull] = useState<Asset | null>(null)
  useEffect(() => {
    film.getAsset(asset.id).then(setFull).catch((e) => toastError(errorMessage(e)))
  }, [asset.id])
  return (
    <div className="card !bg-well p-2.5 fade-in">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[12px] text-mute">Exact version of {asset.name}</span>
        <button className="btn-ghost text-[11px]" onClick={onClose}>close</button>
      </div>
      {!full ? <Spinner /> : (
        <div className="flex gap-2 overflow-x-auto">
          {(full.versions ?? []).map((v) => (
            <button key={v.id} className={`shrink-0 w-24 rounded-el border p-1.5 text-left ${v.id === full.current_version_id ? 'border-ember' : 'border-line'}`} onClick={() => onChoose(v)}>
              <AssetThumb url={v.primary_thumb_url} name={asset.name} size={84} />
              <div className="text-[11px] mt-1 truncate">{v.label}</div>
              <div className="text-[10px] text-faint">{v.frozen ? 'frozen' : 'draft'}{v.id === full.current_version_id ? ' · current' : ''}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
