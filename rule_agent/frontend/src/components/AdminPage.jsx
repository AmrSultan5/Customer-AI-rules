import { useState, useEffect } from 'react'
import AdminDashboard from './AdminDashboard.jsx'
import { apiFetch } from '../api.js'

const SESSION_KEY = 'rule_agent_admin_token'

// Brand mark — same red disc + wave as the favicon for full identity consistency
const BrandMark = ({ size = 36 }) => (
  <svg width={size} height={size} viewBox="0 0 17 17" aria-hidden="true" style={{ display: 'block' }}>
    <circle cx="8.5" cy="8.5" r="8.5" fill="#E8000D" />
    <path
      d="M2.5 10.5C5.4 6.9 8.2 12.4 11 9.3c1.5-1.7 2.5-2.9 3.5-3.9"
      stroke="#fff" strokeWidth="1.9" strokeLinecap="round" fill="none"
    />
  </svg>
)

const ArrowLeftIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M7.5 2.5L4 6l3.5 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const UserIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <circle cx="7" cy="4.5" r="2.5" stroke="currentColor" strokeWidth="1.3" />
    <path d="M2 12c0-2.76 2.24-5 5-5s5 2.24 5 5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
  </svg>
)

const LockIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="2.5" y="6" width="9" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
    <path d="M4.5 6V4.5a2.5 2.5 0 0 1 5 0V6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    <circle cx="7" cy="9.5" r="1" fill="currentColor" />
  </svg>
)

const EyeIcon = ({ off }) => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M1.5 7C1.5 7 3.5 3 7 3s5.5 4 5.5 4-2 4-5.5 4S1.5 7 1.5 7z" stroke="currentColor" strokeWidth="1.2" />
    <circle cx="7" cy="7" r="1.8" stroke="currentColor" strokeWidth="1.2" />
    {off && <path d="M2.5 11.5l9-9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />}
  </svg>
)

const AlertIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true" style={{ flexShrink: 0 }}>
    <circle cx="6.5" cy="6.5" r="5.5" stroke="currentColor" strokeWidth="1.2" />
    <path d="M6.5 3.8v3.2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    <circle cx="6.5" cy="9.3" r="0.8" fill="currentColor" />
  </svg>
)

// ── Auth gate ──────────────────────────────────────────────────────────────

function AuthGate({ onAuthenticated }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPw,   setShowPw]   = useState(false)
  const [error,    setError]    = useState('')
  const [busy,     setBusy]     = useState(false)

  async function attempt(e) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setBusy(true); setError('')
    try {
      const res = await apiFetch('/admin/login', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ username: username.trim(), password }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.token !== undefined) {
        sessionStorage.setItem(SESSION_KEY, data.token)
        onAuthenticated(data.token)
      } else if (res.status === 401) {
        setError(data?.detail?.error ?? 'Invalid username or password.')
      } else {
        setError(`Server error (${res.status}). Is the backend running?`)
      }
    } catch {
      setError('Could not reach the server. Make sure the backend is running.')
    } finally {
      setBusy(false)
    }
  }

  const hasError = !!error

  return (
    <div className="adm-gate">
      <main className="adm-gate-card">
        <div className="adm-gate-brand"><BrandMark size={46} /></div>
        <span className="adm-gate-eyebrow">Coca-Cola HBC &middot; Admin Portal</span>
        <h1 className="adm-gate-title">Rule Intelligence</h1>
        <p className="adm-gate-sub">Sign in to access the Rule Health Dashboard.</p>

        <form className="adm-gate-form" onSubmit={attempt}>
          <div className="adm-field">
            <label className="adm-field-label" htmlFor="adm-username">Username</label>
            <div className={`adm-field-wrap${hasError ? ' adm-field-error' : ''}`}>
              <span className="adm-field-icon"><UserIcon /></span>
              <input
                id="adm-username"
                className="adm-field-input"
                type="text"
                placeholder="admin"
                value={username}
                onChange={e => { setUsername(e.target.value); setError('') }}
                autoFocus
                autoComplete="username"
                disabled={busy}
              />
            </div>
          </div>

          <div className="adm-field">
            <label className="adm-field-label" htmlFor="adm-password">Password</label>
            <div className={`adm-field-wrap${hasError ? ' adm-field-error' : ''}`}>
              <span className="adm-field-icon"><LockIcon /></span>
              <input
                id="adm-password"
                className="adm-field-input"
                type={showPw ? 'text' : 'password'}
                placeholder="••••••••"
                value={password}
                onChange={e => { setPassword(e.target.value); setError('') }}
                autoComplete="current-password"
                disabled={busy}
              />
              <button
                type="button"
                className="adm-field-toggle"
                onClick={() => setShowPw(s => !s)}
                aria-label={showPw ? 'Hide password' : 'Show password'}
                tabIndex={-1}
              >
                <EyeIcon off={showPw} />
              </button>
            </div>
          </div>

          {error && (
            <p className="adm-gate-alert" role="alert">
              <AlertIcon />
              {error}
            </p>
          )}

          <button
            className="adm-gate-submit"
            type="submit"
            disabled={busy || !username.trim() || !password}
          >
            {busy ? <><span className="adm-spinner" aria-hidden="true" /> Signing in…</> : 'Sign in'}
          </button>
        </form>

        <a href="/" className="adm-gate-back"><ArrowLeftIcon /> Back to Rule Intelligence</a>
      </main>

      <p className="adm-gate-footer">
        &copy; Coca-Cola HBC &middot; Internal use only
      </p>
    </div>
  )
}

// ── Full admin page ────────────────────────────────────────────────────────

export default function AdminPage() {
  const [token,  setToken]  = useState(() => sessionStorage.getItem(SESSION_KEY) ?? '')
  const [authed, setAuthed] = useState(false)

  useEffect(() => { if (token) setAuthed(true) }, [])

  function handleAuthenticated(t) { setToken(t); setAuthed(true) }

  function handleLogout() {
    sessionStorage.removeItem(SESSION_KEY)
    setToken(''); setAuthed(false)
  }

  if (!authed) return <AuthGate onAuthenticated={handleAuthenticated} />

  return (
    <div className="adm-page">
      <header className="adm-topbar">
        <div className="adm-topbar-brand">
          <BrandMark size={28} />
          <span className="adm-topbar-product">Rule Intelligence</span>
          <span className="adm-topbar-sep" />
          <span className="adm-chip">Admin</span>
        </div>
        <div className="adm-topbar-actions">
          <a href="/" className="adm-btn"><ArrowLeftIcon /> Back to app</a>
          <button className="adm-btn adm-btn-danger" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>
      <AdminDashboard token={token} onRefresh={handleLogout} />
    </div>
  )
}
