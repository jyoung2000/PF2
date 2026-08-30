import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  CollectionSummary,
  createCollection,
  deleteCollection,
  getCollection,
  listCollections,
  updateCollection,
} from '../api'
import { PostGallery } from '../components/PostGallery'
import { ConfirmModal, EmptyState, Modal, SkeletonGrid } from '../components/Primitives'
import { useFetch } from '../lib/hooks'
import { toastError, toastSuccess } from '../lib/toast'

function CoverMosaic({ urls, className = '' }: { urls: string[]; className?: string }) {
  const cells = urls.slice(0, 4)
  return (
    <div className={`grid grid-cols-2 grid-rows-2 gap-px bg-line aspect-[4/3] overflow-hidden ${className}`}>
      {Array.from({ length: 4 }, (_, i) =>
        cells[i] ? (
          <img key={i} src={cells[i]} alt="" loading="lazy" className="w-full h-full object-cover" />
        ) : (
          <div key={i} className="bg-well" />
        ),
      )}
    </div>
  )
}

interface ModelCollection {
  family: string
  label: string
  count: number
  image_count: number
  video_count: number
  versions: string[]
  cover_urls: string[]
}

function ModelCollectionCard({ mc }: { mc: ModelCollection }) {
  return (
    <Link
      to={`/collections/model/${mc.family}`}
      className="card overflow-hidden group hover:border-mute/50 transition-colors duration-fast"
    >
      <CoverMosaic urls={mc.cover_urls} />
      <div className="p-3">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-display font-medium text-[14.5px] truncate">{mc.label}</h3>
          <span className="chip shrink-0">
            {mc.image_count} img{mc.video_count > 0 && ` · ${mc.video_count} vid`}
          </span>
        </div>
        {mc.versions.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1 max-h-11 overflow-hidden">
            {mc.versions.slice(0, 3).map((v) => (
              <span key={v} className="chip !text-[11px]">
                {v}
              </span>
            ))}
          </div>
        )}
      </div>
    </Link>
  )
}

