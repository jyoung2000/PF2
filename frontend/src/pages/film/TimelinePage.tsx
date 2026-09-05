// Timeline (spec §23, L, N, O, T–V): proportional timeline with drag
// durations and scene gaps, sequence preview, audio tracks + mixer,
// subtitles, QA report → repair queue, export with post-render review.
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { TimingPanel } from '../../components/film/TimingPanel'
import { Spinner } from '../../components/Primitives'
import { timeAgo } from '../../lib/format'
import { AudioTrack, errorMessage, film, fmtTc, fmtUsd, Job, Shot, Subtitles, Timeline } from '../../lib/film'
import { useFetch } from '../../lib/hooks'
import { toastError, toastSuccess } from '../../lib/toast'
import { JobRow } from './DirectorPage'
import { useFilm } from './FilmPage'

export function TimelinePage() {
  const { project, reloadProject } = useFilm()
  const [tl, setTl] = useState<Timeline | null>(null)
  const [view, setView] = useState<'scene' | 'shot' | 'timeline'>('timeline')
  const [selected, setSelected] = useState<number | null>(null)
  const [tab, setTab] = useState<'preview' | 'audio' | 'subtitles' | 'qa' | 'export'>('preview')
  const navigate = useNavigate()
  const load = () => project && film.timeline(project.id).then(setTl).catch((e) => toastError(errorMessage(e)))
  useEffect(() => {
    load()
  }, [project?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!project) return null
  const wrap = (fn: () => Promise<Timeline>) => fn().then((t) => { setTl(t); reloadProject() }).catch((e) => toastError(errorMessage(e)))
  return (
    <div className="space-y-3" data-testid="timeline-page">
      {tl ? (
        <div className="card p-3.5">
          <TimingPanel
            tl={tl}
            view={view}
            onView={setView}
            onDefaultGap={(g, reset) => wrap(() => film.setGap(project.id, { default_gap_s: g, reset_overrides: reset }))}
            onApplyAll={(g) => wrap(() => film.setGap(project.id, { apply_to_all: g }))}
            onSceneGap={(sid, g) => wrap(() => film.setSceneGap(sid, g))}
            onShotDuration={(id, s) => film.patchShot(id, { duration_s: s }).then(load).then(() => reloadProject()).catch((e) => toastError(errorMessage(e)))}
            onSelectShot={setSelected}
            selectedShotId={selected}
            onDefaultTransition={(kind) => film.patchProject(project.id, { settings: { default_transition: { kind, duration_s: kind === 'cut' ? 0 : 0.5 } } }).then(load).catch((e) => toastError(errorMessage(e)))}
          />
          {selected && <div className="mt-2 text-[12px] text-faint">Selected shot #{selected} — <button className="underline" onClick={() => navigate('/film/storyboard', { state: { shotId: selected } })}>open in storyboard</button></div>}
        </div>
      ) : <Spinner />}
      <div className="flex gap-1 flex-wrap">
        {(['preview', 'audio', 'subtitles', 'qa', 'export'] as const).map((t) => (
          <button key={t} className={`px-2.5 py-1.5 rounded-el text-[13px] ${tab === t ? 'bg-well text-fg font-medium' : 'text-mute hover:text-fg'}`} onClick={() => setTab(t)} data-timeline-tab={t}>{t === 'qa' ? 'QA & repair' : t[0].toUpperCase() + t.slice(1)}</button>
        ))}
      </div>
      {tab === 'preview' && tl && <SequencePreview project={project} tl={tl} />}
      {tab === 'audio' && <AudioPanel projectId={project.id} tl={tl} />}
      {tab === 'subtitles' && <SubtitlesPanel projectId={project.id} />}
      {tab === 'qa' && <QaPanel projectId={project.id} />}
      {tab === 'export' && <ExportPanel projectId={project.id} />}
    </div>
  )
}

// --------------------------------------------------------------- preview --
function SequencePreview({ project, tl }: { project: { id: number; scenes?: { shots: Shot[] }[] }; tl: Timeline }) {
  const shots = useMemo(() => (project.scenes ?? []).flatMap((sc) => sc.shots), [project])
  const playable = shots.filter((sh) => sh.selected_take?.media_url)
  const [i, setI] = useState(0)
  const [playing, setPlaying] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const cur = playable[i]
  useEffect(() => {
    if (playing && videoRef.current) videoRef.current.play().catch(() => undefined)
  }, [i, playing])
  if (!playable.length) return <p className="card p-4 text-[12.5px] text-faint">No shot has media yet — generate or import takes in the Storyboard to preview the cut.</p>
  const isImage = cur.selected_take?.kind === 'image' || /\.(png|jpe?g|webp)$/i.test(cur.selected_take?.media_url ?? '')
  return (
    <div className="card p-3 grid lg:grid-cols-[2fr_1fr] gap-3" data-testid="sequence-preview">
      <div>
        <div className="aspect-video bg-ink rounded-el overflow-hidden flex items-center justify-center">
          {isImage ? <img src={cur.selected_take!.media_url!} alt="" className="max-h-full" /> : (
            <video ref={videoRef} key={cur.id} src={cur.selected_take!.media_url!} className="w-full h-full" controls={!playing} onEnded={() => (i < playable.length - 1 ? setI(i + 1) : setPlaying(false))} />
          )}
        </div>
        <div className="flex items-center gap-2 mt-2 text-[12.5px]">
          <button className="btn" onClick={() => { setI(0); setPlaying(true) }}>▶ Play sequence</button>
          <button className="btn-ghost" onClick={() => setPlaying(false)}>stop</button>
          <span className="text-faint">shot {cur.label} · {cur.duration_s}s · {playable.length}/{shots.length} shots have media · runtime {tl.runtime_tc}</span>
        </div>
      </div>
      <div className="flex flex-wrap gap-1 content-start">
        {playable.map((sh, k) => (
          <button key={sh.id} className={`w-20 rounded-el overflow-hidden border ${k === i ? 'border-ember' : 'border-line'}`} onClick={() => { setI(k); setPlaying(false) }}>
            {sh.thumb_url ? <img src={sh.thumb_url} alt="" className="w-full aspect-video object-cover" /> : <div className="aspect-video bg-well" />}
            <div className="text-[10px] text-faint px-1">{sh.label}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

// ----------------------------------------------------------------- audio --
function AudioPanel({ projectId, tl }: { projectId: number; tl: Timeline | null }) {
  const data = useFetch(() => film.audio(projectId), [projectId])
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [kind, setKind] = useState('music')
  const [anchor, setAnchor] = useState<{ kind: string; id: string }>({ kind: 'timeline', id: '' })
  const [busy, setBusy] = useState(false)
  const shots = tl?.scenes.flatMap((sc) => sc.shots) ?? []
  const upload = async (f: File) => {
    setBusy(true)
    try {
      await film.addAudio(projectId, f, { kind, anchor_kind: anchor.kind, anchor_id: anchor.id ? Number(anchor.id) : undefined })
      toastSuccess('Track added')
      data.reload()
    } catch (e) {
      toastError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const patch = (t: AudioTrack, body: Partial<AudioTrack>) => film.patchAudio(t.id, body).then(() => data.reload()).catch((e) => toastError(errorMessage(e)))
  if (!data.data) return <Spinner />
  const caps = data.data.capabilities
  return (
    <div className="space-y-3" data-testid="audio-panel">
      <div className="card p-3 flex flex-wrap items-center gap-2 text-[12.5px]">
        <select className="input !w-32 !h-8" value={kind} onChange={(e) => setKind(e.target.value)}>{data.data.kinds.map((k) => <option key={k}>{k}</option>)}</select>
        <select className="input !w-32 !h-8" value={anchor.kind} onChange={(e) => setAnchor({ kind: e.target.value, id: '' })}><option value="timeline">at timeline start</option><option value="shot">anchored to shot</option><option value="scene">anchored to scene</option></select>
        {anchor.kind === 'shot' && <select className="input !w-40 !h-8" value={anchor.id} onChange={(e) => setAnchor({ ...anchor, id: e.target.value })}><option value="">shot…</option>{shots.map((s) => <option key={s.id} value={s.id}>{s.label} {s.title ?? ''}</option>)}</select>}
        {anchor.kind === 'scene' && <select className="input !w-40 !h-8" value={anchor.id} onChange={(e) => setAnchor({ ...anchor, id: e.target.value })}><option value="">scene…</option>{tl?.scenes.map((s) => <option key={s.id} value={s.id}>{s.number}. {s.title}</option>)}</select>}
        <button className="btn" onClick={() => fileRef.current?.click()} disabled={busy || ((anchor.kind !== 'timeline') && !anchor.id)}>{busy ? <Spinner /> : 'Upload audio'}</button>
        <input ref={fileRef} type="file" accept="audio/*,video/mp4" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <span className="text-faint ml-auto">{data.data.mix.tracks.length} audible track(s) · mixed at export</span>
      </div>
      {data.data.tracks.length === 0 ? <p className="text-[12.5px] text-faint">No audio tracks. Dialogue, narration, music, ambience and SFX all live here; clip audio from footage is mixed automatically.</p> : (
        <div className="space-y-1.5">
          {data.data.tracks.map((t) => (
            <div key={t.id} className={`card p-2.5 flex flex-wrap items-center gap-2 text-[12.5px] ${t.muted ? 'opacity-60' : ''}`} data-track-id={t.id}>
              <span className="chip !text-[10px]">{t.kind}</span>
              <input className="input !h-7 !w-40 text-[12px]" defaultValue={t.label ?? ''} onBlur={(e) => e.target.value !== (t.label ?? '') && patch(t, { label: e.target.value })} />
              <span className="text-faint tabular-nums">{t.orphaned ? 'anchor missing' : `${fmtTc(t.start_s)} → ${fmtTc(t.end_s)}`} · {t.anchor_kind}{t.anchor_id ? ` #${t.anchor_id}` : ''}</span>
              <label className="flex items-center gap-1 text-faint">gain<input type="range" min="-30" max="12" step="1" defaultValue={t.gain_db} onMouseUp={(e) => patch(t, { gain_db: Number((e.target as HTMLInputElement).value) })} onTouchEnd={(e) => patch(t, { gain_db: Number((e.target as HTMLInputElement).value) })} /><span className="tabular-nums w-10">{t.gain_db} dB</span></label>
              <label className="flex items-center gap-1 text-faint">offset<input className="input !h-7 !w-16 text-[12px]" type="number" step="0.1" defaultValue={t.offset_s} onBlur={(e) => Number(e.target.value) !== t.offset_s && patch(t, { offset_s: Number(e.target.value) })} />s</label>
              <label className="flex items-center gap-1 text-faint"><input type="checkbox" checked={t.muted} onChange={(e) => patch(t, { muted: e.target.checked })} />mute</label>
              <label className="flex items-center gap-1 text-faint"><input type="checkbox" checked={t.loop} onChange={(e) => patch(t, { loop: e.target.checked })} />loop</label>
              {t.url && <audio src={t.url} controls className="h-7 max-w-[200px]" />}
              <button className="btn-ghost text-[11px] text-red-300 ml-auto" onClick={() => window.confirm('Remove track?') && film.deleteAudio(t.id).then(() => data.reload())}>remove</button>
            </div>
          ))}
        </div>
      )}
      <details className="text-[12px]"><summary className="text-faint cursor-pointer">Generate audio (TTS · music · SFX · enhancement)</summary>
        <ul className="mt-1 space-y-0.5">{Object.entries(caps).map(([k, v]) => <li key={k} className="text-faint">{k.replace(/_/g, ' ')}: {v.supported ? 'available' : v.reason}</li>)}</ul>
      </details>
    </div>
  )
}

// ------------------------------------------------------------- subtitles --
function SubtitlesPanel({ projectId }: { projectId: number }) {
  const data = useFetch(() => film.subtitles(projectId), [projectId])
  const [importText, setImportText] = useState('')
  const [cues, setCues] = useState<Subtitles['cues']>([])
  useEffect(() => setCues(data.data?.cues ?? []), [data.data])
  const wrap = (fn: () => Promise<Subtitles>, ok?: string) => fn().then((s) => { data.setData(s); if (ok) toastSuccess(ok) }).catch((e) => toastError(errorMessage(e)))
  if (!data.data) return <Spinner />
  const s = data.data
  const dirty = JSON.stringify(cues) !== JSON.stringify(s.cues)
  return (
    <div className="space-y-3" data-testid="subtitles-panel">
      <div className="card p-3 flex flex-wrap items-center gap-2 text-[12.5px]">
        <button className="btn" onClick={() => wrap(() => film.subtitlesFromScript(projectId), 'Captions generated from the script dialogue')}>From script dialogue</button>
        <button className="btn" onClick={() => wrap(() => film.subtitlesResync(projectId), 'Cues re-synced to shot timing')}>Re-sync to timing</button>
        <label className="flex items-center gap-1.5 ml-2"><input type="checkbox" checked={s.burn_in} onChange={(e) => wrap(() => film.putSubtitles(projectId, { burn_in: e.target.checked }))} /> burn in at export</label>
        <label className="flex items-center gap-1.5">size<input className="input !h-7 !w-16" type="number" min="12" max="72" defaultValue={s.style.font_size} onBlur={(e) => wrap(() => film.putSubtitles(projectId, { style: { ...s.style, font_size: Number(e.target.value) } }))} /></label>
        <label className="flex items-center gap-1.5">colour<input type="color" defaultValue={s.style.color} onBlur={(e) => wrap(() => film.putSubtitles(projectId, { style: { ...s.style, color: e.target.value } }))} /></label>
        <span className={`ml-auto ${s.validation?.status === 'PASS' ? 'text-emerald-300' : s.validation?.status === 'FAIL' ? 'text-red-300' : 'text-amber-300'}`}>{s.validation?.status}: {s.validation?.message}</span>
        <a className="btn-ghost text-[12px]" href={`/api/film/projects/${projectId}/subtitles.srt`} target="_blank" rel="noreferrer">.srt</a>
        <a className="btn-ghost text-[12px]" href={`/api/film/projects/${projectId}/subtitles.vtt`} target="_blank" rel="noreferrer">.vtt</a>
      </div>
      <div className="card p-3 space-y-1.5">
        {cues.length === 0 && <p className="text-[12.5px] text-faint">No cues yet.</p>}
        {cues.map((c, i) => (
          <div key={c.id ?? i} className="grid grid-cols-[80px_80px_1fr_28px] gap-1.5 items-center text-[12.5px]">
            <input className="input !h-7 tabular-nums" type="number" step="0.1" value={c.start_s} onChange={(e) => setCues(cues.map((x, j) => (j === i ? { ...x, start_s: Number(e.target.value) } : x)))} aria-label="start" />
            <input className="input !h-7 tabular-nums" type="number" step="0.1" value={c.end_s} onChange={(e) => setCues(cues.map((x, j) => (j === i ? { ...x, end_s: Number(e.target.value) } : x)))} aria-label="end" />
            <input className="input !h-7" value={c.text} onChange={(e) => setCues(cues.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} aria-label="text" />
            <button className="btn-ghost text-red-300 px-1" onClick={() => setCues(cues.filter((_, j) => j !== i))} aria-label="remove cue">✕</button>
          </div>
        ))}
        <div className="flex gap-2">
          <button className="btn text-[12px]" onClick={() => setCues([...cues, { id: cues.length + 1, start_s: cues.length ? cues[cues.length - 1].end_s : 0, end_s: (cues.length ? cues[cues.length - 1].end_s : 0) + 2, text: '' }])}>+ cue</button>
          <button className="btn-accent text-[12px]" disabled={!dirty} onClick={() => wrap(() => film.putSubtitles(projectId, { cues }), 'Subtitles saved')}>Save cues</button>
        </div>
      </div>
      <details className="card p-3 text-[12.5px]"><summary className="cursor-pointer text-mute">Import SRT / WebVTT</summary>
        <textarea className="input font-mono text-[11.5px] min-h-[100px] mt-2" value={importText} onChange={(e) => setImportText(e.target.value)} placeholder={'1\n00:00:00,200 --> 00:00:01,500\nHello'} />
        <button className="btn mt-2" disabled={!importText.trim()} onClick={() => wrap(() => film.subtitlesImport(projectId, importText), 'Imported').then(() => setImportText(''))}>Import</button>
      </details>
    </div>
  )
}

// ------------------------------------------------------------------- QA ---
function QaPanel({ projectId }: { projectId: number }) {
  const [report, setReport] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const run = () => {
    setBusy(true)
    film.qa(projectId).then(setReport).catch((e) => toastError(errorMessage(e))).finally(() => setBusy(false))
  }
  useEffect(run, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps
  const color = (v: string) => (v === 'PASS' ? 'text-emerald-300' : v === 'FAIL' ? 'text-red-300' : 'text-amber-300')
  return (
    <div className="space-y-3" data-testid="qa-panel">
      <div className="flex items-center gap-2"><button className="btn" onClick={run} disabled={busy}>{busy ? <Spinner /> : 'Run pre-render QA'}</button>{report && <span className={`font-display text-[16px] ${color(report.verdict)}`}>{report.verdict}</span>}<span className="text-[11.5px] text-faint">technical (ffprobe), visual heuristics (black / frozen frames), continuity, subtitles, completeness</span></div>
      {report && (
        <div className="grid lg:grid-cols-2 gap-3">
          <div className="card p-3 space-y-1 text-[12.5px]">
            {report.checks.map((c: any) => <div key={c.key} className="flex gap-2"><span className={`w-12 shrink-0 ${color(c.status)}`}>{c.status}</span><span>{c.message}{c.heuristic && <span className="text-faint"> (heuristic)</span>}</span></div>)}
          </div>
          <div className="card p-3 space-y-1.5 text-[12.5px]">
            <h4 className="font-display">Repair queue <span className="text-faint">({report.repairs?.length ?? 0})</span></h4>
            {(report.repairs ?? []).length === 0 && <p className="text-faint">Nothing to repair.</p>}
            {(report.repairs ?? []).map((r: any, i: number) => (
              <div key={i} className="flex items-center gap-2">
                <span className={color(r.severity)}>{r.severity}</span>
                <span className="font-medium">{r.label}</span>
                <span className="text-faint truncate flex-1" title={r.reason}>{r.reason}</span>
                {r.kind === 'regenerate_shot' && <button className="btn text-[11.5px] py-0.5" onClick={() => navigate('/film/storyboard', { state: { shotId: r.entity_id } })}>Fix shot</button>}
                {r.kind === 'fix_subtitles' && <span className="chip !text-[10px]">Subtitles tab</span>}
                {r.kind === 'continuity' && <button className="btn text-[11.5px] py-0.5" onClick={() => navigate('/film/storyboard')}>Continuity</button>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------- export ---
function ExportPanel({ projectId }: { projectId: number }) {
  const data = useFetch(() => film.exports(projectId), [projectId])
  const [label, setLabel] = useState('')
  const [quality, setQuality] = useState('1080p')
  const [burn, setBurn] = useState<boolean | null>(null)
  const [audio, setAudio] = useState(true)
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState<string | null>(null)
  const active = (data.data?.exports ?? []).some((j) => ['queued', 'running'].includes(j.status))
  useEffect(() => {
    if (!active) return
    const t = window.setInterval(() => data.reload(), 3000)
    return () => window.clearInterval(t)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps
  const start = async (force = false) => {
    setBusy(true)
    setBlocked(null)
    try {
      await film.startExport(projectId, { label: label || undefined, quality, burn_in: burn ?? undefined, include_audio: audio, force })
      toastSuccess('Export started')
      data.reload()
    } catch (e) {
      setBlocked(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const plan = data.data?.plan
  return (
    <div className="space-y-3" data-testid="export-panel">
      <div className="card p-3 flex flex-wrap items-center gap-2 text-[12.5px]">
        <input className="input !w-44 !h-8" placeholder="label (v1, festival-cut…)" value={label} onChange={(e) => setLabel(e.target.value)} />
        <select className="input !w-24 !h-8" value={quality} onChange={(e) => setQuality(e.target.value)}><option value="1080p">1080p</option><option value="720p">720p</option></select>
        <label className="flex items-center gap-1"><input type="checkbox" checked={burn ?? false} onChange={(e) => setBurn(e.target.checked)} /> burn in subtitles</label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={audio} onChange={(e) => setAudio(e.target.checked)} /> include audio</label>
        <button className="btn-accent" onClick={() => start(false)} disabled={busy || active}>{busy ? <Spinner /> : 'Export master'}</button>
        {plan && <span className="text-faint ml-auto">{plan.segments.filter((s: any) => s.type === 'clip').length} clips · {plan.segments.filter((s: any) => s.type === 'gap').length} gaps · {fmtTc(plan.runtime_s)} · {plan.fps} fps · {plan.aspect_ratio}</span>}
      </div>
      {blocked && <div className="card !bg-well p-2.5 text-[12.5px] text-amber-300">{blocked} <button className="underline ml-2" onClick={() => start(true)}>Export anyway (missing shots render black)</button></div>}
      {(data.data?.exports ?? []).map((j) => <ExportRow key={j.id} j={j} onChanged={data.reload} />)}
      {data.data && data.data.exports.length === 0 && <p className="text-[12.5px] text-faint">No exports yet. The export conforms every selected take, honours gaps, dissolves and fades exactly as the timeline shows, mixes audio, writes SRT/VTT and a sources file, then reviews the render.</p>}
    </div>
  )
}

function ExportRow({ j, onChanged }: { j: Job; onChanged: () => void }) {
  const r = j.result
  const color = (v: string) => (v === 'PASS' ? 'text-emerald-300' : v === 'FAIL' ? 'text-red-300' : 'text-amber-300')
  return (
    <div className="card p-3 space-y-2" data-export-id={j.id}>
      <JobRow j={j} onChanged={onChanged} />
      {r && j.status === 'done' && (
        <div className="grid lg:grid-cols-[2fr_1fr] gap-3 text-[12.5px]">
          <div>
            <video src={r.url} controls className="w-full rounded-el bg-ink" />
            <div className="flex flex-wrap gap-2 mt-1.5">
              <a className="btn text-[12px]" href={r.url} download>Download master</a>
              {r.srt_url && <a className="btn-ghost text-[12px]" href={r.srt_url} download>.srt</a>}
              {r.vtt_url && <a className="btn-ghost text-[12px]" href={r.vtt_url} download>.vtt</a>}
              {r.sources_url && <a className="btn-ghost text-[12px]" href={r.sources_url} download>project sources (json)</a>}
              <span className="text-faint self-center">{r.width}×{r.height} · {fmtTc(r.runtime_s)} · {r.fps} fps · {r.tracks} audio track(s){r.burn_in ? ' · burned-in subtitles' : ''} · {timeAgo(j.finished_at)}</span>
            </div>
          </div>
          <div>
            <div className={`font-display text-[15px] ${color(r.review?.verdict)}`}>Post-render review: {r.review?.verdict}</div>
            <ul className="space-y-0.5 mt-1">{(r.review?.checks ?? []).map((c: any) => <li key={c.key} className="flex gap-2"><span className={`w-12 shrink-0 ${color(c.status)}`}>{c.status}</span><span>{c.message}</span></li>)}</ul>
            {r.samples?.length > 0 && <div className="flex gap-1 mt-2">{r.samples.map((s: string) => <img key={s} src={s} alt="" className="h-14 rounded-el border border-line" />)}</div>}
          </div>
        </div>
      )}
    </div>
  )
}

export const fmtCost = fmtUsd
