// The full browsing experience (search bar → filter bar → masonry → drawer),
// reused by Gallery, Collections and Model pages via fixedParams.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { PostCard as PostCardData, PostDetail, searchPosts, SearchParams, patchPost } from '../api'
import { toastError } from '../lib/toast'
import { useInfiniteSentinel } from '../lib/hooks'
import { DetailDrawer } from './DetailDrawer'
import { FilterBar, GalleryFilters } from './FilterBar'
import { MasonryGrid } from './MasonryGrid'
import { PostCard } from './PostCard'
import { EmptyState, ErrorState, SkeletonGrid, Spinner } from './Primitives'
import { SaveTarget, SaveToCollectionPopover } from './SaveToCollectionPopover'
import { SearchBar } from './SearchBar'

export function PostGallery({
  fixedParams = {},
  hidePlatform = false,
  hideModel = false,
  collectionContext,
  emptyTitle = 'No posts yet',
  emptyHint = 'Enable a scraper and hit “Run now” — fresh prompts will start landing here.',
  emptyAction,
  extraDrawerActions,
}: {
  fixedParams?: Partial<SearchParams>
  hidePlatform?: boolean
  hideModel?: boolean
  collectionContext?: { id: number; name: string }
  emptyTitle?: string
  emptyHint?: string
  emptyAction?: React.ReactNode
  extraDrawerActions?: (p: PostDetail) => React.ReactNode
}) {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const openPost = params.get('post')
  const [filters, setFilters] = useState<GalleryFilters>({})
  const [posts, setPosts] = useState<PostCardData[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saveTarget, setSaveTarget] = useState<SaveTarget | null>(null)
  const generation = useRef(0)

  const setQ = useCallback(
    (next: string) => {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev)
          if (next) p.set('q', next)
          else p.delete('q')
          return p
        },
        { replace: true },
      )
    },
    [setParams],
  )

  const buildParams = useCallback(
    (cur: number | null): SearchParams => ({
      q: q || undefined,
      cursor: cur ?? undefined,
      limit: 40,
      ...filters,
      ...fixedParams,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [q, filters, JSON.stringify(fixedParams)],
  )

  useEffect(() => {
    const gen = ++generation.current
    setLoading(true)
    setError(null)
    searchPosts(buildParams(null))
      .then((page) => {
        if (generation.current !== gen) return
        setPosts(page.items)
        setCursor(page.next_cursor)
      })
      .catch((e: Error) => generation.current === gen && setError(e.message))
      .finally(() => generation.current === gen && setLoading(false))
  }, [buildParams])

  const loadMore = useCallback(() => {
    if (loadingMore || loading || cursor === null) return
    const gen = generation.current
    setLoadingMore(true)
    searchPosts(buildParams(cursor))
      .then((page) => {
        if (generation.current !== gen) return
        setPosts((prev) => {
          const seen = new Set(prev.map((p) => p.id))
          return [...prev, ...page.items.filter((p) => !seen.has(p.id))]
        })
        setCursor(page.next_cursor)
      })
      .catch((e: Error) => toastError(`Couldn't load more: ${e.message}`))
      .finally(() => setLoadingMore(false))
  }, [buildParams, cursor, loading, loadingMore])

  const sentinel = useInfiniteSentinel(loadMore, cursor !== null && !loading)

  const toggleFavorite = async (post: PostCardData) => {
    try {
      const updated = await patchPost(post.id, { favorite: !post.favorite })
      setPosts((prev) => prev.map((p) => (p.id === post.id ? { ...p, favorite: updated.favorite } : p)))
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const openDrawer = (id: number) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        p.set('post', String(id))
        return p
      },
      { replace: false },
    )
  const closeDrawer = () =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        p.delete('post')
        return p
      },
      { replace: false },
    )

  return (
    <div>
      <div className="sticky top-12 z-30 -mx-3 sm:-mx-5 px-3 sm:px-5 py-2.5 bg-ink/90 backdrop-blur border-b border-line/70 space-y-2">
        <SearchBar value={q} onChange={setQ} />
        <FilterBar filters={filters} onChange={setFilters} hidePlatform={hidePlatform} hideModel={hideModel} />
      </div>

      <div className="pt-4">
        {loading && <SkeletonGrid />}
        {error && !loading && <ErrorState message={error} onRetry={() => setFilters({ ...filters })} />}
        {!loading && !error && posts.length === 0 && (
          <EmptyState title={emptyTitle} hint={emptyHint} action={emptyAction} icon="✦" />
        )}
        {!loading && posts.length > 0 && (
          <MasonryGrid
            items={posts.map((p) => ({
              key: p.id,
              width: p.width,
              height: p.height,
              render: () => (
                <PostCard
                  post={p}
                  onOpen={openDrawer}
                  onToggleFavorite={toggleFavorite}
                  onSave={(post, rect) =>
                    setSaveTarget({ post, anchor: { top: rect.bottom + 6, left: rect.left } })
                  }
                />
              ),
            }))}
          />
        )}
        {loadingMore && (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        )}
        <div ref={sentinel} aria-hidden />
      </div>

      {openPost && (
        <DetailDrawer
          postId={Number(openPost)}
          onClose={closeDrawer}
          collectionContext={collectionContext}
          onChanged={(d) =>
            setPosts((prev) => prev.map((p) => (p.id === d.id ? { ...p, favorite: d.favorite } : p)))
          }
          onDeleted={(id) => setPosts((prev) => prev.filter((p) => p.id !== id))}
          onRemovedFromCollection={(id) => setPosts((prev) => prev.filter((p) => p.id !== id))}
          onSearchTag={(tag) => {
            closeDrawer()
            setQ(`tag:${tag}`)
          }}
          onSaveToCollection={(p) =>
            setSaveTarget({ post: p, anchor: { top: 80, left: window.innerWidth / 2 } })
          }
          extraActions={extraDrawerActions}
        />
      )}

      {saveTarget && (
        <SaveToCollectionPopover target={saveTarget} onClose={() => setSaveTarget(null)} />
      )}
    </div>
  )
}
