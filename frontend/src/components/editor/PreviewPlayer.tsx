// Central preview player (Editor E4/E5): plays the flattened sequence —
// the SAME resolution the export renders — via one <video>/<img> element
// per active segment plus <audio> elements for audible audio clips. The
// clock lives in the page (derived from performance.now, never
// accumulated); this component only syncs media to the given time.
import { useEffect, useMemo, useRef, useState } from 'react'
import { audioAt, captionsAt, effectsToCss, flattenVideo, fmtTcF, segmentAt, Sequence } from '../../lib/editor'

export function PreviewPlayer({ seq, playhead, playing, loop, onTogglePlay, onSeek, onToggleLoop, onStep }: {
  seq: Sequence
  playhead: number
  playing: boolean
  loop: boolean
  onTogglePlay: () => void
  onSeek: (t: number) => void
  onToggleLoop: () => void
  onStep: (frames: number) => void
}) {
  const segments = useMemo(() => flattenVideo(seq), [seq])
  const seg = segmentAt(segments, playhead)
  const [safe, setSafe] = useState(false)
  const [decodeError, setDecodeError] = useState<number | null>(null)   // clip_id that failed
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const isVideo = seg?.type === 'clip' && seg.media_url && seg.media_kind !== 'image'
  const isImage = seg?.type === 'clip' && seg.media_url && seg.media_kind === 'image'

  // sync the video element to the playhead
  useEffect(() => {
    const v = videoRef.current
    if (!v || !seg || seg.type !== 'clip' || !isVideo) return
    const want = (seg.trim_start_s ?? 0) + (playhead - seg.start_s) * (seg.speed ?? 1)
    // readyState < 2 ⇒ no frame decoded yet — a seek forces the first paint
    if (Math.abs(v.currentTime - want) > 0.18 || v.readyState < 2) v.currentTime = Math.max(0.001, want)
    v.playbackRate = seg.speed ?? 1
    v.muted = !!seg.muted
    v.volume = Math.min(1, Math.max(0, Math.pow(10, (seg.gain_db ?? 0) / 20)))
    if (playing && v.paused) v.play().catch(() => undefined)
    if (!playing && !v.paused) v.pause()
  }, [seg?.clip_id, seg?.media_url, playing, playhead]) // eslint-disable-line react-hooks/exhaustive-deps

  const audible = playing ? audioAt(seq, playhead) : []
  const caps = captionsAt(seq, playhead)
  const aspect = seq.aspect_ratio === '9:16' ? 'aspect-[9/16] max-h-[46vh]' : seq.aspect_ratio === '1:1' ? 'aspect-square max-h-[46vh]' : 'aspect-video'

  return (
    <div className="flex flex-col" data-testid="preview-player">
      <div className={`relative bg-ink rounded-el overflow-hidden ${aspect} mx-auto w-full flex items-center justify-center`}>
        {isVideo && (
          <video ref={videoRef} key={seg!.clip_id} src={seg!.media_url!} className="w-full h-full object-contain" playsInline preload="auto"
                 style={effectsToCss(seg!.effects)} data-testid="preview-video"
                 onError={() => setDecodeError(seg!.clip_id ?? null)} onLoadedData={() => setDecodeError(null)} />
        )}
        {decodeError != null && decodeError === seg?.clip_id && (
          <div className="absolute inset-x-4 bottom-10 text-center text-[11.5px] text-amber-300 bg-black/60 rounded p-1.5" data-testid="decode-error">
            This browser can't decode the clip's video (the export still renders it) — thumbnails and timing stay accurate.
          </div>
        )}
        {isImage && <img src={seg!.media_url!} alt="" className="w-full h-full object-contain" style={effectsToCss(seg!.effects)} />}
        {seg && seg.type === 'clip' && !seg.media_url && (
          <div className="text-[12px] text-amber-300 px-4 text-center">Clip has no media yet — generate or import a take, or replace it from the review queue.</div>
        )}
        {(!seg || seg.type === 'gap') && <div className="text-[11px] text-faint">— black —</div>}
        {caps.length > 0 && (
          <div className="absolute bottom-4 left-0 right-0 text-center pointer-events-none">
            {caps.map((c, i) => (
              <div key={i} className="inline-block bg-black/70 text-white text-[14px] px-2 py-0.5 rounded" data-testid="caption-overlay">{c}</div>
            ))}
          </div>
        )}
        {safe && (
          <div className="absolute inset-0 pointer-events-none" data-testid="safe-areas">
            <div className="absolute border border-white/40" style={{ inset: '5%' }} />
            <div className="absolute border border-white/25 border-dashed" style={{ inset: '10%' }} />
            <div className="absolute left-1/2 top-1/2 w-3 h-px bg-white/40" />
            <div className="absolute left-1/2 top-1/2 w-px h-3 bg-white/40" />
          </div>
        )}
      </div>
      {/* audio clips sound through their own elements */}
      {audible.map((c) => (
        <AudioBed key={c.id} url={c.media_url!} t={(c.trim_start_s ?? 0) + (playhead - c.start_s) * c.speed} gainDb={c.gain_db} playing={playing} rate={c.speed} />
      ))}
      <div className="flex items-center gap-1.5 mt-2 text-[12.5px]">
        <button className="btn !px-2" onClick={() => onStep(-1)} title="Previous frame (←)">⏮︎</button>
        <button className="btn-accent !px-3" onClick={onTogglePlay} title="Play / pause (Space)" data-testid="btn-play">{playing ? '⏸' : '▶'}</button>
        <button className="btn !px-2" onClick={() => onStep(1)} title="Next frame (→)">⏭︎</button>
        <button className={`chip ${loop ? '!border-ember text-fg' : ''}`} onClick={onToggleLoop} title="Loop (L)">loop</button>
        <button className={`chip ${safe ? '!border-ember text-fg' : ''}`} onClick={() => setSafe(!safe)} title="Safe areas">safe</button>
        <span className="font-mono tabular-nums ml-auto text-[13px]" data-testid="timecode">{fmtTcF(playhead, seq.fps)}</span>
        <span className="text-faint">/ {fmtTcF(seq.runtime_s, seq.fps)}</span>
      </div>
      <input
        type="range" min={0} max={Math.max(0.1, seq.runtime_s)} step={1 / seq.fps} value={Math.min(playhead, seq.runtime_s)}
        onChange={(e) => onSeek(Number(e.target.value))} className="w-full mt-1" aria-label="Scrub timeline"
      />
    </div>
  )
}

function AudioBed({ url, t, gainDb, playing, rate }: { url: string; t: number; gainDb: number; playing: boolean; rate: number }) {
  const ref = useRef<HTMLAudioElement | null>(null)
  useEffect(() => {
    const a = ref.current
    if (!a) return
    a.volume = Math.min(1, Math.max(0, Math.pow(10, gainDb / 20)))
    a.playbackRate = rate
    if (Math.abs(a.currentTime - t) > 0.25) a.currentTime = Math.max(0, t)
    if (playing && a.paused) a.play().catch(() => undefined)
    if (!playing && !a.paused) a.pause()
  }, [t, playing, gainDb, rate])
  useEffect(() => () => ref.current?.pause(), [])
  return <audio ref={ref} src={url} preload="auto" />
}
