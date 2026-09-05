// Story / Script workspace (spec §12): logline, synopsis, script with
// deterministic scene import (preview first), scene list with intent,
// summary, defaults, reorder, and the hand-off to the Director.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal, Spinner } from '../../components/Primitives'
import { errorMessage, film, Scene } from '../../lib/film'
import { toastError, toastSuccess } from '../../lib/toast'
import { useFilm } from './FilmPage'

export function StoryPage() {
  const { project, reloadProject } = useFilm()
  const navigate = useNavigate()
  const [script, setScript] = useState(project?.script ?? '')
  const [preview, setPreview] = useState<any[] | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => setScript(project?.script ?? ''), [project?.id, project?.script])
  if (!project) return null
  const scenes = project.scenes ?? []
  const savePatch = async (body: Parameters<typeof film.patchProject>[1]) => {
    try {
      await film.patchProject(project.id, body)
      await reloadProject()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const parse = async () => {
    if (!script.trim()) return toastError('Paste or type a script first.')
    setBusy(true)
    try {
      const r = await film.parseScript(script)
      setPreview(r.scenes)
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const doImport = async (mode: 'replace' | 'append') => {
    setBusy(true)
    try {
      const r = await film.importScript(project.id, script, mode)
      setPreview(null)
      await reloadProject()
      toastSuccess(`${r.scene_ids.length} scene(s) ${mode === 'replace' ? 'imported' : 'appended'}`)
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const addScene = async () => {
    try {
      await film.createScene(project.id, { title: `Scene ${scenes.length + 1}` })
      await reloadProject()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const move = async (sc: Scene, dir: -1 | 1) => {
    const ids = scenes.map((s) => s.id)
    const i = ids.indexOf(sc.id)
    const j = i + dir
    if (j < 0 || j >= ids.length) return
    ;[ids[i], ids[j]] = [ids[j], ids[i]]
    try {
      await film.reorderScenes(project.id, ids)
      await reloadProject()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  return (
    <div className="grid lg:grid-cols-[1fr_1fr] gap-3" data-testid="story-page">
      <section className="space-y-3">
        <div className="card p-3 space-y-2">
          <label className="label block">Logline<input className="input mt-1" defaultValue={project.logline ?? ''} placeholder="One sentence: who wants what, against what." onBlur={(e) => e.target.value !== (project.logline ?? '') && savePatch({ logline: e.target.value })} /></label>
          <label className="label block">Synopsis<textarea className="input mt-1 min-h-[90px]" defaultValue={project.synopsis ?? ''} placeholder="A paragraph or two. The Director can break this into scenes even without a script." onBlur={(e) => e.target.value !== (project.synopsis ?? '') && savePatch({ synopsis: e.target.value })} /></label>
        </div>
        <div className="card p-3 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="label">Script</span>
            <span className="text-[11px] text-faint">INT./EXT. sluglines, “Scene 1:” headings, or plain paragraphs — all parse.</span>
            <div className="ml-auto flex gap-1.5">
              <button className="btn text-[12px]" onClick={() => savePatch({ script })} disabled={script === (project.script ?? '')}>Save text</button>
              <button className="btn-accent text-[12px]" onClick={parse} disabled={busy}>{busy ? <Spinner /> : 'Import scenes…'}</button>
            </div>
          </div>
          <textarea className="input font-mono text-[12px] min-h-[380px]" value={script} onChange={(e) => setScript(e.target.value)} placeholder={'FADE IN:\n\nINT. WAREHOUSE - NIGHT\n\nRain hammers the skylights. JACK crouches by a crate.\n\nJACK\nWe don\'t have long.'} spellCheck={false} data-testid="script-editor" />
        </div>
      </section>
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <h2 className="font-display text-[15px]">Scenes <span className="text-faint text-[12px]">({scenes.length})</span></h2>
          <div className="ml-auto flex gap-1.5">
            <button className="btn text-[12px]" onClick={addScene}>+ Scene</button>
            <button className="btn-accent text-[12px]" onClick={() => navigate('/film/director')}>Direct story →</button>
          </div>
        </div>
        {scenes.length === 0 && <p className="text-[12.5px] text-faint card p-4">No scenes yet. Import a script on the left, add scenes by hand, or let the Director break the synopsis down.</p>}
        {scenes.map((sc, i) => (
          <SceneCard key={sc.id} sc={sc} first={i === 0} last={i === scenes.length - 1} onMove={(d) => move(sc, d)} onChanged={reloadProject} />
        ))}
      </section>
      {preview && (
        <Modal title={`Import ${preview.length} scene(s)?`} onClose={() => setPreview(null)} wide>
          <ol className="space-y-1.5 max-h-[50vh] overflow-y-auto text-[12.5px]">
            {preview.map((sc, i) => (
              <li key={i} className="card !bg-well p-2">
                <div className="flex items-center gap-2"><span className="font-display">{i + 1}. {sc.title}</span>{sc.time_of_day && <span className="chip !text-[10px]">{sc.time_of_day}</span>}{sc.weather && <span className="chip !text-[10px]">{sc.weather}</span>}{sc.characters?.length > 0 && <span className="text-faint">{sc.characters.join(', ')}</span>}</div>
                <p className="text-faint line-clamp-2 mt-0.5">{sc.text}</p>
              </li>
            ))}
          </ol>
          <div className="flex justify-end gap-2 mt-3">
            <button className="btn" onClick={() => setPreview(null)}>Cancel</button>
            {scenes.length > 0 && <button className="btn" onClick={() => doImport('append')} disabled={busy}>Append to existing</button>}
            <button className="btn-accent" onClick={() => doImport('replace')} disabled={busy}>{scenes.length > 0 ? 'Replace scenes' : 'Import'}</button>
          </div>
          {scenes.length > 0 && <p className="text-[11px] text-amber-300 mt-2">Replace removes the current scenes and their shots.</p>}
        </Modal>
      )}
    </div>
  )
}

function SceneCard({ sc, first, last, onMove, onChanged }: { sc: Scene; first: boolean; last: boolean; onMove: (d: -1 | 1) => void; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const patch = async (body: Parameters<typeof film.patchScene>[1]) => {
    try {
      await film.patchScene(sc.id, body)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const del = async () => {
    if (!window.confirm(`Delete scene “${sc.title}” and its ${sc.shots.length} shot(s)?`)) return
    try {
      await film.deleteScene(sc.id)
      onChanged()
    } catch (e) {
      toastError(errorMessage(e))
    }
  }
  const d = sc.defaults ?? {}
  return (
    <div className="card p-3 space-y-2" data-scene-id={sc.id}>
      <div className="flex items-center gap-2">
        <span className="font-mono text-[11px] text-faint w-6">{String(sc.number).padStart(2, '0')}</span>
        <input className="input !h-8 font-display flex-1" defaultValue={sc.title} onBlur={(e) => e.target.value.trim() && e.target.value !== sc.title && patch({ title: e.target.value })} aria-label="Scene title" />
        <span className="text-[11px] text-faint">{sc.shots.length} shot{sc.shots.length === 1 ? '' : 's'}</span>
        <button className="btn-ghost px-1" disabled={first} onClick={() => onMove(-1)} aria-label="Move up">↑</button>
        <button className="btn-ghost px-1" disabled={last} onClick={() => onMove(1)} aria-label="Move down">↓</button>
        <button className="btn-ghost text-[12px]" onClick={() => setOpen((v) => !v)}>{open ? 'less' : 'more'}</button>
      </div>
      <div className="flex flex-wrap gap-1 text-[11px]">
        {d.location_name && <span className="chip">📍 {d.location_name}</span>}
        {d.time_of_day && <span className="chip">{d.time_of_day}</span>}
        {d.weather && <span className="chip">{d.weather}</span>}
        {(d.characters ?? []).map((c: string) => <span key={c} className="chip">👤 {c}</span>)}
        {(d.assets ?? []).map((a: any) => <span key={a.asset_id} className="chip text-ember" title={`version ${a.version_id}`}>{a.name ?? a.asset_id}</span>)}
      </div>
      <input className="input !h-8 text-[12.5px]" defaultValue={sc.intent ?? ''} placeholder="Scene intent / goal (what must the audience feel or learn?)" onBlur={(e) => e.target.value !== (sc.intent ?? '') && patch({ intent: e.target.value })} />
      {open && (
        <div className="space-y-2 fade-in">
          <textarea className="input min-h-[60px] text-[12.5px]" defaultValue={sc.summary ?? ''} placeholder="Summary" onBlur={(e) => e.target.value !== (sc.summary ?? '') && patch({ summary: e.target.value })} />
          <textarea className="input font-mono min-h-[120px] text-[12px]" defaultValue={sc.script_text ?? ''} placeholder="Scene script" onBlur={(e) => e.target.value !== (sc.script_text ?? '') && patch({ script_text: e.target.value })} spellCheck={false} />
          <div className="grid sm:grid-cols-3 gap-2 text-[12px]">
            <label className="text-mute">Time of day<input className="input mt-1" defaultValue={d.time_of_day ?? ''} onBlur={(e) => patch({ defaults: { time_of_day: e.target.value } })} /></label>
            <label className="text-mute">Weather<input className="input mt-1" defaultValue={d.weather ?? ''} onBlur={(e) => patch({ defaults: { weather: e.target.value } })} /></label>
            <label className="text-mute">Mood<input className="input mt-1" defaultValue={d.mood ?? ''} onBlur={(e) => patch({ defaults: { mood: e.target.value } })} /></label>
          </div>
          <div className="flex gap-1.5 justify-end">
            <button className="btn text-[12px]" onClick={() => navigate('/film/storyboard', { state: { sceneId: sc.id } })}>Open in storyboard</button>
            <button className="btn-danger text-[12px]" onClick={del}>Delete scene</button>
          </div>
        </div>
      )}
    </div>
  )
}
