import { useRef, useState } from 'react'
import { PostCard as PostCardData } from '../api'
import { firstLine, formatDuration } from '../lib/format'

export function PostCard({
  post,
  onOpen,
  onToggleFavorite,
  onSave,
  showPromptCaption = true,
}: {
  post: PostCardData
  onOpen: (id: number) => void
  onToggleFavorite: (post: PostCardData) => void
  onSave: (post: PostCardData, anchor: DOMRect) => void
  showPromptCaption?: boolean
}) {
  const [loaded, setLoaded] = useState(false)
  const [hover, setHover] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const isVideo = post.media_type === 'video'

  return (
    <figure
      className="group relative w-full h-full rounded-el overflow-hidden bg-well border border-line/60 cursor-zoom-in"
      onMouseEnter={() => {
        setHover(true)
        videoRef.current?.play().catch(() => undefined)
      }}
      onMouseLeave={() => {
        setHover(false)
        videoRef.current?.pause()
      }}
      onClick={() => onOpen(post.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen(post.id)
      }}
      tabIndex={0}
      role="button"
      aria-label={firstLine(post.prompt) || `${post.platform} ${post.media_type}`}
    >
      {post.thumb_url && (
        <img
          src={post.thumb_url}
          alt=""
          loading="lazy"
          onLoad={() => setLoaded(true)}
          className={`w-full h-full object-cover ${loaded ? 'thumb-loaded' : 'thumb-loading'} ${
            isVideo && hover ? 'opacity-0' : 'opacity-100'
          }`}
        />
      )}
      {isVideo && hover && post.media_url && (
        <video
          ref={videoRef}
          src={post.media_url}
          muted
          loop
          playsInline
          autoPlay
          poster={post.thumb_url ?? undefined}
          className="absolute inset-0 w-full h-full object-cover"
        />
      )}

      {/* quick actions */}
      <div
        className="absolute top-1.5 right-1.5 flex gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-fast"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          aria-label={post.favorite ? 'Unfavorite' : 'Favorite'}
          title={post.favorite ? 'Unfavorite' : 'Favorite'}
          className={`w-7 h-7 rounded-el backdrop-blur bg-ink/60 border border-line flex items-center justify-center text-[13px] transition-colors duration-fast hover:bg-ink/80 ${
            post.favorite ? 'text-ember' : 'text-fg'
          }`}
          onClick={() => onToggleFavorite(post)}
        >
          {post.favorite ? '★' : '☆'}
        </button>
        <button
          aria-label="Save to collection"
          title="Save to collection"
          className="w-7 h-7 rounded-el backdrop-blur bg-ink/60 border border-line flex items-center justify-center text-[12px] text-fg transition-colors duration-fast hover:bg-ink/80"
          onClick={(e) => onSave(post, (e.currentTarget as HTMLElement).getBoundingClientRect())}
        >
          🔖
        </button>
      </div>

      {/* favorite marker when not hovering */}
      {post.favorite && (
        <span className="absolute top-1.5 left-1.5 text-ember text-[12px] drop-shadow group-hover:opacity-0 transition-opacity duration-fast" aria-hidden>
          ★
        </span>
      )}

      {/* video duration badge */}
      {isVideo && (
        <span className="chip absolute bottom-1.5 right-1.5 bg-ink/70 backdrop-blur border-line/80 text-fg">
          ▶ {formatDuration(post.duration_s) || 'video'}
        </span>
      )}

      {/* prompt caption on hover */}
      {showPromptCaption && post.prompt && (
        <figcaption className="absolute inset-x-0 bottom-0 px-2.5 pt-8 pb-2 bg-gradient-to-t from-ink/90 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-fast pointer-events-none">
          <span className="text-[11.5px] leading-snug text-fg/90 line-clamp-2">
            {firstLine(post.prompt, 140)}
          </span>
        </figcaption>
      )}
    </figure>
  )
}
