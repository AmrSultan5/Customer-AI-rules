import { useState, useEffect } from 'react'
import AdminDashboard from './AdminDashboard.jsx'
import { apiFetch } from '../api.js'

const SESSION_KEY = 'rule_agent_admin_token'

const LogoMark = () => (
  <div style={{
    width: 36, height: 36, borderRadius: '50%',
    background: '#E8000D', display: 'flex', alignItems: 'center', justifyContent: 'center',
    boxShadow: '0 2px 16px rgba(232,0,13,0.35)',
  }}>
    <span style={{ fontFamily: 'DM Serif Display, serif', fontSize: '18px', color: '#fff', lineHeight: 1 }}>R</span>
  </div>
)

const HomeIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <path d="M1.5 6.5L6.5 2l5 4.5V11a1 1 0 0 1-1 1h-2.5V8.5h-3V12H2.5a1 1 0 0 1-1-1V6.5z"
      stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/>
  </svg>
)

const UserIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <circle cx="7" cy="4.5" r="2.5" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M2 12c0-2.76 2.24-5 5-5s5 2.24 5 5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
  </svg>
)

const LockIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="2.5" y="6" width="9" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M4.5 6V4.5a2.5 2.5 0 0 1 5 0V6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    <circle cx="7" cy="9.5" r="1" fill="currentColor"/>
  </svg>
)

// ── Auth gate ──────────────────────────────────────────────────────────────

function AuthGate({ onAuthenticated }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
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
      <div className="adm-gate-card">
        <div className="adm-gate-logo"><LogoMark /></div>
        <h1 className="adm-gate-title">Admin Sign In</h1>
        <p className="adm-gate-sub">Sign in to access the Rule Health Dashboard.</p>

        <form className="adm-gate-form" onSubmit={attempt}>
          {/* Username */}
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

          {/* Password */}
          <div className="adm-field">
            <label className="adm-field-label" htmlFor="adm-password">Password</label>
            <div className={`adm-field-wrap${hasError ? ' adm-field-error' : ''}`}>
              <span className="adm-field-icon"><LockIcon /></span>
              <input
                id="adm-password"
                className="adm-field-input"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={e => { setPassword(e.target.value); setError('') }}
                autoComplete="current-password"
                disabled={busy}
              />
            </div>
          </div>

          {error && <p className="adm-gate-error">{error}</p>}

          <button
            className="adm-gate-submit"
            type="submit"
            disabled={busy || !username.trim() || !password}
          >
            {busy ? 'Signing in…' : 'Sign In'}
          </button>
        </form>

        <a href="/" className="adm-gate-back"><HomeIcon /> Back to Rule Intelligence</a>
      </div>

      <p className="adm-gate-footer">
        Rule Intelligence &middot; Coca-Cola HBC &middot; Admin Portal
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
          <LogoMark />
          <span className="adm-topbar-product">Rule Intelligence</span>
          <span className="adm-topbar-sep" />
          <span className="adm-topbar-badge">ADMIN</span>
        </div>
        <div className="adm-topbar-actions">
          <a href="/" className="adm-topbar-btn"><HomeIcon /> Back to App</a>
          <button className="adm-topbar-btn adm-topbar-btn-logout" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>
      <AdminDashboard token={token} onRefresh={handleLogout} />
    </div>
  )
}
