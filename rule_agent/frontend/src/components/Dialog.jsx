import { useEffect, useRef, useState } from 'react'

function Overlay({ children, onClose }) {
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="modal-overlay dialog-overlay" onClick={onClose}>
      <div className="dialog-card" onClick={e => e.stopPropagation()}>
        {children}
      </div>
    </div>
  )
}

export function ConfirmDialog({ title, message, confirmLabel = 'Confirm', onConfirm, onCancel, danger = false }) {
  const btnRef = useRef(null)
  useEffect(() => { btnRef.current?.focus() }, [])

  return (
    <Overlay onClose={onCancel}>
      <div className="dialog-header">
        {danger && (
          <span className="dialog-icon-wrap danger" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M8 5.5v4M8 11.5v.5M6.9 2.5 1.5 11a1.3 1.3 0 0 0 1.1 2h10.8a1.3 1.3 0 0 0 1.1-2L9.1 2.5a1.3 1.3 0 0 0-2.2 0z"
                stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"
              />
            </svg>
          </span>
        )}
        <h3 className="dialog-title">{title}</h3>
      </div>
      {message && <p className="dialog-body">{message}</p>}
      <div className="dialog-actions">
        <button className="btn-secondary" onClick={onCancel}>Cancel</button>
        <button ref={btnRef} className={danger ? 'btn-danger' : 'btn-primary'} onClick={onConfirm}>
          {confirmLabel}
        </button>
      </div>
    </Overlay>
  )
}

export function RenameDialog({ title, initialValue = '', placeholder = 'New name…', onSave, onCancel }) {
  const [value, setValue] = useState(initialValue)
  const inputRef = useRef(null)

  useEffect(() => { inputRef.current?.select() }, [])

  function submit() {
    const v = value.trim()
    if (v) onSave(v)
  }

  return (
    <Overlay onClose={onCancel}>
      <h3 className="dialog-title">{title}</h3>
      <input
        ref={inputRef}
        className="dialog-input"
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') submit() }}
        placeholder={placeholder}
        autoFocus
      />
      <div className="dialog-actions">
        <button className="btn-secondary" onClick={onCancel}>Cancel</button>
        <button className="btn-primary" onClick={submit} disabled={!value.trim()}>
          Save
        </button>
      </div>
    </Overlay>
  )
}
