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

const WarningIcon = () => (
  <svg width="14" height="14" viewBox="0 0 15 15" fill="none" aria-hidden="true">
    <path d="M7.5 1.6 13.8 12.4a1 1 0 0 1-.87 1.5H2.07a1 1 0 0 1-.87-1.5L7.5 1.6z"
      stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
    <path d="M7.5 6v2.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    <circle cx="7.5" cy="11" r="0.85" fill="currentColor"/>
  </svg>
)

/**
 * Settings modal: active-KB chooser (only when the switcher is enabled),
 * the per-KB custom prompt editor (draft → Enhance with AI → review → Save),
 * and the light/dark theme toggle.
 */
const REPO_STATUS_LABELS = {
  queued: 'Queued',
  ingesting: 'Ingesting…',
  ready: 'Ready',
  error: 'Error',
}

const RepoStatusPill = ({ status }) => (
  <span className={`repo-status-pill repo-status-${status}`}>
    {REPO_STATUS_LABELS[status] ?? status}
  </span>
)

export default function Settings({
  knowledgeBases,
  activeKbId,
  switcherEnabled,
  onSelectKb,
  theme,
  onSetTheme,
  onClose,
  repos,
  reposLoading,
  reposLoadError,
  onReloadRepo,
  onDeleteRepo,
  onAddRepo,
}) {
  const [draft, setDraft] = useState('')
  const [enhanced, setEnhanced] = useState('')
  const [loading, setLoading] = useState(false)
  const [enhancing, setEnhancing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  // Repo list/polling now lives in App (so it keeps running while this
  // modal is closed) — `repos`/`reposLoading`/`reposLoadError` are props.
  // Only per-row/per-form action errors stay local here.
  const [reposError, setReposError] = useState('')

  const [formName, setFormName] = useState('')
  const [formGitUrl, setFormGitUrl] = useState('')
  const [formGitRef, setFormGitRef] = useState('')
  const [formVisibility, setFormVisibility] = useState('public')
  const [formToken, setFormToken] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [formGlobs, setFormGlobs] = useState('')
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [rowBusy, setRowBusy] = useState({})
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)

  async function handleAddRepo(e) {
    e.preventDefault()
    setFormError('')
    if (!formName.trim() || !formGitUrl.trim()) {
      setFormError('Name and Git URL are required.')
      return
    }
    if (formVisibility === 'private' && !formToken.trim()) {
      setFormError('A personal access token is required for private repositories.')
      return
    }
    setSubmitting(true)
    try {
      await onAddRepo({
        name: formName.trim(),
        git_url: formGitUrl.trim(),
        git_ref: formGitRef.trim() || undefined,
        include_globs: formGlobs.trim() || undefined,
        visibility: formVisibility,
        auth_token: formVisibility === 'private' ? formToken.trim() : undefined,
      })
      setFormName('')
      setFormGitUrl('')
      setFormGitRef('')
      setFormToken('')
      setFormVisibility('public')
      setFormGlobs('')
      setAdvancedOpen(false)
    } catch {
      setFormError('Could not add the repository. Please check the details and try again.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleReload(id) {
    setRowBusy(b => ({ ...b, [id]: 'resync' }))
    setReposError('')
    try {
      await onReloadRepo(id)
    } catch {
      setReposError('Could not reload that repository. Please try again.')
    } finally {
      setRowBusy(b => { const n = { ...b }; delete n[id]; return n })
    }
  }

  async function handleDelete(id) {
    setRowBusy(b => ({ ...b, [id]: 'delete' }))
    setReposError('')
    try {
      await onDeleteRepo(id)
      setConfirmDeleteId(null)
    } catch {
      setReposError('Could not delete that repository. Please try again.')
    } finally {
      setRowBusy(b => { const n = { ...b }; delete n[id]; return n })
    }
  }

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
              onChange={e => {
                const kb = knowledgeBases.find(k => k.id === e.target.value)
                if (kb && !kb.selectable) return // guard: shouldn't fire for a disabled option
                onSelectKb(e.target.value)
              }}
            >
              {knowledgeBases.map(kb => (
                <option key={kb.id} value={kb.id} disabled={!kb.selectable}>
                  {kb.selectable ? kb.name : `${kb.name} (updating…)`}
                </option>
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
          <h4 className="settings-section-title">Knowledge repositories</h4>
          <p className="modal-hint">
            Point the assistant at a Git repository to ingest its documents into a new
            knowledge base. Ingestion runs in the background — this list refreshes on its own
            while a repo is queued or ingesting.
          </p>

          {reposLoading && repos.length === 0 && (
            <p className="modal-hint">Loading repositories…</p>
          )}
          {reposLoadError && <p className="settings-error">{reposLoadError}</p>}
          {reposError && <p className="settings-error">{reposError}</p>}

          {repos.length > 0 && (
            <ul className="repo-list">
              {repos.map(repo => {
                const isPending = repo.status === 'queued' || repo.status === 'ingesting'
                const busy = rowBusy[repo.id]
                const actionsDisabled = !!busy || isPending
                return (
                <li className={`repo-row${isPending ? ' repo-row-pending' : ''}`} key={repo.id}>
                  <div className="repo-row-main">
                    <div className="repo-row-info">
                      <span className="repo-row-name">{repo.name}</span>
                      <span className="repo-row-url">{repo.git_url}</span>
                    </div>
                    <RepoStatusPill status={repo.status} />
                  </div>

                  <div className="repo-row-meta">
                    {(repo.documents != null || repo.chunks != null) && (
                      <span className="repo-row-counts">
                        {repo.documents != null && `${repo.documents} docs`}
                        {repo.documents != null && repo.chunks != null && ' · '}
                        {repo.chunks != null && `${repo.chunks} chunks`}
                      </span>
                    )}
                    {repo.status === 'ready' && (
                      <span className="repo-row-ready-note">Ready — pick it in the KB switcher.</span>
                    )}
                  </div>

                  {repo.status === 'error' && (
                    <div className="repo-row-error" role="alert">
                      <span className="repo-row-error-icon" aria-hidden="true"><WarningIcon /></span>
                      <div className="repo-row-error-body">
                        <p className="repo-row-error-message">
                          {repo.status_detail || 'The last update failed for an unknown reason.'}
                        </p>
                        {((repo.chunks ?? 0) > 0 || (repo.documents ?? 0) > 0) && (
                          <p className="repo-row-error-note">
                            Still serving the previous version — Reload to try again.
                          </p>
                        )}
                      </div>
                    </div>
                  )}

                  <div className="repo-row-actions">
                    <button
                      className="btn-secondary"
                      onClick={() => handleReload(repo.id)}
                      disabled={actionsDisabled}
                      title="Pull the latest and re-embed"
                    >
                      {(busy === 'resync' || isPending) && <span className="btn-spinner" aria-hidden="true" />}
                      {busy === 'resync' ? 'Reloading…' : isPending ? 'Reloading…' : 'Reload'}
                    </button>
                    {confirmDeleteId === repo.id ? (
                      <>
                        <span className="repo-confirm-text">Delete this repo?</span>
                        <button
                          className="btn-secondary repo-danger"
                          onClick={() => handleDelete(repo.id)}
                          disabled={actionsDisabled}
                        >
                          {busy === 'delete' && <span className="btn-spinner" aria-hidden="true" />}
                          {busy === 'delete' ? 'Deleting…' : 'Confirm'}
                        </button>
                        <button className="btn-secondary" onClick={() => setConfirmDeleteId(null)}>
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        className="btn-secondary repo-danger"
                        onClick={() => setConfirmDeleteId(repo.id)}
                        disabled={actionsDisabled}
                        title="Delete this knowledge repository"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </li>
                )
              })}
            </ul>
          )}

          <form className="repo-add-form" onSubmit={handleAddRepo}>
            <label className="settings-label">Name</label>
            <input
              className="settings-input"
              value={formName}
              onChange={e => setFormName(e.target.value)}
              placeholder="e.g. Internal Docs"
              disabled={submitting}
            />

            <label className="settings-label">Git URL</label>
            <input
              className="settings-input"
              value={formGitUrl}
              onChange={e => setFormGitUrl(e.target.value)}
              placeholder="https://github.com/org/repo.git"
              disabled={submitting}
            />

            <label className="settings-label">Branch / ref (optional)</label>
            <input
              className="settings-input"
              value={formGitRef}
              onChange={e => setFormGitRef(e.target.value)}
              placeholder="main"
              disabled={submitting}
            />

            <label className="settings-label">Visibility</label>
            <div className="repo-visibility-toggle">
              <button
                type="button"
                className={`settings-theme-btn${formVisibility === 'public' ? ' active' : ''}`}
                onClick={() => setFormVisibility('public')}
                disabled={submitting}
              >
                Public
              </button>
              <button
                type="button"
                className={`settings-theme-btn${formVisibility === 'private' ? ' active' : ''}`}
                onClick={() => setFormVisibility('private')}
                disabled={submitting}
              >
                Private
              </button>
            </div>

            {formVisibility === 'private' && (
              <>
                <label className="settings-label">Personal access token</label>
                <input
                  type="password"
                  className="settings-input"
                  value={formToken}
                  onChange={e => setFormToken(e.target.value)}
                  placeholder="ghp_…"
                  disabled={submitting}
                  autoComplete="off"
                />
              </>
            )}

            <button
              type="button"
              className="repo-advanced-toggle"
              onClick={() => setAdvancedOpen(v => !v)}
            >
              {advancedOpen ? 'Hide advanced ▲' : 'Advanced ▾'}
            </button>
            {advancedOpen && (
              <>
                <label className="settings-label">Include globs (comma-separated)</label>
                <input
                  className="settings-input"
                  value={formGlobs}
                  onChange={e => setFormGlobs(e.target.value)}
                  placeholder="docs/**/*.md, *.mdx"
                  disabled={submitting}
                />
              </>
            )}

            {formError && <p className="settings-error">{formError}</p>}

            <div className="repo-add-actions">
              <button className="btn-primary" type="submit" disabled={submitting}>
                {submitting ? 'Adding…' : 'Add repository'}
              </button>
            </div>
          </form>
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
