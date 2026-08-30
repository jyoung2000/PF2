import { useState } from 'react'
import { addTag, listTags, removeTag } from '../api'
import { toastError } from '../lib/toast'

export function TagEditor({
  postId,
  tags,
  onTagsChange,
  onTagClick,
}: {
  postId: number
  tags: string[]
  onTagsChange: (tags: string[]) => void
  onTagClick?: (tag: string) => void
}) {
  const [input, setInput] = useState('')
  const [suggestions, setSuggestions] = useState<string[]>([])

  const add = async (name: string) => {
    const trimmed = name.trim()
    if (!trimmed) return
    try {
      const r = await addTag(postId, trimmed)
      onTagsChange(r.tags)
      setInput('')
      setSuggestions([])
    } catch (e) {
      toastError(`Couldn't add tag: ${(e as Error).message}`)
    }
  }

  const remove = async (name: string) => {
    try {
      const r = await removeTag(postId, name)
      onTagsChange(r.tags)
    } catch (e) {
      toastError(`Couldn't remove tag: ${(e as Error).message}`)
    }
  }

  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {tags.map((t) => (
          <span key={t} className="chip !text-fg group/tag">
            <button
              className="hover:text-ember"
              title={`Search tag:${t}`}
              onClick={() => onTagClick?.(t)}
            >
              {t}
            </button>
            <button
              aria-label={`Remove tag ${t}`}
              className="text-faint hover:text-red-300 ml-0.5"
              onClick={() => remove(t)}
            >
              ✕
            </button>
          </span>
        ))}
        {tags.length === 0 && <span className="text-faint text-[12px]">No tags yet</span>}
      </div>
      <div className="relative mt-2">
        <input
          className="input h-8 text-[12.5px]"
          placeholder="Add a tag…"
          value={input}
          aria-label="Add a tag"
          onChange={(e) => {
            const v = e.target.value
            setInput(v)
            if (v.trim()) {
              listTags(v.trim())
                .then((r) => setSuggestions(r.tags.map((t) => t.name).filter((n) => !tags.includes(n))))
                .catch(() => undefined)
            } else setSuggestions([])
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') add(input)
            if (e.key === 'Escape') setSuggestions([])
          }}
        />
        {suggestions.length > 0 && (
          <div className="absolute z-30 mt-1 w-full card shadow-lg shadow-black/40 py-1 max-h-44 overflow-y-auto">
            {suggestions.map((s) => (
              <button
                key={s}
                className="w-full text-left px-2.5 py-1 text-[12.5px] hover:bg-well"
                onClick={() => add(s)}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
