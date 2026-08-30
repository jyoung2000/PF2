// Detail drawer: slides over the grid without losing scroll position.
// Full media, prompt + copy, params chips, tag editor, actions.
import { useEffect, useState } from 'react'
import { api, deletePost, getPost, patchPost, PostDetail } from '../api'
import { formatBytes, timeAgo } from '../lib/format'
import { toastError, toastSuccess } from '../lib/toast'
import { ConfirmModal, Spinner } from './Primitives'
import { TagEditor } from './TagEditor'

function CopyButton({ text, label = 'Copy prompt' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      className={`btn h-7 py-0 text-[12px] ${copied ? '!border-emerald-400/60 text-emerald-300' : ''}`}
      onClick={() => {
        navigator.clipboard
          .writeText(text)
          .then(() => {
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1600)
          })
          .catch(() => toastError('Clipboard unavailable'))
      }}
    >
      {copied ? '✓ Copied' : label}
    </button>
  )
}

function ParamChips({ params }: { params: Record<string, unknown> }) {
  const entries = Object.entries(params).filter(
    ([k, v]) => v !== null && v !== '' && k !== 'workflow' && typeof v !== 'object',
  )
  if (!entries.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([k, v]) => (
        <span key={k} className="chip">
          <span className="text-faint">{k}</span> {String(v)}
        </span>
      ))}
    </div>
  )
}

