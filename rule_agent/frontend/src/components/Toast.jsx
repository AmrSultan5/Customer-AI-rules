import { useEffect } from 'react'

const AUTO_DISMISS_MS = 6000

const CheckIcon = () => (
  <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M2.5 7.5l3 3 6-6.5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const WarnIcon = () => (
  <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M7 1.4l6.2 11.2H0.8L7 1.4z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    <path d="M7 5.6v3M7 10.8h.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
)

function ToastItem({ toast, onDismiss }) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(toast.id), AUTO_DISMISS_MS)
    return () => clearTimeout(timer)
  }, [toast.id, onDismiss])

  return (
    <div className={`toast toast-${toast.type}`}>
      <span className="toast-icon" aria-hidden="true">
        {toast.type === 'error' ? <WarnIcon /> : <CheckIcon />}
      </span>
      <span className="toast-message">{toast.message}</span>
      <button className="toast-close" onClick={() => onDismiss(toast.id)} aria-label="Dismiss notification">
        ×
      </button>
    </div>
  )
}

/**
 * App-wide toast host — dismissible success/error notices that fire
 * regardless of what's open (e.g. a repo-ingest finishing while Settings
 * is closed). Mount once at the app root.
 */
export default function ToastHost({ toasts, onDismiss }) {
  if (!toasts?.length) return null
  return (
    <div className="toast-host" role="status" aria-live="polite">
      {toasts.map(t => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  )
}
