import { Link } from 'react-router-dom'
import { PostGallery } from '../components/PostGallery'

export function GalleryPage() {
  return (
    <PostGallery
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
