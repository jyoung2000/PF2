import { useCallback, useEffect, useRef, useState } from 'react'

export function useDebounced<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(t)
  }, [value, delayMs])
  return debounced
}

/** IntersectionObserver sentinel for infinite scroll. */
export function useInfiniteSentinel(onReach: () => void, enabled: boolean) {
  const ref = useRef<HTMLDivElement | null>(null)
  const cb = useRef(onReach)
  cb.current = onReach
  useEffect(() => {
    const el = ref.current
    if (!el || !enabled) return
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) cb.current()
      },
      { rootMargin: '900px' },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [enabled])
  return ref
}

/** Simple fetch-on-mount hook with reload(). */
export function useFetch<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fnRef
      .current()
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(load, [load])
  return { data, error, loading, reload: load, setData }
}

/** Close on Escape / outside click for popovers & drawers. */
export function useDismiss(onDismiss: () => void, active = true) {
  const ref = useRef<HTMLDivElement | null>(null)
  const cb = useRef(onDismiss)
  cb.current = onDismiss
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') cb.current()
    }
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) cb.current()
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [active])
  return ref
}
