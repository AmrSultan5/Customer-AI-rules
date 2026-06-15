import { useState } from 'react'
import { login, setUsername } from '../api.js'

/**
 * Lightweight username login — no password. Claims (or creates) a workspace by
 * name. The name is stored in localStorage and sent as the X-User header.
 */
export default function Login({ initial = '', onDone }) {
  const [name, setName] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit(e) {
    e?.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    setErr('')
    // Persist first so the X-User header is attached to the login request.
    setUsername(trimmed)
    try {
      await login(trimmed)
      onDone?.(trimmed)
    } catch {
      setUsername(initial || '')
      setErr('Could not sign in. Please try again.')
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay login-overlay">
      <form className="modal-card login-card" onSubmit={submit}>
        <h2 className="login-title">Welcome to Rule Intelligence</h2>
        <p className="login-sub">Enter a username to open your workspace. Your chats and projects are saved under this name.</p>
        <input
          className="login-input"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="e.g. amr"
          autoFocus
          maxLength={64}
        />
        {err && <p className="login-error">{err}</p>}
        <button className="btn-primary login-submit" type="submit" disabled={busy || !name.trim()}>
          {busy ? 'Opening…' : 'Continue'}
        </button>
      </form>
    </div>
  )
}
