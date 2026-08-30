export function formatBytes(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—'
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n
  let i = -1
  do {
    v /= 1024
    i++
  } while (v >= 1024 && i < units.length - 1)
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (isNaN(then)) return '—'
  const sec = Math.max(0, (Date.now() - then) / 1000)
  if (sec < 60) return 'just now'
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  if (sec < 86400 * 30) return `${Math.floor(sec / 86400)}d ago`
  return new Date(iso).toLocaleDateString()
}

export function formatDuration(s: number | null | undefined): string {
  if (s == null || !isFinite(s)) return ''
  const total = Math.round(s)
  const m = Math.floor(total / 60)
  const rest = total % 60
  return m > 0 ? `${m}:${String(rest).padStart(2, '0')}` : `0:${String(rest).padStart(2, '0')}`
}

export function firstLine(text: string | null | undefined, max = 110): string {
  if (!text) return ''
  const line = text.split('\n')[0]
  return line.length > max ? `${line.slice(0, max - 1)}…` : line
}

export function formatMoney(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—'
  return v < 0.1 ? `$${v.toFixed(3)}` : `$${v.toFixed(2)}`
}
