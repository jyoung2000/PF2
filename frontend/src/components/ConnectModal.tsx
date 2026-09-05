// One-click in-app login (X5): streams the server's own headless browser into
// a modal — the user logs in themselves (clicks/keys forwarded verbatim, never
// stored), and the session storage_state saves server-side. Auto-detects X
// login; other sites use the "Save session now" button.
import { useCallback, useEffect, useRef, useState } from 'react'
import { deleteScraperSession, testScraper, uploadScraperSession } from '../api'
import { toastError, toastSuccess } from '../lib/toast'
import { Spinner } from './Primitives'

/** Paste-to-connect for API-key sources (Civitai): committing a key
 * (paste / Enter / blur) saves it and immediately runs the site's connection
 * test — one paste and the source is connected. */
export function ApiKeyConnect({
  platform,
  settingKey,
  keyUrl,
  configured,
  masked,
  save,
  onChanged,
}: {
  platform: string
  settingKey: string
  keyUrl?: string | null
  configured: boolean
  masked?: string
  save: (v: Record<string, unknown>) => Promise<boolean>
  onChanged?: () => void
}) {
  const [value, setValue] = useState('')
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null)

  const runTest = async () => {
    setTesting(true)
    try {
      const r = await testScraper(platform)
      setResult(r)
      if (r.ok) toastSuccess(`${platform} connected ✓`)
    } catch (e) {
      setResult({ ok: false, detail: (e as Error).message })
    } finally {
      setTesting(false)
      onChanged?.()
    }
  }

  const commit = async (raw?: string) => {
    const v = (raw ?? value).trim()
    if (!v) return
    if (await save({ [settingKey]: v })) {
      setValue('')
      await runTest()
    }
  }

  const forget = async () => {
    if (await save({ [settingKey]: '' })) {
      setResult(null)
      toastSuccess('Key removed')
      onChanged?.()
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <input
          id={`setting-${settingKey}`}
          type="text"
          autoComplete="off"
          spellCheck={false}
          className="input font-mono flex-1 min-w-[220px]"
          placeholder={configured ? `${masked || '••••'} stored — paste to replace` : 'paste API key to connect'}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onPaste={(e) => {
            const text = e.clipboardData.getData('text').trim()
            if (text) {
              e.preventDefault()
              setValue(text)
              void commit(text)
            }
          }}
          onBlur={() => void commit()}
          onKeyDown={(e) => e.key === 'Enter' && void commit()}
        />
        {keyUrl && (
          <a className="btn !py-1.5 text-[12px] whitespace-nowrap" href={keyUrl} target="_blank" rel="noreferrer">
            Get an API key ↗
          </a>
        )}
        {configured && (
          <>
            <button className="btn !py-1.5 text-[12px]" onClick={runTest} disabled={testing}>
              {testing ? <Spinner /> : 'Test'}
            </button>
            <button className="btn !py-1.5 text-[12px]" onClick={forget}>
              Remove key
            </button>
          </>
        )}
      </div>
      {result && (
        <p
          className={`text-[12.5px] rounded-el px-3 py-2 border ${
            result.ok
              ? 'text-emerald-300 bg-emerald-400/10 border-emerald-400/30'
              : 'text-red-300 bg-red-400/10 border-red-400/30'
          }`}
        >
          {result.ok ? '✓ ' : ''}
          {result.detail}
        </p>
      )}
    </div>
  )
}

const VIEW_W = 1280
const VIEW_H = 800

type ConnState = 'connecting' | 'launching' | 'live' | 'saving' | 'saved' | 'error'

const SPECIAL_KEYS = new Set([
  'Enter', 'Backspace', 'Delete', 'Tab', 'Escape', 'ArrowUp', 'ArrowDown',
  'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown',
])

