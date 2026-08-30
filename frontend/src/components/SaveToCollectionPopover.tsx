// Save-to-collection popover: existing collections (matching model family
// first), inline "New collection…", clear cross-family message (3.4).
import { useEffect, useState } from 'react'
import {
  ApiError,
  CollectionSummary,
  createCollection,
  listCollections,
  PostCard,
  saveToCollection,
} from '../api'
import { useDismiss } from '../lib/hooks'
import { toastError, toastSuccess } from '../lib/toast'
import { Spinner } from './Primitives'

export interface SaveTarget {
  post: PostCard
  anchor: { top: number; left: number }
}

export function SaveToCollectionPopover({
  target,
  onClose,
  onSaved,
}: {
  target: SaveTarget
  onClose: () => void
  onSaved?: (collection: CollectionSummary) => void
}) {
  const ref = useDismiss(onClose)
  const [collections, setCollections] = useState<CollectionSummary[] | null>(null)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState<string | null>(null)

  useEffect(() => {
    listCollections()
      .then((r) => {
        const family = target.post.model_family
        const sorted = [...r.user_collections].sort((a, b) => {
          const aMatch = a.model_family === family || a.allow_mixed_models || !a.model_family ? 0 : 1
          const bMatch = b.model_family === family || b.allow_mixed_models || !b.model_family ? 0 : 1
          return aMatch - bMatch
        })
        setCollections(sorted)
      })
      .catch((e: Error) => {
        setCollections([])
        toastError(`Couldn't load collections: ${e.message}`)
      })
  }, [target.post.id, target.post.model_family])

  const save = async (c: CollectionSummary) => {
    setBusy(true)
    setBlocked(null)
    try {
      await saveToCollection(c.id, target.post.id)
      toastSuccess(`Saved to “${c.name}”`)
      onSaved?.(c)
      onClose()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setBlocked(e.message)
      } else {
        toastError(`Couldn't save: ${(e as Error).message}`)
      }
    } finally {
      setBusy(false)
    }
  }

  const create = async () => {
    const name = newName.trim()
    if (!name) return
    setBusy(true)
    try {
      const c = await createCollection({ name })
      await save(c)
    } catch (e) {
      toastError(`Couldn't create collection: ${(e as Error).message}`)
      setBusy(false)
    }
  }

  const top = Math.min(target.anchor.top, window.innerHeight - 340)
  const left = Math.min(Math.max(8, target.anchor.left - 240), window.innerWidth - 268)

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="Save to collection"
      className="fixed z-[80] w-64 card shadow-2xl shadow-black/50 fade-in"
      style={{ top, left }}
    >
      <div className="px-3 py-2 border-b border-line text-[12px] text-mute font-medium">
        Save to collection
      </div>
      <div className="max-h-56 overflow-y-auto py-1">
        {collections === null && (
          <div className="px-3 py-3 flex justify-center">
            <Spinner />
          </div>
        )}
        {collections?.length === 0 && (
          <p className="px-3 py-2 text-[12px] text-faint">No collections yet — create one below.</p>
        )}
        {collections?.map((c) => {
          const family = target.post.model_family
          const mismatch =
            !!c.model_family && !!family && c.model_family !== family && !c.allow_mixed_models
          return (
            <button
              key={c.id}
              disabled={busy}
              className={`w-full text-left px-3 py-1.5 text-[13px] hover:bg-well flex items-center justify-between gap-2 ${
                mismatch ? 'opacity-50' : ''
              }`}
              title={
                mismatch
                  ? `This collection holds ${c.model_family_label} posts`
                  : `Save to ${c.name}`
              }
              onClick={() => save(c)}
            >
              <span className="truncate">{c.name}</span>
              <span className="chip shrink-0">
                {c.model_family_label ?? 'any'} · {c.count}
              </span>
            </button>
          )
        })}
      </div>
      {blocked && (
        <p className="px-3 py-2 text-[12px] text-amber-300 border-t border-line">{blocked}</p>
      )}
      <div className="p-2 border-t border-line">
        {creating ? (
          <div className="flex gap-1.5">
            <input
              autoFocus
              className="input h-8 text-[12.5px]"
              placeholder="Collection name"
              value={newName}
              aria-label="New collection name"
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') create()
              }}
            />
            <button className="btn-accent h-8 py-0" disabled={busy || !newName.trim()} onClick={create}>
              {busy ? <Spinner /> : 'Add'}
            </button>
          </div>
        ) : (
          <button className="btn-ghost w-full justify-center text-[12.5px]" onClick={() => setCreating(true)}>
            ＋ New collection…
          </button>
        )}
      </div>
    </div>
  )
}
