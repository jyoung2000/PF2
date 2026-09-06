// Media bin (Editor E4): the project's shots/takes, footage corpus and
// audio tracks — the ONLY media sources (no separate library). "Add" drops
// the item at the playhead on the first matching unlocked track.
import { useState } from 'react'
import { AudioTrack, Clip, film, Project, Shot, Take } from '../../lib/film'
import { useFetch } from '../../lib/hooks'
import { Sequence } from '../../lib/editor'
import { Spinner } from '../Primitives'

export interface AddPayload {
  source_kind: 'take' | 'footage' | 'audio'
  take_id?: number
  footage_id?: number
  audio_track_id?: number
  shot_id?: number
  label?: string
  duration_s?: number
}

export function MediaBin({ project, seq, onAdd }: {
  project: Project
  seq: Sequence
  onAdd: (p: AddPayload) => void
}) {
  const [tab, setTab] = useState<'shots' | 'footage' | 'audio'>('shots')
  const shots: Shot[] = (project.scenes ?? []).flatMap((sc: any) => sc.shots ?? [])
  const usedTakes = new Set(seq.tracks.flatMap((t) => t.clips).map((c) => c.take_id).filter(Boolean))
  return (
    <div className="flex flex-col h-full" data-testid="media-bin">
      <div className="flex gap-1 mb-2">
        {(['shots', 'footage', 'audio'] as const).map((t) => (
          <button key={t} className={`chip ${tab === t ? '!border-ember text-fg' : ''}`} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      <div className="overflow-y-auto flex-1 space-y-1 pr-1">
        {tab === 'shots' && (shots.length === 0 ? <Empty text="No shots yet — build the storyboard first." /> : shots.map((sh) => (
          <ShotRow key={sh.id} shot={sh} used={usedTakes} onAdd={onAdd} />
        )))}
        {tab === 'footage' && <FootageList projectId={project.id} onAdd={onAdd} />}
        {tab === 'audio' && <AudioList projectId={project.id} onAdd={onAdd} />}
      </div>
    </div>
  )
}

const Empty = ({ text }: { text: string }) => <p className="text-[11.5px] text-faint">{text}</p>

function ShotRow({ shot, used, onAdd }: { shot: Shot; used: Set<number | null>; onAdd: (p: AddPayload) => void }) {
  const [open, setOpen] = useState(false)
  const [takes, setTakes] = useState<Take[] | null>(null)
  const t = shot.selected_take
  const load = () => {
    if (!open && takes === null) film.takes(shot.id).then((r) => setTakes(r.takes)).catch(() => setTakes([]))
    setOpen(!open)
  }
  return (
    <div className="card !p-1.5 text-[11.5px]" data-testid={`bin-shot-${shot.id}`}>
      <div className="flex items-center gap-1.5">
        {t?.thumb_url ? <img src={t.thumb_url} alt="" className="w-12 aspect-video object-cover rounded" /> : <div className="w-12 aspect-video bg-well rounded" />}
        <div className="flex-1 min-w-0">
          <div className="truncate">{shot.label} {shot.title ?? ''}</div>
          <div className="text-faint">{shot.duration_s}s{t ? ` · take ${t.number}` : ' · no media'}{t && used.has(t.id) ? ' · in timeline' : ''}</div>
        </div>
        {t && <button className="btn !px-2 !py-0.5 text-[11px]" title="Add selected take at the playhead" onClick={() => onAdd({ source_kind: 'take', take_id: t.id, shot_id: shot.id, label: `${shot.label} ${shot.title ?? ''}`.trim(), duration_s: t.duration_s ?? shot.duration_s })} data-testid={`bin-add-${shot.id}`}>+ Add</button>}
        <button className="btn-ghost !px-1 text-[11px]" onClick={load} aria-label={`Takes of ${shot.label}`}>{open ? '▾' : '▸'}</button>
      </div>
      {open && (
        <div className="mt-1 space-y-0.5 pl-2 border-l border-line">
          {takes === null && <Spinner />}
          {takes?.filter((x) => x.status === 'succeeded' || x.status === 'imported').map((x) => (
            <div key={x.id} className="flex items-center gap-1.5">
              {x.thumb_url ? <img src={x.thumb_url} alt="" className="w-9 aspect-video object-cover rounded" /> : <div className="w-9 aspect-video bg-well rounded" />}
              <span className="flex-1 text-faint">take {x.number} · {x.kind}{x.duration_s ? ` · ${x.duration_s.toFixed(1)}s` : ''}</span>
              <button className="btn-ghost !px-1.5 text-[10.5px]" onClick={() => onAdd({ source_kind: 'take', take_id: x.id, shot_id: shot.id, label: `${shot.label} t${x.number}`, duration_s: x.duration_s ?? shot.duration_s })}>+ Add</button>
            </div>
          ))}
          {takes?.length === 0 && <Empty text="No takes yet." />}
        </div>
      )}
    </div>
  )
}

function FootageList({ projectId, onAdd }: { projectId: number; onAdd: (p: AddPayload) => void }) {
  const data = useFetch(() => film.clips(undefined, projectId), [projectId])
  const clips: Clip[] = (data.data?.clips ?? data.data?.results ?? []) as Clip[]
  if (!data.data) return <Spinner />
  if (!clips.length) return <Empty text="No footage in this project — upload or search stock on the Storyboard's footage modal." />
  return (
    <>
      {clips.map((c) => (
        <div key={c.id} className="card !p-1.5 flex items-center gap-1.5 text-[11.5px]" data-testid={`bin-footage-${c.id}`}>
          {c.thumb_url ? <img src={c.thumb_url} alt="" className="w-12 aspect-video object-cover rounded" /> : <div className="w-12 aspect-video bg-well rounded" />}
          <div className="flex-1 min-w-0">
            <div className="truncate">{c.title ?? c.source}</div>
            <div className="text-faint">{c.media_type}{c.duration_s ? ` · ${c.duration_s.toFixed(1)}s` : ''} · {c.source}</div>
          </div>
          {c.file_url && <button className="btn !px-2 !py-0.5 text-[11px]" onClick={() => onAdd({ source_kind: 'footage', footage_id: c.id, label: c.title ?? c.source, duration_s: c.duration_s ?? undefined })}>+ Add</button>}
        </div>
      ))}
    </>
  )
}

function AudioList({ projectId, onAdd }: { projectId: number; onAdd: (p: AddPayload) => void }) {
  const data = useFetch(() => film.audio(projectId), [projectId])
  if (!data.data) return <Spinner />
  const tracks: AudioTrack[] = data.data.tracks
  if (!tracks.length) return <Empty text="No audio files — upload them on the Timeline page's Audio tab; they appear here to place as clips." />
  return (
    <>
      {tracks.map((t) => (
        <div key={t.id} className="card !p-1.5 flex items-center gap-1.5 text-[11.5px]" data-testid={`bin-audio-${t.id}`}>
          <span className="chip !text-[10px]">{t.kind}</span>
          <span className="flex-1 truncate">{t.label ?? t.kind}{t.duration_s ? ` · ${t.duration_s.toFixed(1)}s` : ''}</span>
          <button className="btn !px-2 !py-0.5 text-[11px]" onClick={() => onAdd({ source_kind: 'audio', audio_track_id: t.id, label: t.label ?? t.kind, duration_s: t.duration_s ?? undefined })}>+ Add</button>
        </div>
      ))}
    </>
  )
}
