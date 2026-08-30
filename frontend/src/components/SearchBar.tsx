import { useEffect, useRef, useState } from 'react'
import { getSuggestions, Suggestions } from '../api'
import { useDebounced, useDismiss } from '../lib/hooks'

export function SearchBar({
  value,
  onChange,
  placeholder = 'Search prompts, models, tags…  (try  model:flux  or  tag:cyberpunk)',
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
      {open && hasSuggestions && (
        <div className="absolute z-50 mt-1.5 w-full card shadow-xl shadow-black/40 py-1.5 fade-in">
          {sugg!.models.length > 0 && (
            <div className="px-3 pb-1 pt-0.5 text-[11px] uppercase tracking-wide text-faint">Models</div>
          )}
          {sugg!.models.map((m) => (
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
          {sugg!.tags.length > 0 && (
            <div className="px-3 pb-1 pt-1.5 text-[11px] uppercase tracking-wide text-faint border-t border-line mt-1">
              Tags
            </div>
          )}
          {sugg!.tags.map((t) => (
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
