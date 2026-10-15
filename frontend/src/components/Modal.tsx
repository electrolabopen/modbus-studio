import { useEffect, type FormEvent, type ReactNode } from 'react'

interface ModalProps {
  title: string
  submitLabel: string
  busy?: boolean
  error?: string | null
  onSubmit: () => void
  onClose: () => void
  /** Optional extra button on the left of the actions, e.g. "Reset". */
  secondary?: { label: string; onClick: () => void }
  /** Focus Cancel when the dialog opens, so a stray Enter does not confirm. */
  focusCancel?: boolean
  children: ReactNode
}

export function Modal({
  title,
  submitLabel,
  busy,
  error,
  onSubmit,
  onClose,
  secondary,
  focusCancel,
  children,
}: ModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit()
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="modal" role="dialog" aria-label={title} onSubmit={submit}>
        <h2>{title}</h2>
        <div className="modal-body">{children}</div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          {secondary && (
            <button
              type="button"
              className="btn modal-secondary"
              disabled={busy}
              onClick={secondary.onClick}
            >
              {secondary.label}
            </button>
          )}
          <button type="button" className="btn" autoFocus={focusCancel} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {submitLabel}
          </button>
        </div>
      </form>
    </div>
  )
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  )
}
