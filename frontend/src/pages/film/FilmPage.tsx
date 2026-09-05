// Film Studio section (S4): Projects · Assets · Story · Director ·
// Storyboard · Timeline. One current project (remembered per browser)
// flows through every tab; Assets are global.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { EmptyState, Spinner } from '../../components/Primitives'
import { errorMessage, film, FilmSchema, loadProjectId, Presets, Project, saveProjectId } from '../../lib/film'
import { toastError } from '../../lib/toast'
import { AssetsPage } from './AssetsPage'
import { DirectorPage } from './DirectorPage'
import { ProjectsPage } from './ProjectsPage'
import { StoryboardPage } from './StoryboardPage'
import { StoryPage } from './StoryPage'
import { TimelinePage } from './TimelinePage'

export interface FilmCtx {
  project: Project | null
  projects: Project[]
  setProjectId: (id: number | null) => void
  reloadProject: () => Promise<Project | null>
  reloadProjects: () => Promise<void>
  schema: FilmSchema | null
  presets: Presets | null
  reloadPresets: () => Promise<void>
}
const Ctx = createContext<FilmCtx | null>(null)
export const useFilm = () => {
  const c = useContext(Ctx)
  if (!c) throw new Error('useFilm outside FilmPage')
  return c
}

const TABS = [
  { to: '', label: 'Projects', end: true },
  { to: 'assets', label: 'Assets' },
  { to: 'story', label: 'Story' },
  { to: 'director', label: 'Director' },
  { to: 'storyboard', label: 'Storyboard' },
  { to: 'timeline', label: 'Timeline' },
]

export function FilmPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectIdState] = useState<number | null>(loadProjectId())
  const [project, setProject] = useState<Project | null>(null)
  const [schema, setSchema] = useState<FilmSchema | null>(null)
  const [presets, setPresets] = useState<Presets | null>(null)
  const [ready, setReady] = useState(false)

  const reloadProjects = useCallback(async () => {
    try {
      const r = await film.listProjects()
      setProjects(r.projects)
    } catch (e) {
      toastError(errorMessage(e))
    }
  }, [])
  const reloadProject = useCallback(async () => {
    if (projectId == null) {
      setProject(null)
      return null
    }
    try {
      const p = await film.getProject(projectId)
      setProject(p)
      return p
    } catch {
      setProject(null)
      setProjectIdState(null)
      saveProjectId(null)
      return null
    }
  }, [projectId])
  const reloadPresets = useCallback(async () => {
    try {
      setPresets(await film.presets())
    } catch (e) {
      toastError(errorMessage(e))
    }
  }, [])
  useEffect(() => {
    Promise.all([film.schema().then(setSchema), reloadPresets(), reloadProjects()]).catch((e) => toastError(errorMessage(e))).finally(() => setReady(true))
  }, [reloadPresets, reloadProjects])
  useEffect(() => {
    reloadProject()
  }, [reloadProject])

  const setProjectId = (id: number | null) => {
    setProjectIdState(id)
    saveProjectId(id)
  }
  const value = useMemo<FilmCtx>(() => ({ project, projects, setProjectId, reloadProject, reloadProjects, schema, presets, reloadPresets }), [project, projects, reloadProject, reloadProjects, schema, presets, reloadPresets])

  return (
    <Ctx.Provider value={value}>
      <div className="fade-in space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="font-display font-medium text-[19px]">Film Studio</h1>
          <ProjectSwitcher />
          <nav className="flex items-center gap-0.5 overflow-x-auto scrollbar-none ml-auto" aria-label="Film sections">
            {TABS.map((t) => (
              <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => `px-2.5 py-1.5 rounded-el text-[13px] whitespace-nowrap ${isActive ? 'bg-well text-fg font-medium' : 'text-mute hover:text-fg'}`}>
                {t.label}
              </NavLink>
            ))}
          </nav>
        </div>
        {!ready ? (
          <div className="py-20 flex justify-center"><Spinner className="w-6 h-6" /></div>
        ) : (
          <Routes>
            <Route index element={<ProjectsPage />} />
            <Route path="assets/*" element={<AssetsPage />} />
            <Route path="story" element={<NeedsProject><StoryPage /></NeedsProject>} />
            <Route path="director" element={<NeedsProject><DirectorPage /></NeedsProject>} />
            <Route path="storyboard" element={<NeedsProject><StoryboardPage /></NeedsProject>} />
            <Route path="timeline" element={<NeedsProject><TimelinePage /></NeedsProject>} />
          </Routes>
        )}
      </div>
    </Ctx.Provider>
  )
}

function ProjectSwitcher() {
  const { project, projects, setProjectId } = useFilm()
  return (
    <select className="input !w-auto !h-8 text-[12.5px] max-w-[240px]" value={project?.id ?? ''} onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)} aria-label="Current project">
      <option value="">— no project —</option>
      {projects.map((p) => (
        <option key={p.id} value={p.id}>{p.title}</option>
      ))}
    </select>
  )
}

function NeedsProject({ children }: { children: JSX.Element }) {
  const { project } = useFilm()
  const navigate = useNavigate()
  if (!project) {
    return <EmptyState icon="🎬" title="Pick or create a project" hint="Every story, storyboard and timeline belongs to a project." action={<button className="btn-accent" onClick={() => navigate('/film')}>Go to projects</button>} />
  }
  return children
}
