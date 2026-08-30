import { Route, Routes } from 'react-router-dom'
import { Shell } from './components/Shell'
import { CollectionsPage } from './pages/CollectionsPage'
import { GalleryPage } from './pages/GalleryPage'
import { ModelsPage } from './pages/ModelsPage'
import { ScrapersPage } from './pages/ScrapersPage'
import { SettingsPage } from './pages/SettingsPage'
import { StudioPage } from './pages/StudioPage'

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<GalleryPage />} />
        <Route path="/collections" element={<CollectionsPage />} />
        <Route path="/collections/:id" element={<CollectionsPage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/studio/*" element={<StudioPage />} />
        <Route path="/scrapers" element={<ScrapersPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </Shell>
  )
}
