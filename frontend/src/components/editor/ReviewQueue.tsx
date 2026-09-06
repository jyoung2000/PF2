// Generation review queue (Editor E6): every finished-but-undecided take in
// one place — approve, reject (with note), regenerate (cost shown, budget
// approval honoured), compare against the shot's current take, and swap
// into the timeline. Decisions land on the take; nothing is auto-deleted.
import { useState } from 'react'
import { errorMessage, film, fmtUsd, Take } from '../../lib/film'
import { seq as seqApi, Sequence } from '../../lib/editor'
import { useFetch } from '../../lib/hooks'
import { toastError, toastSuccess } from '../../lib/toast'
import { Spinner } from '../Primitives'

interface QueueItem {
  take: Take
  shot_id: number
  shot_label: string
  shot_title: string | null
  selected_on_shot: boolean
  sequence_clip_id: number | null
  review: { status: string; note?: string | null } | null
}

export function ReviewQueue({ projectId, onClose, onSequence, onOpenShot }: {
  projectId: number
  onClose: () => void
  onSequence: (s: Sequence) => void
  onOpenShot: (shotId: number) => void
}) {
  const data = useFetch(() => film.reviewQueue(projectId), [projectId])
  const [busy, setBusy] = useState<number | null>(null)
  const [compare, setCompare] = useState<QueueItem | null>(null)
  const q = data.data
  const decide = (item: QueueItem, status: 'approved' | 'rejected' | null, note?: string) => {
    film.reviewTake(item.take.id, status, note).then(() => data.reload()).catch((e) => toastError(errorMessage(e)))
  }
  const regenerate = async (item: QueueItem, approve = false) => {
    setBusy(item.take.id)
    try {
      await film.createTake(item.shot_id, { kind: item.take.kind === 'image' ? 'image' : 'video', approve_cost: approve })
      toastSuccess(`New take queued for shot ${item.shot_label}`)
      data.reload()
    } catch (e: any) {
      const info = e?.info
      if (info?.budget?.requires_approval && !approve) {
        if (window.confirm(`${info.message ?? 'Budget approval required.'}\nApprove ${fmtUsd(info.budget.amount_usd)} and generate?`)) return regenerate(item, true)
      } else toastError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  const useInTimeline = (item: QueueItem) => {
    if (!item.sequence_clip_id) return
    seqApi.setTake(item.sequence_clip_id, item.take.id).then((s) => { onSequence(s); toastSuccess('Timeline clip updated') }).catch((e) => toastError(errorMessage(e)))
  }
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose} data-testid="review-queue">
      <div className="card p-4 max-w-3xl w-full max-h-[86vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center mb-2">
          <h3 className="font-display text-[15px] flex-1">Review queue {q && <span className="text-faint text-[12px]">· {q.counts.pending} awaiting · {q.counts.failed} failed</span>}</h3>
          <button className="btn-ghost" onClick={onClose}>✕</button>
        </div>
        {!q && <Spinner />}
        {q && q.pending.length === 0 && <p className="text-[12.5px] text-faint mb-2">Nothing awaiting review — takes land here as generations finish.</p>}
        {q?.pending.map((item: QueueItem) => (
          <Row key={item.take.id} item={item} busy={busy === item.take.id}
               onApprove={() => decide(item, 'approved')}
               onReject={() => { const note = window.prompt('Why reject? (goes on the take)') ?? undefined; decide(item, 'rejected', note) }}
               onRegen={() => regenerate(item)} onCompare={() => setCompare(item)}
               onUse={item.sequence_clip_id ? () => useInTimeline(item) : undefined}
               onOpenShot={() => onOpenShot(item.shot_id)} />
        ))}
        {q && q.failed.length > 0 && (
          <details className="mt-2 text-[12px]"><summary className="cursor-pointer text-red-300">{q.failed.length} failed take(s)</summary>
            {q.failed.map((item: QueueItem) => (
              <div key={item.take.id} className="flex items-center gap-2 py-1">
                <span className="font-mono text-faint">{item.shot_label}</span>
                <span className="text-faint truncate flex-1">{item.take.error ?? 'failed'}</span>
                <button className="btn text-[11px] py-0.5" disabled={busy === item.take.id} onClick={() => regenerate(item)}>Regenerate</button>
              </div>
            ))}
          </details>
        )}
        {q && q.decided.length > 0 && (
          <details className="mt-2 text-[12px]"><summary className="cursor-pointer text-faint">Recently decided ({q.decided.length})</summary>
            {q.decided.map((item: QueueItem) => (
              <div key={item.take.id} className="flex items-center gap-2 py-1">
                <span className="font-mono text-faint">{item.shot_label}</span>
                <span className={item.review?.status === 'approved' ? 'text-emerald-300' : 'text-red-300'}>{item.review?.status}</span>
                {item.review?.note && <span className="text-faint truncate flex-1" title={item.review.note}>{item.review.note}</span>}
                <button className="btn-ghost text-[11px]" onClick={() => decide(item, null)}>reopen</button>
              </div>
            ))}
          </details>
        )}
        {compare && <ComparePanel item={compare} onClose={() => setCompare(null)} />}
      </div>
    </div>
  )
}

