import { ReactNode } from 'react'
import { useDismiss } from '../lib/hooks'

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />
}

export function SkeletonGrid({ count = 12 }: { count?: number }) {
  const heights = [220, 300, 260, 340, 200, 280, 320, 240, 300, 220, 260, 340]
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} style={{ height: heights[i % heights.length] }} className="skeleton" />
      ))}
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  action,
  icon = '◇',
}: {
  title: string
  hint?: string
  action?: ReactNode
  icon?: string
}) {
  return (
    <div className="fade-in flex flex-col items-center justify-center py-24 px-6 text-center">
      <div className="text-3xl mb-3 text-faint" aria-hidden>
        {icon}
      </div>
      <h3 className="font-display font-medium text-[16px] text-fg">{title}</h3>
      {hint && <p className="text-mute text-[13px] mt-1.5 max-w-sm">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <EmptyState
      icon="⚠"
      title="Something needs attention"
      hint={message}
      action={
        onRetry && (
          <button className="btn" onClick={onRetry}>
            Try again
          </button>
        )
      }
    />
  )
}

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const ref = useDismiss(onClose)
  return (
    <div className="fixed inset-0 z-[70] bg-ink/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div
        ref={ref}
        role="dialog"
        aria-modal
        aria-label={title}
        className={`card fade-in w-full ${wide ? 'max-w-2xl' : 'max-w-md'} max-h-[88vh] flex flex-col shadow-2xl shadow-black/50`}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-line shrink-0">
          <h2 className="font-display font-medium text-[15px]">{title}</h2>
          <button className="btn-ghost px-2 py-1" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="p-4 overflow-y-auto">{children}</div>
      </div>
    </div>
  )
}

export function ConfirmModal({
  title,
  message,
  confirmLabel = 'Delete',
  onConfirm,
  onClose,
}: {
  title: string
  message: string
  confirmLabel?: string
  onConfirm: () => void
  onClose: () => void
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <p className="text-mute text-[13px]">{message}</p>
      <div className="flex justify-end gap-2 mt-5">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn-danger border-red-400/40 text-red-300"
          onClick={() => {
            onConfirm()
            onClose()
          }}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  )
}

export function StatusDot({
  status,
  label,
}: {
  status: 'ok' | 'error' | 'needs_setup' | 'experimental' | 'off'
  label?: string
}) {
  const color =
    status === 'ok'
      ? 'bg-emerald-400'
      : status === 'error'
        ? 'bg-red-400'
        : status === 'experimental'
          ? 'bg-amber-400'
          : 'bg-faint'
  return (
    <span className="inline-flex items-center gap-1.5" title={label}>
      <span className={`w-1.5 h-1.5 rounded-full ${color}`} />
      {label && <span className="text-[12px] text-mute">{label}</span>}
    </span>
  )
}

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-block w-3.5 h-3.5 border-2 border-mute/40 border-t-fg rounded-full animate-spin ${className}`}
      aria-label="Loading"
    />
  )
}
