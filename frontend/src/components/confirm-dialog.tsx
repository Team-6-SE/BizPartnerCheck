import { useEffect, useRef, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'

/**
 * Asks before something that cannot be undone. A native <dialog>: Esc and the backdrop
 * cancel, focus stays inside, and the safe choice ("Cancel") has the focus first.
 */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  busy = false,
  error,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  busy?: boolean
  error?: string
  onConfirm: () => void
  onCancel: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const cancelButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (open && !element.open) {
      element.showModal()
      cancelButton.current?.focus()
    }
    if (!open && element.open) element.close()
  }, [open])

  return (
    <dialog
      ref={dialog}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onCancel()
      }}
      onClick={(event) => {
        if (event.target === dialog.current && !busy) onCancel()
      }}
      aria-labelledby="confirm-title"
      className="guide-player m-auto w-[min(440px,calc(100vw-32px))] rounded-2xl border bg-card p-6 text-card-foreground shadow-2xl"
    >
      <h2 id="confirm-title" className="font-heading text-lg font-semibold">
        {title}
      </h2>
      <div className="mt-2 text-sm text-muted-foreground">{children}</div>
      {error && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="mt-6 flex justify-end gap-2">
        <Button ref={cancelButton} variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button variant="destructive" onClick={onConfirm} disabled={busy}>
          {busy && <Spinner data-icon="inline-start" />}
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  )
}
