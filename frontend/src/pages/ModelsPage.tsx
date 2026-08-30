import { Link } from 'react-router-dom'
import { getModelsMeta } from '../api'
import { EmptyState, SkeletonGrid } from '../components/Primitives'
import { timeAgo } from '../lib/format'
import { useFetch } from '../lib/hooks'

export function ModelsPage() {
  const { data, loading, error } = useFetch(getModelsMeta)

  if (loading) return <SkeletonGrid count={8} />
  if (error) return <EmptyState title="Couldn't load models" hint={error} icon="⚠" />

  const models = data?.models ?? []

  return (
    <div className="fade-in">
      <div className="mb-4">
        <h1 className="font-display font-medium text-[19px]">Models</h1>
        <p className="text-[12.5px] text-faint">
          Every model family seen in your library — fully data-driven, new models surface here the moment
          posts arrive. Click one to browse its collection.
        </p>
      </div>
      {models.length === 0 ? (
        <EmptyState
          title="No models seen yet"
          hint="Run a scraper — every model in scraped prompts appears here automatically."
          icon="◈"
        />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {models.map((m) => (
            <Link
              key={m.family}
              to={`/collections/model/${m.family}`}
              className="card p-4 hover:border-mute/50 transition-colors duration-fast"
            >
              <div className="flex items-center gap-2">
                <h2 className="font-display font-medium text-[15px]">{m.label}</h2>
                {m.is_new && (
                  <span className="chip !text-[10.5px] !text-ember border-ember/50 bg-ember/10 font-semibold">
                    NEW
                  </span>
                )}
                <span className="chip ml-auto tabular-nums">
                  {m.post_count} post{m.post_count === 1 ? '' : 's'}
                </span>
              </div>
              <p className="text-[12px] text-faint mt-1 tabular-nums">
                {m.image_count} images · {m.video_count} videos · first seen {timeAgo(m.first_seen)} · last{' '}
                {timeAgo(m.last_seen)}
              </p>
              {m.versions.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {m.versions.slice(0, 4).map((v) => (
                    <span key={v} className="chip !text-[11px]">
                      {v}
                    </span>
                  ))}
                  {m.versions.length > 4 && (
                    <span className="chip !text-[11px]">+{m.versions.length - 4}</span>
                  )}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
