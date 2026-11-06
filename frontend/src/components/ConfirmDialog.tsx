import { useEffect, useRef } from 'react'

interface Props {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

// Replaces the native window.confirm()/alert(): a focus-trapped, Esc-dismissable
// dialog used before destructive actions (cancel appointment, delete patient,
// record no-show, etc.).
export default function ConfirmDialog({
  open, title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel',
  danger = false, onConfirm, onCancel,
}: Props) {
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    confirmRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="absolute inset-0 bg-ink-950/40 backdrop-blur-sm animate-fadein" onClick={onCancel} aria-hidden />
      <div className="relative w-full max-w-sm bg-white rounded-2xl shadow-xl border border-ink-100 p-5 animate-fadein">
        <h3 id="confirm-title" className="text-base font-bold text-ink-900">{title}</h3>
        <p className="text-sm text-ink-500 mt-2 leading-relaxed">{message}</p>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-ghost" onClick={onCancel}>{cancelLabel}</button>
          <button
            ref={confirmRef}
            className={danger ? 'btn-danger' : 'btn-primary'}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
