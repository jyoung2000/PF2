// Footage picker (spec D/E): search configured stock/archival sources or the
// local corpus (your own footage, indexed by segment), preview, attach to a
// shot with license/attribution preserved; upload your own footage.
import { useEffect, useRef, useState } from 'react'
import { Modal, Spinner } from '../Primitives'
import { Clip, errorMessage, film, FootageResult } from '../../lib/film'
import { toastError, toastSuccess } from '../../lib/toast'

export function FootageModal({ shotId, projectId, initialQuery = '', onClose, onAttached }: { shotId: number; projectId: number; initialQuery?: string; onClose: () => void; onAttached: () => void }) {
  const [tab, setTab] = useState<'stock' | 'mine'>('mine')
  const [q, setQ] = useState(initialQuery)
  const [mediaType, setMediaType] = useState<'video' | 'image'>('video')
  const [sources, setSources] = useState<{ key: string; label: string; configured: boolean; media: string[]; key_url: string | null }[]>([])
  const [results, setResults] = useState<{ results: FootageResult[]; errors: Record<string, string>; needs_setup: string[] } | null>(null)
  const [mine, setMine] = useState<any[] | Clip[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    film.footageSources().then((r) => setSources(r.sources)).catch(() => undefined)
  }, [])
  const searchStock = async () => {
    if (!q.trim()) return
    setBusy('search')
    try {
      setResults(await film.footageSearch(q, mediaType))
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  const searchMine = async () => {
    setBusy('mine')
    try {
      const r = await film.clips(q.trim() || undefined, projectId)
      setMine(r.results ?? r.clips ?? [])
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  useEffect(() => {
    if (tab === 'mine') searchMine()
  }, [tab]) // eslint-disable-line react-hooks/exhaustive-deps
  const attachStock = async (r: FootageResult) => {
    setBusy(r.source_id)
    try {
      await film.footageAttach(shotId, r)
      toastSuccess(`Attached — ${r.attribution ?? r.source}${r.license ? ` (${r.license.name})` : ' (license unknown)'}`)
      onAttached()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  const attachMine = async (clipId: number, seg?: { start_s: number; end_s: number }) => {
    setBusy(`clip${clipId}`)
    try {
      await film.clipAttach(clipId, { shot_id: shotId, start_s: seg?.start_s, end_s: seg?.end_s })
      toastSuccess('Footage attached as a take')
      onAttached()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  const uploadMine = async (f: File) => {
    setBusy('upload')
    try {
      const c = await film.footageUpload(f, { project_id: projectId, title: f.name })
      toastSuccess(`Analysed: ${c.segments.length} segment(s)${c.pacing ? `, median ${c.pacing.median_s}s` : ''}`)
      searchMine()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  return (
    <Modal title="Footage" onClose={onClose} wide>
      <div className="space-y-3" data-testid="footage-modal">
        <div className="flex gap-1">
          <button className={`chip ${tab === 'mine' ? '!border-ember text-fg' : ''}`} onClick={() => setTab('mine')}>My footage</button>
          <button className={`chip ${tab === 'stock' ? '!border-ember text-fg' : ''}`} onClick={() => setTab('stock')}>Stock & archives</button>
          <span className="ml-auto text-[11px] text-faint self-center">licenses are stored exactly as the source reports them</span>
        </div>
        <div className="flex gap-2 items-center">
          <input className="input flex-1" placeholder={tab === 'mine' ? '“wide shot of the city at night”' : 'city at night rain'} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && (tab === 'mine' ? searchMine() : searchStock())} />
          {tab === 'stock' && <select className="input !w-24" value={mediaType} onChange={(e) => setMediaType(e.target.value as 'video' | 'image')}><option value="video">video</option><option value="image">image</option></select>}
          <button className="btn-accent" onClick={tab === 'mine' ? searchMine : searchStock} disabled={busy === 'search' || busy === 'mine'}>{busy === 'search' || busy === 'mine' ? <Spinner /> : 'Search'}</button>
          {tab === 'mine' && <><button className="btn" onClick={() => fileRef.current?.click()} disabled={busy === 'upload'}>{busy === 'upload' ? <Spinner /> : 'Upload footage'}</button><input ref={fileRef} type="file" accept="video/*,image/*" hidden onChange={(e) => e.target.files?.[0] && uploadMine(e.target.files[0])} /></>}
        </div>
        {tab === 'stock' && (
          <div className="flex flex-wrap gap-1 text-[11px]">
            {sources.filter((s) => s.media.includes(mediaType)).map((s) => <span key={s.key} className={`chip ${s.configured ? '' : 'opacity-60'}`} title={s.configured ? 'configured' : s.key_url ? `needs an API key — ${s.key_url}` : ''}>{s.label}{s.configured ? '' : ' · needs key'}</span>)}
          </div>
        )}
        {tab === 'stock' && results && (
          <div className="space-y-2">
            {Object.entries(results.errors).map(([k, v]) => <p key={k} className="text-[11.5px] text-amber-300">{k}: {v}</p>)}
            {results.results.length === 0 && <p className="text-[12.5px] text-faint">No results.</p>}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-[46vh] overflow-y-auto">
              {results.results.map((r) => (
                <div key={r.source + r.source_id} className="card p-1.5 text-[11px]">
                  <div className="aspect-video bg-well rounded-el overflow-hidden">{r.thumb_url && <img src={r.thumb_url} alt="" className="w-full h-full object-cover" loading="lazy" />}</div>
                  <div className="mt-1 truncate font-medium" title={r.title ?? ''}>{r.title ?? r.source_id}</div>
                  <div className="text-faint truncate">{r.source}{r.duration_s ? ` · ${r.duration_s}s` : ''}{r.width ? ` · ${r.width}×${r.height}` : ''}</div>
                  <div className="text-faint truncate" title={r.license?.url ?? ''}>{r.license ? r.license.name : 'license unknown — check the source'}</div>
                  <div className="flex gap-1 mt-1"><button className="btn text-[11px] py-0.5 flex-1" onClick={() => attachStock(r)} disabled={busy != null}>{busy === r.source_id ? <Spinner /> : 'Attach'}</button>{r.page_url && <a className="btn-ghost text-[11px] py-0.5" href={r.page_url} target="_blank" rel="noreferrer">↗</a>}</div>
                </div>
              ))}
            </div>
          </div>
        )}
        {tab === 'mine' && mine && (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-[46vh] overflow-y-auto">
            {mine.length === 0 && <p className="text-[12.5px] text-faint col-span-full">No footage in the corpus yet — upload a clip; it is analysed (cuts, keyframes, pacing) and indexed for search.</p>}
            {mine.map((c: any, i: number) => {
              const isHit = 'confidence' in c
              const clipId = isHit ? c.clip_id : c.id
              const seg = isHit ? c.segment : null
              return (
                <div key={i} className="card p-1.5 text-[11px]">
                  <div className="aspect-video bg-well rounded-el overflow-hidden">{c.thumb_url && <img src={c.thumb_url} alt="" className="w-full h-full object-cover" loading="lazy" />}</div>
                  <div className="mt-1 truncate font-medium">{c.title}</div>
                  <div className="text-faint">{isHit ? `${c.timecode} · confidence ${Math.round(c.confidence * 100)}%` : `${c.segments?.length ?? 0} segment(s)${c.duration_s ? ` · ${c.duration_s.toFixed(1)}s` : ''}`}</div>
                  {isHit && c.matched?.length > 0 && <div className="text-faint truncate">matched: {c.matched.join(', ')}</div>}
                  <button className="btn text-[11px] py-0.5 w-full mt-1" onClick={() => attachMine(clipId, seg ?? undefined)} disabled={busy != null}>{busy === `clip${clipId}` ? <Spinner /> : seg ? 'Attach segment' : 'Attach clip'}</button>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </Modal>
  )
}
