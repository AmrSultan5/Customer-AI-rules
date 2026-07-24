/**
 * Tiny toast event bus.
 *
 * Lets any module or deeply-nested component raise a user-facing toast without
 * prop-drilling the app-level pushToast through the tree. App.jsx subscribes
 * once and feeds these into its toast state (rendered by ToastHost). Use this
 * for failures the user should know about (a save/load/send that didn't work) —
 * NOT for best-effort/background things (localStorage, clipboard, analytics).
 */

let _listeners = []
let _seq = 0

/** Subscribe to bus toasts. Returns an unsubscribe function. */
export function subscribeToasts(listener) {
  _listeners.push(listener)
  return () => {
    _listeners = _listeners.filter((l) => l !== listener)
  }
}

/** Raise a toast: { type: 'error' | 'success', message }. No-op if no message. */
export function notify({ type = 'error', message } = {}) {
  if (!message) return null
  const toast = { id: `bus-${Date.now()}-${_seq++}`, type, message }
  _listeners.forEach((l) => {
    try { l(toast) } catch { /* a broken listener must not break the caller */ }
  })
  return toast.id
}

export const notifyError = (message) => notify({ type: 'error', message })
export const notifySuccess = (message) => notify({ type: 'success', message })
