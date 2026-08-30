import { Link } from 'react-router-dom'
import { GeneratePanel } from '../components/GeneratePanel'
import { PostGallery } from '../components/PostGallery'

export function GalleryPage() {
  return (
    <PostGallery
      extraDrawerActions={(p) =>
        p.prompt ? (
          <GeneratePanel
            prompt={p.prompt}
            negative={p.negative_prompt}
            modelFamily={p.model_family}
            buttonLabel="⟳ Recreate"
          />
        ) : null
      }
      emptyTitle="No posts yet"
      emptyHint="Enable a scraper and hit “Run now” — fresh prompts and media will start landing here."
      emptyAction={
        <Link to="/scrapers" className="btn-accent">
          Open scrapers
        </Link>
      }
    />
  )
}
