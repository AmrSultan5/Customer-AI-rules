import { Component } from 'react'

/**
 * Top-level React Error Boundary.
 * Catches render errors in any child tree and shows a styled fallback
 * instead of a blank white screen.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, errorMessage: '' }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, errorMessage: error?.message ?? String(error) }
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary] Uncaught render error:', error, info)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    const isDev = import.meta.env.DEV

    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg-base, #0f1117)',
        color: 'var(--text-primary, #e2e8f0)',
        fontFamily: 'Inter, system-ui, sans-serif',
        padding: '2rem',
        gap: '1.5rem',
        textAlign: 'center',
      }}>
        <div style={{
          width: 56,
          height: 56,
          borderRadius: '50%',
          background: 'rgba(239,68,68,0.12)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 28,
        }}>⚠</div>

        <div>
          <h1 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600 }}>
            Something went wrong
          </h1>
          <p style={{ margin: '0.5rem 0 0', color: 'var(--text-muted, #94a3b8)', fontSize: '0.9rem' }}>
            An unexpected error occurred. Reload the page to continue.
          </p>
        </div>

        {isDev && this.state.errorMessage && (
          <pre style={{
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.2)',
            borderRadius: 8,
            padding: '0.75rem 1rem',
            fontSize: '0.78rem',
            color: '#fca5a5',
            maxWidth: 600,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            textAlign: 'left',
          }}>
            {this.state.errorMessage}
          </pre>
        )}

        <button
          onClick={() => window.location.reload()}
          style={{
            padding: '0.6rem 1.5rem',
            borderRadius: 8,
            border: '1px solid rgba(255,255,255,0.12)',
            background: 'rgba(255,255,255,0.06)',
            color: 'var(--text-primary, #e2e8f0)',
            fontSize: '0.875rem',
            cursor: 'pointer',
            transition: 'background 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.1)'}
          onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.06)'}
        >
          Reload page
        </button>
      </div>
    )
  }
}
