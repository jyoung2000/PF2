// Tiny toast store + renderer (D34): no external state lib.
import { useEffect, useState } from 'react'

export interface Toast {
  id: number
  kind: 'success' | 'error' | 'info'
  message: string
}

type Listener = (toasts: Toast[]) => void

let toasts: Toast[] = []
let nextId = 1
const listeners = new Set<Listener>()

function emit() {
  for (const l of listeners) l([...toasts])
}

export function toast(kind: Toast['kind'], message: string, ttlMs = 4200) {
  const t: Toast = { id: nextId++, kind, message }
  toasts = [...toasts, t].slice(-4)
  emit()
  window.setTimeout(() => {
    toasts = toasts.filter((x) => x.id !== t.id)
    emit()
  }, ttlMs)
}

export const toastSuccess = (m: string) => toast('success', m)
export const toastError = (m: string) => toast('error', m, 6500)
export const toastInfo = (m: string) => toast('info', m)

export function Toasts() {
  const [items, setItems] = useState<Toast[]>([])
  useEffect(() => {
    const l: Listener = setItems
    listeners.add(l)
    return () => {
      listeners.delete(l)
    }
  }, [])
  if (!items.length) return null
  return (
    <div className="fixed bottom-4 right-4 z-[90] flex flex-col gap-2 max-w-[92vw] sm:max-w-md">
      {items.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`card fade-in px-3.5 py-2.5 text-[13px] shadow-xl shadow-black/40 border-l-2 ${
            t.kind === 'error'
              ? 'border-l-red-400 text-red-200'
              : t.kind === 'success'
                ? 'border-l-emerald-400'
                : 'border-l-ember'
          }`}
        >
          {t.message}
        </div>
      ))}
    </div>
  )
}
