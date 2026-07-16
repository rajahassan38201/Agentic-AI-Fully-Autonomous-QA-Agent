import { useEffect, useRef } from 'react'

export default function ConfirmDialog({
  title,
  body,
  confirmLabel = 'Confirm',
  tone = 'danger',
  busy = false,
  onConfirm,
  onCancel,
}) {
  const confirmRef = useRef(null)

  useEffect(() => {
    confirmRef.current?.focus()
  }, [])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="modal modal-sm" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <header className="modal-head">
          <h2 id="confirm-title">{title}</h2>
        </header>
        <div className="modal-body">
          <p className="confirm-body">{body}</p>
          <footer className="modal-foot">
            <button type="button" className="btn btn-quiet" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button
              type="button"
              ref={confirmRef}
              className={tone === 'danger' ? 'btn btn-danger' : 'btn btn-primary'}
              onClick={onConfirm}
              disabled={busy}
            >
              {busy ? 'Working…' : confirmLabel}
            </button>
          </footer>
        </div>
      </div>
    </div>
  )
}