function Row({ item, busy, onApprove, onReject, onRegen, onCompare, onUse, onOpenShot }: {
  item: QueueItem
  busy: boolean
  onApprove: () => void
  onReject: () => void
  onRegen: () => void
  onCompare: () => void
  onUse?: () => void
  onOpenShot: () => void
}) {
  const t = item.take
  return (
    <div className="card !bg-well p-2 mb-1.5 flex items-center gap-2.5 text-[12px]" data-testid={`review-item-${t.id}`}>
      {t.thumb_url ? <img src={t.thumb_url} alt="" className="w-20 aspect-video object-cover rounded" /> : <div className="w-20 aspect-video bg-ink rounded" />}
      <div className="flex-1 min-w-0">
        <button className="font-medium hover:underline" onClick={onOpenShot}>{item.shot_label} {item.shot_title ?? ''}</button>
        <div className="text-faint">take {t.number} · {t.kind}{t.provider ? ` · ${t.provider}` : ''}{t.cost_actual != null ? ` · ${fmtUsd(t.cost_actual)}` : t.cost_estimate != null ? ` · est ${fmtUsd(t.cost_estimate)}` : ''}
          {item.selected_on_shot ? ' · shot’s pick' : ''}{item.sequence_clip_id ? ' · in timeline' : ''}</div>
      </div>
      <button className="btn text-[11.5px] py-1" onClick={onApprove} data-testid={`approve-${t.id}`}>✓ Approve</button>
      <button className="btn text-[11.5px] py-1" onClick={onReject}>✗ Reject</button>
      <button className="btn-ghost text-[11.5px]" onClick={onCompare}>Compare</button>
      <button className="btn-ghost text-[11.5px]" disabled={busy} onClick={onRegen} title={t.cost_estimate != null ? `Roughly ${fmtUsd(t.cost_estimate)} again` : 'Generate a new take'}>{busy ? <Spinner /> : '↻ Regenerate'}</button>
      {onUse && <button className="btn-accent text-[11.5px] py-1" onClick={onUse}>Use in timeline</button>}
    </div>
  )
}

function ComparePanel({ item, onClose }: { item: QueueItem; onClose: () => void }) {
  const data = useFetch(() => film.takes(item.shot_id), [item.shot_id])
  const takes = (data.data?.takes ?? []).filter((t) => (t.status === 'succeeded' || t.status === 'imported') && t.media_url)
  return (
    <div className="mt-3 border-t border-line pt-2" data-testid="compare-panel">
      <div className="flex items-center"><h4 className="font-display text-[13px] flex-1">Takes of shot {item.shot_label}</h4><button className="btn-ghost text-[11px]" onClick={onClose}>close</button></div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-1.5">
        {takes.map((t) => (
          <figure key={t.id} className={`rounded-el overflow-hidden border ${t.id === item.take.id ? 'border-ember' : 'border-line'}`}>
            {t.kind === 'image' ? <img src={t.media_url!} alt="" className="w-full aspect-video object-cover" /> : <video src={t.media_url!} controls className="w-full aspect-video bg-ink" />}
            <figcaption className="text-[10.5px] text-faint px-1 py-0.5">take {t.number}{t.review ? ` · ${t.review.status}` : ''}{t.id === item.take.id ? ' · reviewing' : ''}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  )
}