export function ConnectModal({
  platform,
  label,
  onClose,
  onConnected,
}: {
  platform: string
  label: string
  onClose: () => void
  onConnected: () => void
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const wheelAcc = useRef(0)
  const wheelTimer = useRef<number | null>(null)
  const [state, setState] = useState<ConnState>('connecting')
  const [message, setMessage] = useState('')
  // generic-detection sites save without closing: the window stays live so
  // an unfinished login can continue, and "Save session now" re-saves
  const [autoSaved, setAutoSaved] = useState(false)

  const send = useCallback((obj: Record<string, unknown>) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj))
  }, [])

  useEffect(() => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/api/ws/connect/${platform}`)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws
    let closedByUs = false

    ws.onmessage = async (ev) => {
      if (typeof ev.data === 'string') {
        const msg = JSON.parse(ev.data)
        if (msg.t === 'status') {
          setState(msg.state as ConnState)
          setMessage(msg.message ?? '')
        } else if (msg.t === 'saved') {
          onConnected()
          if (msg.final === false) {
            setAutoSaved(true)
            setMessage(msg.message ?? 'Login detected — session saved ✓.')
            toastSuccess(`${label} connected ✓ — keep going if you weren't done`)
            return
          }
          setState('saved')
          setMessage('Session saved — this site is now connected.')
          toastSuccess(`${label} connected ✓`)
          window.setTimeout(onClose, 1400)
        } else if (msg.t === 'error') {
          setState('error')
          setMessage(msg.message ?? 'Something went wrong.')
        }
        return
      }
      try {
        const bmp = await createImageBitmap(new Blob([ev.data], { type: 'image/jpeg' }))
        const ctx = canvasRef.current?.getContext('2d')
        if (ctx) ctx.drawImage(bmp, 0, 0, VIEW_W, VIEW_H)
        bmp.close()
      } catch {
        /* dropped frame */
      }
    }
    ws.onerror = () => {
      setState((s) => (s === 'saved' || closedByUs ? s : 'error'))
      setMessage((m) => m || 'Connection to the server lost.')
    }
    ws.onclose = () => {
      setState((s) => (s === 'saved' || s === 'error' || closedByUs ? s : 'error'))
      setMessage((m) => m || 'The connect window closed.')
    }
    wrapRef.current?.focus()
    return () => {
      closedByUs = true
      ws.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [platform])

  const clickAt = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    send({
      t: 'click',
      x: ((e.clientX - rect.left) / rect.width) * VIEW_W,
      y: ((e.clientY - rect.top) / rect.height) * VIEW_H,
    })
    wrapRef.current?.focus()
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (state !== 'live') return
    const mod = e.ctrlKey || e.metaKey
    if (mod && e.key.toLowerCase() === 'v') return // let the paste event carry the text
    if (!mod && !e.altKey && e.key.length === 1) {
      send({ t: 'text', text: e.key })
      e.preventDefault()
      return
    }
    if (SPECIAL_KEYS.has(e.key) || (mod && e.key.length === 1)) {
      send({ t: 'key', key: e.key.length === 1 ? e.key.toLowerCase() : e.key, ctrl: e.ctrlKey, alt: e.altKey, shift: e.shiftKey, meta: e.metaKey })
      e.preventDefault()
    }
  }

  const onPaste = (e: React.ClipboardEvent) => {
    const text = e.clipboardData.getData('text')
    if (text) {
      send({ t: 'text', text })
      e.preventDefault()
    }
  }

  const onWheel = (e: React.WheelEvent) => {
    wheelAcc.current += e.deltaY
    if (wheelTimer.current == null) {
      wheelTimer.current = window.setTimeout(() => {
        send({ t: 'scroll', dy: wheelAcc.current })
        wheelAcc.current = 0
        wheelTimer.current = null
      }, 110)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/75 flex items-start sm:items-center justify-center p-2 sm:p-6 overflow-y-auto">
      <div
        ref={wrapRef}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        className="card w-full max-w-[960px] p-3 sm:p-4 outline-none space-y-3"
        role="dialog"
        aria-label={`Connect ${label}`}
      >
        <div className="flex items-center gap-2">
          <h2 className="font-display font-medium text-[15.5px]">Connect {label}</h2>
          <span className="chip !text-[10.5px]">your server's browser</span>
          <button className={`ml-auto ${autoSaved ? 'btn-accent' : 'btn'}`} onClick={onClose}>
            {autoSaved ? 'Done' : 'Cancel'}
          </button>
        </div>

        <p
          className={`text-[12.5px] rounded-el px-3 py-2 border ${
            state === 'error'
              ? 'text-red-300 bg-red-400/10 border-red-400/30'
              : state === 'saved' || autoSaved
                ? 'text-emerald-300 bg-emerald-400/10 border-emerald-400/30'
                : 'text-mute bg-well/50 border-line'
          }`}
        >
          {state === 'connecting' && 'Opening a connection…'}
          {state === 'launching' && (message || 'Starting the browser…')}
          {state === 'live' &&
            (autoSaved
              ? `✓ ${message}`
              : message ||
                'Log in below exactly as usual — keystrokes go straight to the page and are never stored. If a verification step appears, just complete it yourself.')}
          {state === 'saving' && (message || 'Saving your session…')}
          {(state === 'saved' || state === 'error') && message}
        </p>

        <div className="relative rounded-el overflow-hidden border border-line bg-black">
          <canvas
            ref={canvasRef}
            width={VIEW_W}
            height={VIEW_H}
            onClick={clickAt}
            onWheel={onWheel}
            className="w-full block cursor-pointer select-none"
            style={{ aspectRatio: `${VIEW_W} / ${VIEW_H}` }}
          />
          {(state === 'connecting' || state === 'launching') && (
            <div className="absolute inset-0 flex items-center justify-center text-mute">
              <Spinner /> <span className="ml-2 text-[13px]">warming up Chromium…</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <button className="btn-accent" onClick={() => send({ t: 'save' })} disabled={state !== 'live'}>
            Save session now
          </button>
          <span className="text-[12px] text-faint">
            {platform === 'x' || platform === 'midjourney' || platform === 'grok'
              ? 'Saves automatically the moment you finish logging in — the button is a manual fallback.'
              : 'Saves itself when a login is detected; click this if you finish and it hasn’t.'}
          </span>
        </div>
      </div>
    </div>
  )
}

/** "or upload a session file" — installs a capture_login.py export. */
export function SessionUploadButton({
  platform,
  onDone,
  className = 'btn',
  children,
}: {
  platform: string
  onDone: () => void
  className?: string
  children?: React.ReactNode
}) {
  const input = useRef<HTMLInputElement | null>(null)
  return (
    <>
      <button className={className} onClick={() => input.current?.click()}>
        {children ?? 'Upload session file…'}
      </button>
      <input
        ref={input}
        type="file"
        accept=".json,application/json"
        className="hidden"
        aria-label={`Upload ${platform} session file`}
        onChange={async (e) => {
          const f = e.target.files?.[0]
          e.currentTarget.value = ''
          if (!f) return
          try {
            await uploadScraperSession(platform, f)
            toastSuccess('Session installed ✓')
            onDone()
          } catch (err) {
            toastError((err as Error).message)
          }
        }}
      />
    </>
  )
}

/** Forget the stored login session (posts are kept). */
export function DisconnectButton({
  platform,
  onDone,
  className = 'btn',
}: {
  platform: string
  onDone: () => void
  className?: string
}) {
  return (
    <button
      className={className}
      onClick={async () => {
        if (!window.confirm('Forget this login session? Collected posts stay; you can reconnect any time.')) return
        try {
          await deleteScraperSession(platform)
          toastSuccess('Session removed')
          onDone()
        } catch (e) {
          toastError((e as Error).message)
        }
      }}
    >
      Disconnect
    </button>
  )
}
