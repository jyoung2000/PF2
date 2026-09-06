import { useEffect, useRef, useState } from 'react'
import { getSuggestions, Suggestions } from '../api'
import { useDebounced, useDismiss } from '../lib/hooks'

/** Search qualifiers the backend understands (intel/query.py). Shown as
 *  completions the moment the user types a `word:` prefix, so the syntax is
 *  discoverable instead of documented somewhere else. */
const QUALIFIERS: { token: string; hint: string }[] = [
  { token: 'model:', hint: 'flux, kling, veo…' },
  { token: 'tag:', hint: 'your own tags' },
  { token: 'source:', hint: 'reddit, bluesky, civitai, x…' },
  { token: 'creator:', hint: 'a handle' },
  { token: 'has:', hint: 'prompt | workflow | video | image | metadata | comments' },
  { token: 'prompt_source:', hint: 'explicit | assembled | ai | embedded_metadata…' },
  { token: 'confidence:', hint: '>0.8 — how sure PF2 is of the prompt' },
  { token: 'technique:', hint: 'a technique slug' },
  { token: 'camera:', hint: '35mm, close-up, low-angle' },
  { token: 'ai:', hint: 'true | false | uncertain' },
  { token: 'model_source:', hint: 'explicit | metadata | inferred | ai' },
  { token: 'engagement:', hint: '>1000' },
  { token: 'inspiration:', hint: '>80' },
  { token: 'after:', hint: 'YYYY-MM-DD' },
  { token: 'before:', hint: 'YYYY-MM-DD' },
  { token: 'research:', hint: 'a research job id' },
  { token: 'sort:', hint: 'inspiration | engagement | newest | oldest' },
]

export function SearchBar({
  value,
  onChange,
  placeholder = 'Search prompts, models, tags…  (try  model:flux,  has:workflow  or  prompt_source:explicit)',
  autoFocus = false,
}: {
  value: string
  onChange: (q: string) => void
  placeholder?: string
  autoFocus?: boolean
}) {
  const [text, setText] = useState(value)
  const [open, setOpen] = useState(false)
  const [sugg, setSugg] = useState<Suggestions | null>(null)
  const debounced = useDebounced(text, 250)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const boxRef = useDismiss(() => setOpen(false), open)

  useEffect(() => setText(value), [value])
  useEffect(() => {
    onChange(debounced)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])

  useEffect(() => {
    const lastWord = text.split(/\s+/).pop() ?? ''
    if (!open || lastWord.length < 1) {
      setSugg(null)
      return
    }
    let live = true
    getSuggestions(lastWord.replace(/^(tag|model|platform):/i, ''))
      .then((s) => live && setSugg(s))
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [text, open])

  // qualifier completions: only while typing the KEY, never mid-value
  const lastWord = text.split(/\s+/).pop() ?? ''
  const qualifierMatches =
    lastWord.length >= 1 && !lastWord.includes(':')
      ? QUALIFIERS.filter((q) => q.token.startsWith(lastWord.toLowerCase())).slice(0, 6)
      : []

  const applySuggestion = (token: string) => {
    const words = text.split(/\s+/)
    words.pop()
    const next = [...words, token, ''].join(' ').replace(/\s+/g, ' ').trimStart()
    setText(next)
    inputRef.current?.focus()
  }

  const hasSuggestions = !!sugg && (sugg.models.length > 0 || sugg.tags.length > 0)

  return (
    <div ref={boxRef} className="relative w-full">
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-faint text-[13px]" aria-hidden>
          ⌕
        </span>
        <input
          ref={inputRef}
          type="search"
          role="searchbox"
          aria-label="Search"
          autoFocus={autoFocus}
          className="input pl-8 pr-8 h-10 text-[14px] bg-panel"
          placeholder={placeholder}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') setOpen(false)
          }}
        />
        {text && (
          <button
            aria-label="Clear search"
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-faint hover:text-fg text-[13px]"
            onClick={() => {
              setText('')
              setOpen(false)
            }}
          >
            ✕
          </button>
        )}
      </div>
      {open && (hasSuggestions || qualifierMatches.length > 0) && (
        <div className="absolute z-50 mt-1.5 w-full card shadow-xl shadow-black/40 py-1.5 fade-in">
          {qualifierMatches.length > 0 && (
            <>
              <div className="px-3 pb-1 pt-0.5 text-[11px] uppercase tracking-wide text-faint">Qualifiers</div>
              {qualifierMatches.map((q) => (
                <button
                  key={q.token}
                  className="w-full text-left px-3 py-1.5 hover:bg-well text-[13px] flex justify-between gap-3"
                  onClick={() => applySuggestion(q.token)}
                >
                  <span className="text-fg">{q.token}</span>
                  <span className="text-faint truncate">{q.hint}</span>
                </button>
              ))}
            </>
          )}
          {sugg?.models.length ? (
            <div className="px-3 pb-1 pt-0.5 text-[11px] uppercase tracking-wide text-faint">Models</div>
          ) : null}
          {(sugg?.models ?? []).map((m) => (
            <button
              key={m.family}
              className="w-full text-left px-3 py-1.5 hover:bg-well text-[13px] flex justify-between"
              onClick={() => applySuggestion(`model:${m.family}`)}
            >
              <span>
                <span className="text-faint">model:</span>
                {m.label}
              </span>
              <span className="chip">{m.count}</span>
            </button>
          ))}
          {sugg?.tags.length ? (
            <div className="px-3 pb-1 pt-1.5 text-[11px] uppercase tracking-wide text-faint border-t border-line mt-1">
              Tags
            </div>
          ) : null}
          {(sugg?.tags ?? []).map((t) => (
            <button
              key={t.name}
              className="w-full text-left px-3 py-1.5 hover:bg-well text-[13px] flex justify-between"
              onClick={() => applySuggestion(`tag:${t.name}`)}
            >
              <span>
                <span className="text-faint">tag:</span>
                {t.name}
              </span>
              <span className="chip">{t.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
