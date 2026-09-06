import { Navigate, Route, Routes } from 'react-router-dom'
import { Shell } from './components/Shell'
import {
  CollectionDetailPage,
  CollectionsPage,
  ModelCollectionPage,
} from './pages/CollectionsPage'
import { FilmPage } from './pages/film/FilmPage'
import { ForgePage } from './pages/forge/ForgePage'
import { GalleryPage } from './pages/GalleryPage'
import { InspirationPage } from './pages/InspirationPage'
import { ModelsPage } from './pages/ModelsPage'
import { SettingsPage } from './pages/SettingsPage'
import { StudioPage } from './pages/StudioPage'

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<GalleryPage />} />
        <Route path="/collections" element={<CollectionsPage />} />
        <Route path="/collections/model/:family" element={<ModelCollectionPage />} />
        <Route path="/collections/:id" element={<CollectionDetailPage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/studio/*" element={<StudioPage />} />
        <Route path="/inspiration/*" element={<InspirationPage />} />
        <Route path="/film/*" element={<FilmPage />} />
        <Route path="/forge/*" element={<ForgePage />} />
        <Route path="/scrapers" element={<Navigate to="/inspiration/sources" replace />} />
        <Route path="/monitoring" element={<Navigate to="/inspiration/creators" replace />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </Shell>
  )
}