export function DetailDrawer({
  postId,
  onClose,
  onChanged,
  onDeleted,
  onSearchTag,
  onSaveToCollection,
  collectionContext,
  onRemovedFromCollection,
  extraActions,
}: {
  postId: number
  onClose: () => void
  onChanged?: (p: PostDetail) => void
  onDeleted?: (id: number) => void
  onSearchTag?: (tag: string) => void
  onSaveToCollection?: (p: PostDetail) => void
  collectionContext?: { id: number; name: string }
  onRemovedFromCollection?: (postId: number) => void
  extraActions?: (p: PostDetail) => React.ReactNode
}) {
  const [post, setPost] = useState<PostDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [pushing, setPushing] = useState<string | null>(null)

  useEffect(() => {
    setPost(null)
    setError(null)
    getPost(postId)
      .then(setPost)
      .catch((e: Error) => setError(e.message))
  }, [postId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [onClose])

  const toggleFavorite = async () => {
    if (!post) return
    try {
      const updated = await patchPost(post.id, { favorite: !post.favorite })
      setPost(updated)
      onChanged?.(updated)
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const push = async (target: 'baserow' | 'discord') => {
    if (!post) return
    setPushing(target)
    try {
      await api.post(`/api/posts/${post.id}/push/${target}`)
      toastSuccess(target === 'baserow' ? 'Sent to Baserow' : 'Posted to Discord')
      const updated = await getPost(post.id)
      setPost(updated)
      onChanged?.(updated)
    } catch (e) {
      toastError(`${target === 'baserow' ? 'Baserow' : 'Discord'}: ${(e as Error).message}`)
    } finally {
      setPushing(null)
    }
  }

  const doDelete = async () => {
    if (!post) return
    try {
      await deletePost(post.id)
      toastSuccess('Post deleted')
      onDeleted?.(post.id)
      onClose()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const removeFromCollection = async () => {
    if (!post || !collectionContext) return
    try {
      await api.delete(`/api/collections/${collectionContext.id}/posts/${post.id}`)
      toastSuccess(`Removed from “${collectionContext.name}”`)
      onRemovedFromCollection?.(post.id)
      onClose()
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-[60] bg-ink/60 backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <aside
        role="dialog"
        aria-modal
        aria-label="Post details"
        className="fixed inset-y-0 right-0 z-[65] w-full sm:w-[560px] bg-panel border-l border-line shadow-2xl shadow-black/60 overflow-y-auto fade-in"
      >
        <div className="sticky top-0 z-10 flex items-center justify-between px-4 py-2.5 bg-panel/95 backdrop-blur border-b border-line">
          <span className="text-[12px] text-mute">
            {post ? (
              <>
                <span className="capitalize">{post.platform}</span>
                {post.author && <> · {post.author}</>} · {timeAgo(post.posted_at ?? post.scraped_at)}
              </>
            ) : (
              'Loading…'
            )}
          </span>
          <button className="btn-ghost px-2 py-1" onClick={onClose} aria-label="Close details">
            ✕
          </button>
        </div>

        {error && (
          <div className="p-6 text-[13px] text-red-300">
            Couldn't load this post: {error}
          </div>
        )}
        {!post && !error && (
          <div className="p-10 flex justify-center">
            <Spinner className="w-6 h-6" />
          </div>
        )}

        {post && (
          <div className="pb-8">
            <div className="bg-ink flex items-center justify-center max-h-[62vh] overflow-hidden">
              {post.media_type === 'video' && post.media_url ? (
                <video
                  src={post.media_url}
                  controls
                  loop
                  autoPlay
                  muted
                  playsInline
                  poster={post.thumb_url ?? undefined}
                  className="max-h-[62vh] w-auto max-w-full"
                />
              ) : (
                post.media_url && (
                  <img src={post.media_url} alt={post.prompt ?? ''} className="max-h-[62vh] w-auto max-w-full object-contain" />
                )
              )}
            </div>

            <div className="px-4 pt-4 space-y-5">
              {/* actions */}
              <div className="flex flex-wrap gap-1.5">
                <button
                  className={`btn h-7 py-0 text-[12px] ${post.favorite ? '!border-ember/70 text-ember' : ''}`}
                  onClick={toggleFavorite}
                >
                  {post.favorite ? '★ Favorited' : '☆ Favorite'}
                </button>
                <button className="btn h-7 py-0 text-[12px]" onClick={() => onSaveToCollection?.(post)}>
                  🔖 Save
                </button>
                <button className="btn h-7 py-0 text-[12px]" disabled={pushing !== null} onClick={() => push('baserow')}>
                  {pushing === 'baserow' ? <Spinner /> : post.synced_to_baserow ? '✓ In Baserow' : 'Send to Baserow'}
                </button>
                <button className="btn h-7 py-0 text-[12px]" disabled={pushing !== null} onClick={() => push('discord')}>
                  {pushing === 'discord' ? <Spinner /> : post.posted_to_discord ? '✓ Posted' : 'Post to Discord'}
                </button>
                {extraActions?.(post)}
                {collectionContext && (
                  <button className="btn-danger h-7 py-0 text-[12px]" onClick={removeFromCollection}>
                    Remove from collection
                  </button>
                )}
                <button className="btn-danger h-7 py-0 text-[12px] ml-auto" onClick={() => setConfirmDelete(true)}>
                  Delete
                </button>
              </div>

              {/* prompt */}
              <section>
                <div className="flex items-center justify-between mb-1.5">
                  <h3 className="label !mb-0">Prompt</h3>
                  {post.prompt && <CopyButton text={post.prompt} />}
                </div>
                {post.prompt ? (
                  <p className="max-w-measure text-[13.5px] leading-relaxed whitespace-pre-wrap bg-well border border-line rounded-el p-3">
                    {post.prompt}
                  </p>
                ) : (
                  <p className="text-faint text-[13px]">No prompt captured for this post.</p>
                )}
              </section>

              {post.negative_prompt && (
                <section>
                  <div className="flex items-center justify-between mb-1.5">
                    <h3 className="label !mb-0">Negative prompt</h3>
                    <CopyButton text={post.negative_prompt} label="Copy" />
                  </div>
                  <p className="max-w-measure text-[12.5px] text-mute whitespace-pre-wrap bg-well/60 border border-line rounded-el p-3">
                    {post.negative_prompt}
                  </p>
                </section>
              )}

              {/* model + params */}
              <section>
                <h3 className="label">Model & parameters</h3>
                <div className="flex flex-wrap gap-1.5">
                  {post.model_name && (
                    <span className="chip !text-fg !border-mute/40">{post.model_name}</span>
                  )}
                  {post.model_family_label && post.model_family_label !== post.model_name && (
                    <span className="chip">{post.model_family_label}</span>
                  )}
                  {post.model_version && <span className="chip">{post.model_version}</span>}
                  {post.width && post.height && (
                    <span className="chip">
                      {post.width}×{post.height}
                    </span>
                  )}
                </div>
                <div className="mt-1.5">
                  <ParamChips params={post.params} />
                </div>
                {post.technique_tags.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {post.technique_tags.map((t) => (
                      <span key={t} className="chip !text-ember-soft border-ember/30">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </section>

              {/* tags */}
              <section>
                <h3 className="label">Your tags</h3>
                <TagEditor
                  postId={post.id}
                  tags={post.tags}
                  onTagsChange={(tags) => {
                    const updated = { ...post, tags }
                    setPost(updated)
                    onChanged?.(updated)
                  }}
                  onTagClick={onSearchTag}
                />
              </section>

              {/* source + storage */}
              <section className="text-[12px] text-faint space-y-1 border-t border-line pt-3">
                {post.source_url && (
                  <p>
                    Source:{' '}
                    <a
                      href={post.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-mute hover:text-ember underline underline-offset-2"
                    >
                      {post.source_url}
                    </a>
                  </p>
                )}
                {post.collections.length > 0 && (
                  <p>In collections: {post.collections.map((c) => c.name).join(', ')}</p>
                )}
                {post.original_bytes != null && post.stored_bytes != null && (
                  <p>
                    Storage: {formatBytes(post.stored_bytes)} (saved{' '}
                    {formatBytes(Math.max(0, post.original_bytes - post.stored_bytes))} via compression)
                  </p>
                )}
                <p>
                  {post.origin === 'generated' ? 'Generated in PromptForge' : 'Scraped'} ·{' '}
                  {timeAgo(post.scraped_at)}
                </p>
              </section>
            </div>
          </div>
        )}
      </aside>
      {confirmDelete && post && (
        <ConfirmModal
          title="Delete this post?"
          message="The post and its media files are removed from PromptForge. This can't be undone."
          onConfirm={doDelete}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </>
  )
}
