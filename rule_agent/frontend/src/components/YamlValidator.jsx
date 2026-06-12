import { useState, useEffect, useRef } from 'react'
import { apiPost } from '../api.js'

const MAX_CHARS = 600_000

const CheckIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <circle cx="6.5" cy="6.5" r="5.5" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M4 6.5l1.8 1.8L9 5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const ErrorIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <circle cx="6.5" cy="6.5" r="5.5" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M4.5 4.5l4 4M8.5 4.5l-4 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
  </svg>
)

const WarnIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <path d="M6.5 1.5L12 11H1l5.5-9.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/>
    <path d="M6.5 5v2.8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    <circle cx="6.5" cy="9.4" r="0.7" fill="currentColor"/>
  </svg>
)

/**
 * Modal for the engineer paste-back check: paste an edited pipeline YAML,
 * validate its structure and references against the repository indexes
 * before committing.
 */
export default function YamlValidator({ onClose }) {
  const [yamlText, setYamlText] = useState('')
  const [result, setResult]     = useState(null)
  const [busy, setBusy]         = useState(false)
  const [error, setError]       = useState('')
  const textareaRef = useRef(null)

  useEffect(() => {
    textareaRef.current?.focus()
    function onEsc(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onEsc)
    return () => window.removeEventListener('keydown', onEsc)
  }, [onClose])

  async function validate() {
    const text = yamlText.trim()
    if (!text || busy) return
    setBusy(true); setError(''); setResult(null)
    try {
      const res = await apiPost('/validate/yaml', { yaml_text: text })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setResult(await res.json())
    } catch (e) {
      setError(`Could not validate: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  const summary = result?.summary

  return (
    <div className="yv-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="Validate pipeline YAML">
      <div className="yv-modal" onClick={e => e.stopPropagation()}>
        <div className="yv-header">
          <span className="yv-title">Validate pipeline YAML</span>
          <button className="yv-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <p className="yv-hint">
          Paste your edited <code>golden/</code> pipeline file. Structure, custom operation
          paths, rule IDs, and source tables are checked against the repository — before you commit.
        </p>

        <textarea
          ref={textareaRef}
          className="yv-textarea"
          value={yamlText}
          maxLength={MAX_CHARS}
          onChange={e => { setYamlText(e.target.value); setResult(null); setError('') }}
          placeholder={'transform:\n  name: …\n  operations:\n    - kind: read_dataio\n      …'}
          spellCheck={false}
        />

        <div className="yv-actions">
          <button className="yv-validate-btn" onClick={validate} disabled={busy || !yamlText.trim()}>
            {busy ? 'Validating…' : 'Validate'}
          </button>
          {result && (
            <span className={`yv-verdict ${result.valid ? 'ok' : 'fail'}`}>
              {result.valid ? <CheckIcon /> : <ErrorIcon />}
              {result.valid
                ? (result.warnings.length ? 'Valid, with warnings' : 'Valid')
                : 'Invalid'}
            </span>
          )}
        </div>

        {error && <p className="yv-request-error">{error}</p>}

        {result && (
          <div className="yv-results">
            {result.errors.map((msg, i) => (
              <div key={`e${i}`} className="yv-item yv-error"><ErrorIcon /><span>{msg}</span></div>
            ))}
            {result.warnings.map((msg, i) => (
              <div key={`w${i}`} className="yv-item yv-warning"><WarnIcon /><span>{msg}</span></div>
            ))}
            {result.valid && !result.warnings.length && (
              <div className="yv-item yv-ok">
                <CheckIcon />
                <span>No issues found — structure and references all resolve.</span>
              </div>
            )}
            {summary && (summary.transform_name || summary.operation_count > 0) && (
              <div className="yv-summary">
                {summary.transform_name && <span className="yv-chip">transform: {summary.transform_name}</span>}
                <span className="yv-chip">{summary.operation_count} operations</span>
                {summary.rule_ids.length > 0 && <span className="yv-chip">rules: {summary.rule_ids.join(', ')}</span>}
                {summary.custom_ops.length > 0 && <span className="yv-chip">custom ops: {summary.custom_ops.join(', ')}</span>}
                {summary.sources.length > 0 && <span className="yv-chip">sources: {summary.sources.join(', ')}</span>}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
