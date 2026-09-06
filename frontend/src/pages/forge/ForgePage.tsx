// Forge (spec §14): IDEA → FORGE → CHOOSE → GENERATE → COMPARE → REFINE.
// One section, six tabs — Compose is the flagship flow; Models is the
// intelligence registry; Lab, Plans, Workflows and Usage complete the loop.
import { NavLink, Route, Routes } from 'react-router-dom'
import { CatalogPage } from './CatalogPage'
import { ComposePage } from './ComposePage'
import { LabPage } from './LabPage'
import { PlansPage } from './PlansPage'
import { UsagePage } from './UsagePage'
import { WorkflowsPage } from './WorkflowsPage'

const TABS = [
  { to: '', label: 'Compose', end: true },
  { to: 'models', label: 'Models' },
  { to: 'lab', label: 'Lab' },
  { to: 'plans', label: 'Plans' },
  { to: 'workflows', label: 'Workflows' },
  { to: 'usage', label: 'Usage' },
]

export function ForgePage() {
  return (
    <div className="space-y-4 fade-in">
      <div className="flex items-end gap-4 flex-wrap">
        <div>
          <h1 className="font-display font-medium text-[19px]">Forge</h1>
          <p className="text-[12.5px] text-faint">
            Idea → model-aware prompt → the right model, explained → generate, compare, refine.
          </p>
        </div>
        <nav className="flex items-center gap-0.5 ml-auto overflow-x-auto scrollbar-none" aria-label="Forge sections">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                `px-2.5 py-1.5 text-[13px] rounded-el whitespace-nowrap ${isActive ? 'bg-well text-fg font-medium' : 'text-mute hover:text-fg'}`
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <Routes>
        <Route path="/" element={<ComposePage />} />
        <Route path="/models" element={<CatalogPage />} />
        <Route path="/lab/*" element={<LabPage />} />
        <Route path="/plans/*" element={<PlansPage />} />
        <Route path="/workflows/*" element={<WorkflowsPage />} />
        <Route path="/usage" element={<UsagePage />} />
      </Routes>
    </div>
  )
}
