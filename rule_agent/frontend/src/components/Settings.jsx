import { useState, useEffect, useCallback } from 'react'
import { getKB, enhancePrompt, saveKBPrompt } from '../api.js'

const SunIcon = () => (
  <svg width="13" height="13" viewBox="0 0 15 15" fill="none" aria-hidden="true">
    <circle cx="7.5" cy="7.5" r="2.8" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M7.5 1v1.4M7.5 12.6V14M14 7.5h-1.4M2.4 7.5H1M11.9 3.1l-1 1M4.1 10.9l-1 1M11.9 11.9l-1-1M4.1 4.1l-1-1"
      stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
  </svg>
)

const MoonIcon = () => (
  <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M12 9.3A6 6 0 0 1 4.7 2a5.5 5.5 0 1 0 7.3 7.3z"
      stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

/**
 * Settings modal: active-KB chooser (only when the switcher is enabled),
 * the per-KB custom prompt editor (draft → Enhance with AI → review → Save),
 * and the light/dark theme toggle.
 */
export default function Settings({
  knowledgeBases,
  activeKbId,
  switcherEnabled,
  onSelectKb,
  theme,
  onSetTheme,
  onClose,
}) {
  const [draft, setDraft] = useState('')
  const [enhanced, setEnhanced] = useState('')
  const [loading, setLoading] = useState(false)
  const [enhancing, setEnhancing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  const activeKb = knowledgeBases.find(k => k.id === activeKbId) ?? null
  const showKbChooser = switcherEnabled && knowledgeBases.length > 1

  const loadPrompt = useCallback(async (kbId) => {
    if (!kbId) return
    setLoading(true)
    setError('')
    setSaved(false)
    try {
      const detail = await getKB(kbId)
      setDraft(detail.custom_prompt ?? '')
      setEnhanced(detail.enhanced_prompt ?? '')
    } catch {
      setError('Could not load the current prompt for this knowledge base.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadPrompt(activeKbId) }, [activeKbId, loadPrompt])

  async function handleEnhance() {
    if (!draft.trim() || !activeKbId) return
    setEnhancing(true)
    setError('')
    setSaved(false)
    try {
      const res = await enhancePrompt(activeKbId, draft)
      setEnhanced(res.enhanced ?? '')
    } catch {
      setError('The AI enhancement failed. Please try again.')
    } finally {
      setEnhancing(false)
    }
  }

  async function handleSave() {
    if (!activeKbId) return
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      await saveKBPrompt(activeKbId, { custom_prompt: draft, enhanced_prompt: enhanced })
      setSaved(true)
    } catch {
      setError('Could not save the prompt. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card settings-card" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Settings</h3>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        {showKbChooser && (
          <section className="settings-section">
            <h4 className="settings-section-title">Active knowledge base</h4>
            <select
              className="settings-select"
              value={activeKbId ?? ''}
              onChange={e => onSelectKb(e.target.value)}
            >
              {knowledgeBases.map(kb => (
                <option key={kb.id} value={kb.id}>{kb.name}</option>
              ))}
            </select>
            {activeKb?.description && <p className="modal-hint">{activeKb.description}</p>}
          </section>
        )}

        <section className="settings-section">
          <h4 className="settings-section-title">
            Custom prompt{activeKb ? ` — ${activeKb.name}` : ''}
          </h4>
          <p className="modal-hint">
            Rough instructions for how the assistant should behave on this knowledge base.
            Enhance with AI to turn your draft into a clear prompt fragment, review/edit it,
            then save. It is injected into every chat on this knowledge base.
          </p>

          <label className="settings-label">Draft</label>
          <textarea
            className="instructions-textarea"
            value={draft}
            onChange={e => { setDraft(e.target.value); setSaved(false) }}
            rows={4}
            placeholder="e.g. Always cite the source table, and keep answers under 200 words…"
            disabled={loading}
          />

          <div className="settings-enhance-row">
            <button
              className="btn-secondary"
              onClick={handleEnhance}
              disabled={loading || enhancing || !draft.trim()}
            >
              {enhancing ? 'Enhancing…' : 'Enhance with AI'}
            </button>
          </div>

          <label className="settings-label">Enhanced prompt (reviewable — this is what gets saved)</label>
          <textarea
            className="instructions-textarea"
            value={enhanced}
            onChange={e => { setEnhanced(e.target.value); setSaved(false) }}
            rows={6}
            placeholder="Enhanced prompt will appear here for review — or write it directly…"
            disabled={loading}
          />

          {error && <p className="settings-error">{error}</p>}
          {saved && !error && <p className="settings-saved">Saved.</p>}
        </section>

        <section className="settings-section">
          <h4 className="settings-section-title">Theme</h4>
          <div className="settings-theme-toggle">
            <button
              className={`settings-theme-btn${theme === 'light' ? ' active' : ''}`}
              onClick={() => onSetTheme('light')}
            >
              <SunIcon /> Light
            </button>
            <button
              className={`settings-theme-btn${theme === 'dark' ? ' active' : ''}`}
              onClick={() => onSetTheme('dark')}
            >
              <MoonIcon /> Dark
            </button>
          </div>
        </section>

        <div className="modal-actions">
          <button className="btn-secondary" onClick={onClose}>Close</button>
          <button className="btn-primary" onClick={handleSave} disabled={loading || saving || !activeKbId}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