function UserCollectionCard({ c, onChanged }: { c: CollectionSummary; onChanged: () => void }) {
  const [menu, setMenu] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [name, setName] = useState(c.name)
  return (
    <div className="card overflow-hidden group relative hover:border-mute/50 transition-colors duration-fast">
      <Link to={`/collections/${c.id}`} className="block">
        <CoverMosaic urls={c.cover_urls} />
        <div className="p-3">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="font-display font-medium text-[14.5px] truncate">{c.name}</h3>
            <span className="chip shrink-0">{c.count}</span>
          </div>
          <p className="text-[12px] text-faint mt-0.5">
            {c.model_family_label ?? 'Any model'}
            {c.allow_mixed_models && ' · mixed'}
          </p>
        </div>
      </Link>
      <button
        aria-label={`Options for ${c.name}`}
        className="absolute top-2 right-2 w-7 h-7 rounded-el bg-ink/60 border border-line backdrop-blur opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity duration-fast"
        onClick={() => setMenu((m) => !m)}
      >
        ⋯
      </button>
      {menu && (
        <div className="absolute top-10 right-2 z-20 card shadow-xl shadow-black/50 py-1 w-40">
          <button
            className="w-full text-left px-3 py-1.5 text-[13px] hover:bg-well"
            onClick={() => {
              setMenu(false)
              setRenaming(true)
            }}
          >
            Rename
          </button>
          <button
            className="w-full text-left px-3 py-1.5 text-[13px] hover:bg-well"
            onClick={async () => {
              setMenu(false)
              try {
                await updateCollection(c.id, { allow_mixed_models: !c.allow_mixed_models })
                toastSuccess(c.allow_mixed_models ? 'Mixed models disabled' : 'Mixed models enabled')
                onChanged()
              } catch (e) {
                toastError((e as Error).message)
              }
            }}
          >
            {c.allow_mixed_models ? 'Disable mixed models' : 'Allow mixed models'}
          </button>
          <button
            className="w-full text-left px-3 py-1.5 text-[13px] hover:bg-well text-red-300"
            onClick={() => {
              setMenu(false)
              setConfirmDelete(true)
            }}
          >
            Delete…
          </button>
        </div>
      )}
      {renaming && (
        <Modal title="Rename collection" onClose={() => setRenaming(false)}>
          <input
            className="input"
            value={name}
            autoFocus
            aria-label="Collection name"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={async (e) => {
              if (e.key === 'Enter' && name.trim()) {
                try {
                  await updateCollection(c.id, { name: name.trim() })
                  setRenaming(false)
                  onChanged()
                } catch (err) {
                  toastError((err as Error).message)
                }
              }
            }}
          />
          <div className="flex justify-end gap-2 mt-4">
            <button className="btn" onClick={() => setRenaming(false)}>
              Cancel
            </button>
            <button
              className="btn-accent"
              onClick={async () => {
                try {
                  await updateCollection(c.id, { name: name.trim() })
                  setRenaming(false)
                  onChanged()
                } catch (err) {
                  toastError((err as Error).message)
                }
              }}
            >
              Save
            </button>
          </div>
        </Modal>
      )}
      {confirmDelete && (
        <ConfirmModal
          title={`Delete “${c.name}”?`}
          message="The collection is removed. The posts inside stay in your library."
          onConfirm={async () => {
            try {
              await deleteCollection(c.id)
              toastSuccess('Collection deleted')
              onChanged()
            } catch (e) {
              toastError((e as Error).message)
            }
          }}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </div>
  )
}

export function CollectionsPage() {
  const { data, loading, reload } = useFetch(listCollections)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const navigate = useNavigate()

  const create = async () => {
    if (!newName.trim()) return
    try {
      const c = await createCollection({ name: newName.trim() })
      setCreating(false)
      setNewName('')
      navigate(`/collections/${c.id}`)
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  if (loading) return <SkeletonGrid count={8} />

  const mc = (data?.model_collections ?? []) as unknown as ModelCollection[]
  const uc = data?.user_collections ?? []

  return (
    <div className="space-y-8 fade-in">
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display font-medium text-[17px]">My collections</h2>
          <button className="btn-accent" onClick={() => setCreating(true)}>
            ＋ New collection
          </button>
        </div>
        {uc.length === 0 ? (
          <EmptyState
            title="No collections yet"
            hint="Save posts from the gallery with the 🔖 button — collections keep one model family together so styles stay consistent."
            icon="🔖"
          />
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {uc.map((c) => (
              <UserCollectionCard key={c.id} c={c} onChanged={reload} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="font-display font-medium text-[17px] mb-1">Model collections</h2>
        <p className="text-[12.5px] text-faint mb-3">
          Automatic — every model family seen in your library, kept current as new posts arrive.
        </p>
        {mc.length === 0 ? (
          <EmptyState
            title="No models seen yet"
            hint="Run a scraper and model collections appear here automatically."
            icon="◈"
          />
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {mc.map((m) => (
              <ModelCollectionCard key={m.family} mc={m} />
            ))}
          </div>
        )}
      </section>

      {creating && (
        <Modal title="New collection" onClose={() => setCreating(false)}>
          <label className="label" htmlFor="nc-name">
            Name
          </label>
          <input
            id="nc-name"
            className="input"
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && create()}
            placeholder="e.g. Moody portraits"
          />
          <p className="text-[12px] text-faint mt-2">
            The collection adopts the model family of the first post you save into it.
          </p>
          <div className="flex justify-end gap-2 mt-4">
            <button className="btn" onClick={() => setCreating(false)}>
              Cancel
            </button>
            <button className="btn-accent" disabled={!newName.trim()} onClick={create}>
              Create
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}

export function CollectionDetailPage() {
  const { id } = useParams()
  const collectionId = Number(id)
  const { data: collection, error } = useFetch(() => getCollection(collectionId), [collectionId])
  if (error) return <EmptyState title="Collection not found" hint={error} icon="⚠" />
  return (
    <div>
      <div className="flex items-baseline gap-3 mb-2 flex-wrap">
        <h1 className="font-display font-medium text-[19px]">{collection?.name ?? '…'}</h1>
        {collection?.model_family_label && <span className="chip">{collection.model_family_label}</span>}
        {collection && <span className="text-[12.5px] text-faint">{collection.count} items</span>}
        <Link to="/collections" className="text-[12.5px] text-mute hover:text-fg ml-auto">
          ← All collections
        </Link>
      </div>
      {collection?.description && <p className="text-mute text-[13px] mb-2">{collection.description}</p>}
      <PostGallery
        fixedParams={{ collection_id: collectionId }}
        hidePlatform
        collectionContext={collection ? { id: collection.id, name: collection.name } : undefined}
        emptyTitle="This collection is empty"
        emptyHint="Save posts from the gallery — hover a card and hit 🔖, or use Save in the detail view."
      />
    </div>
  )
}

export function ModelCollectionPage() {
  const { family } = useParams()
  return (
    <div>
      <div className="flex items-baseline gap-3 mb-2">
        <h1 className="font-display font-medium text-[19px] capitalize">{family?.replace(/-/g, ' ')}</h1>
        <span className="chip">model collection</span>
        <Link to="/collections" className="text-[12.5px] text-mute hover:text-fg ml-auto">
          ← All collections
        </Link>
      </div>
      <PostGallery
        fixedParams={{ model: family }}
        hideModel
        emptyTitle="Nothing here yet"
        emptyHint="Posts for this model family will appear as scrapers find them."
      />
    </div>
  )
}
