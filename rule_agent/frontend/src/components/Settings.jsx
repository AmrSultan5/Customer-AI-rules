import { useState, useEffect, useCallback, useRef } from 'react'
import { getKB, enhancePrompt, saveKBPrompt } from '../api.js'
import { notify } from '../utils/toast.js'
import KbDropdown from './KbDropdown.jsx'
import { ConfirmDialog } from './Dialog.jsx'

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

const UploadCloudIcon = () => (
  <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
    <path d="M6.7 15.6a3.6 3.6 0 0 1-.6-7.15A4.6 4.6 0 0 1 15 6.5a3.85 3.85 0 0 1 .5 9.1H6.7Z"
      stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/>
    <path d="M11 9.3v6.1M8.5 11.6 11 9.1l2.5 2.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const AttachIcon = () => (
  <svg width="12" height="12" viewBox="0 0 15 15" fill="none" aria-hidden="true">
    <path d="M10.7 4.1 5.6 9.2a2 2 0 1 0 2.8 2.8l4.6-4.6a3.3 3.3 0 1 0-4.7-4.7L3.6 7.4"
      stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const XIcon = () => (
  <svg width="9" height="9" viewBox="0 0 10 10" fill="none" aria-hidden="true">
    <path d="M1.3 1.3 8.7 8.7M8.7 1.3 1.3 8.7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
  </svg>
)

// Kept in sync with the backend's accepted-upload set: documents/text/code +
// office formats. Images/audio/video/archives are rejected server-side.
const KB_FILE_ACCEPT =
  '.md,.txt,.rst,.csv,.json,.yaml,.yml,.html,.xml,.log,.pdf,.xlsx,.xls,.docx,.pptx,.py,.ts,.tsx,.js,.jsx,.css,.sql'

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Push a toast summarizing an upload — surfaces accepted/rejected counts and reasons. */
function summarizeUpload(kbName, results) {
  const label = kbName ? `‘${kbName}’` : 'the knowledge base'
  const accepted = results.filter(r => r.accepted)
  const rejected = results.filter(r => !r.accepted)
  if (!accepted.length && !rejected.length) return

  const reasonList = rejected.map(r => `${r.filename}${r.reason ? ` (${r.reason})` : ''}`).join(', ')
  let message
  if (accepted.length && !rejected.length) {
    message = `Added ${accepted.length} file${accepted.length === 1 ? '' : 's'} to ${label}.`
  } else if (accepted.length && rejected.length) {
    message = `Added ${accepted.length} file${accepted.length === 1 ? '' : 's'} to ${label} ` +
      `(${rejected.length} rejected: ${reasonList}).`
  } else {
    message = `Couldn’t add any files to ${label} — ${rejected.length} rejected: ${reasonList}.`
  }
  notify({ type: accepted.length ? 'success' : 'error', message })
}

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
  onUploadFiles,
  onUpdateGlobs,
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

  // ── Per-row include-globs editor ────────────────────────────────────────
  const [editingGlobsId, setEditingGlobsId] = useState(null)
  const [globsDraft, setGlobsDraft] = useState('')
  const [globsSubmittingId, setGlobsSubmittingId] = useState(null)
  const [globsError, setGlobsError] = useState('')
  const [confirmGlobs, setConfirmGlobs] = useState(null) // { id, value, name }

  // ── Add-form file picker (files-only or files-alongside-a-repo KB) ────────
  const [formFiles, setFormFiles] = useState([])
  const [dragOver, setDragOver] = useState(false)
  const formFileInputRef = useRef(null)

  function addFormFiles(newFiles) {
    if (!newFiles.length) return
    setFormFiles(prev => {
      const seen = new Set(prev.map(f => `${f.name}:${f.size}`))
      const merged = [...prev]
      newFiles.forEach(f => {
        const key = `${f.name}:${f.size}`
        if (!seen.has(key)) { merged.push(f); seen.add(key) }
      })
      return merged
    })
  }

  function handleFormFileInput(e) {
    addFormFiles(Array.from(e.target.files || []))
    e.target.value = ''
  }

  function handleFormDrop(e) {
    e.preventDefault()
    setDragOver(false)
    addFormFiles(Array.from(e.dataTransfer?.files || []))
  }

  function removeFormFile(idx) {
    setFormFiles(prev => prev.filter((_, i) => i !== idx))
  }

  // ── Per-row "Add files" (upload into an existing KB) ───────────────────────
  const rowFileInputRef = useRef(null)
  const [uploadTargetId, setUploadTargetId] = useState(null)
  const [rowUploading, setRowUploading] = useState({})

  function triggerRowUpload(id) {
    setUploadTargetId(id)
    rowFileInputRef.current?.click()
  }

  async function handleRowFilesSelected(e) {
    const files = Array.from(e.target.files || [])
    const id = uploadTargetId
    e.target.value = ''
    if (!files.length || !id) return
    setRowUploading(u => ({ ...u, [id]: true }))
    setReposError('')
    try {
      const res = await onUploadFiles(id, files)
      const kbName = res.repo?.name ?? repos.find(r => r.id === id)?.name ?? ''
      summarizeUpload(kbName, res.results ?? [])
    } catch {
      setReposError('Could not upload files. Please try again.')
    } finally {
      setRowUploading(u => { const n = { ...u }; delete n[id]; return n })
    }
  }

  async function handleAddRepo(e) {
    e.preventDefault()
    setFormError('')
    const name = formName.trim()
    const gitUrl = formGitUrl.trim()
    if (!name) {
      setFormError('Name is required.')
      return
    }
    if (!gitUrl && formFiles.length === 0) {
      setFormError('Provide a Git URL, add files, or both.')
      return
    }
    if (gitUrl && formVisibility === 'private' && !formToken.trim()) {
      setFormError('A personal access token is required for private repositories.')
      return
    }
    setSubmitting(true)
    try {
      const repo = await onAddRepo({
        name,
        ...(gitUrl ? {
          git_url: gitUrl,
          git_ref: formGitRef.trim() || undefined,
          include_globs: formGlobs.trim() || undefined,
          visibility: formVisibility,
          auth_token: formVisibility === 'private' ? formToken.trim() : undefined,
        } : {}),
      })
      if (formFiles.length > 0) {
        const targetId = repo?.id ?? repo?.repo?.id
        if (targetId) {
          const res = await onUploadFiles(targetId, formFiles)
          summarizeUpload(res.repo?.name ?? name, res.results ?? [])
        }
      }
      setFormName('')
      setFormGitUrl('')
      setFormGitRef('')
      setFormToken('')
      setFormVisibility('public')
      setFormGlobs('')
      setAdvancedOpen(false)
      setFormFiles([])
    } catch {
      setFormError('Could not add the knowledge base. Please check the details and try again.')
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

  function startEditGlobs(repo) {
    setEditingGlobsId(repo.id)
    setGlobsDraft(repo.include_globs || '')
    setGlobsError('')
  }

  function cancelEditGlobs() {
    setEditingGlobsId(null)
    setGlobsDraft('')
    setGlobsError('')
  }

  function requestSaveGlobs(repo) {
    setGlobsError('')
    setConfirmGlobs({ id: repo.id, value: globsDraft.trim(), name: repo.name })
  }

  async function confirmSaveGlobs() {
    if (!confirmGlobs) return
    const { id, value } = confirmGlobs
    setConfirmGlobs(null)
    setGlobsSubmittingId(id)
    setGlobsError('')
    try {
      await onUpdateGlobs(id, value || null)
      setEditingGlobsId(null)
      setGlobsDraft('')
    } catch {
      setGlobsError('Could not update the file filters. Please try again.')
    } finally {
      setGlobsSubmittingId(null)
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
    <>
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card settings-card" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Settings</h3>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        {showKbChooser && (
          <section className="settings-section">
            <h4 className="settings-section-title">Active knowledge base</h4>
            <KbDropdown
              className="kb-dropdown--block"
              knowledgeBases={knowledgeBases}
              value={activeKbId}
              onChange={onSelectKb}
              ariaLabel="Active knowledge base"
            />
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
            Point the assistant at a Git repository, upload files directly, or both — either
            creates a new knowledge base. Ingestion runs in the background — this list refreshes
            on its own while a KB is queued or ingesting.
          </p>

          {reposLoading && repos.length === 0 && (
            <p className="modal-hint">Loading repositories…</p>
          )}
          {reposLoadError && <p className="settings-error">{reposLoadError}</p>}
          {reposError && <p className="settings-error">{reposError}</p>}

          {/* Hidden input shared by every row's "Add files" button — the target
              KB id is tracked in state (set right before the click it triggers). */}
          <input
            ref={rowFileInputRef}
            type="file"
            multiple
            accept={KB_FILE_ACCEPT}
            style={{ display: 'none' }}
            onChange={handleRowFilesSelected}
          />

          {repos.length > 0 && (
            <ul className="repo-list">
              {repos.map(repo => {
                const isPending = repo.status === 'queued' || repo.status === 'ingesting'
                const busy = rowBusy[repo.id]
                const uploading = !!rowUploading[repo.id]
                const actionsDisabled = !!busy || isPending || uploading
                return (
                <li className={`repo-row${isPending ? ' repo-row-pending' : ''}`} key={repo.id}>
                  <div className="repo-row-main">
                    <div className="repo-row-info">
                      <span className="repo-row-name">{repo.name}</span>
                      <span className="repo-row-url">{repo.git_url || 'Files only — no Git source'}</span>
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

                  {repo.git_url && (
                    <div className="repo-row-globs">
                      {editingGlobsId === repo.id ? (
                        <div className="repo-globs-edit">
                          <input
                            className="settings-input repo-globs-input"
                            value={globsDraft}
                            onChange={e => setGlobsDraft(e.target.value)}
                            placeholder="Markdown only (**/*.md)"
                            disabled={globsSubmittingId === repo.id}
                          />
                          <div className="repo-globs-edit-actions">
                            <button
                              type="button"
                              className="btn-secondary"
                              onClick={() => requestSaveGlobs(repo)}
                              disabled={globsSubmittingId === repo.id}
                            >
                              {globsSubmittingId === repo.id && <span className="btn-spinner" aria-hidden="true" />}
                              {globsSubmittingId === repo.id ? 'Saving…' : 'Save'}
                            </button>
                            <button
                              type="button"
                              className="btn-secondary"
                              onClick={cancelEditGlobs}
                              disabled={globsSubmittingId === repo.id}
                            >
                              Cancel
                            </button>
                          </div>
                          {globsError && <p className="settings-error repo-globs-error">{globsError}</p>}
                        </div>
                      ) : (
                        <div className="repo-globs-display">
                          <span className="repo-globs-label">Include globs</span>
                          <span className="repo-globs-value">
                            {repo.include_globs || 'Markdown only (**/*.md)'}
                          </span>
                          <button
                            type="button"
                            className="repo-globs-edit-btn"
                            onClick={() => startEditGlobs(repo)}
                            disabled={actionsDisabled}
                            title="Edit include-globs for this repository"
                          >
                            Edit
                          </button>
                        </div>
                      )}
                    </div>
                  )}

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
                      className="btn-secondary repo-row-add-files"
                      onClick={() => triggerRowUpload(repo.id)}
                      disabled={actionsDisabled}
                      title="Upload files into this knowledge base"
                    >
                      {uploading ? <span className="btn-spinner" aria-hidden="true" /> : <AttachIcon />}
                      {uploading ? 'Uploading…' : 'Add files'}
                    </button>
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

            <label className="settings-label">Git URL (optional)</label>
            <input
              className="settings-input"
              value={formGitUrl}
              onChange={e => setFormGitUrl(e.target.value)}
              placeholder="https://github.com/org/repo.git — leave blank for a files-only KB"
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

            <div className="repo-form-divider">or add files</div>

            <div
              className={`repo-dropzone${dragOver ? ' dragover' : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => !submitting && formFileInputRef.current?.click()}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  if (!submitting) formFileInputRef.current?.click()
                }
              }}
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleFormDrop}
            >
              <span className="repo-dropzone-icon"><UploadCloudIcon /></span>
              <span className="repo-dropzone-title">Drop files here, or click to browse</span>
              <span className="repo-dropzone-hint">Docs, text, code, PDF, Excel, Word, PowerPoint</span>
              <input
                ref={formFileInputRef}
                type="file"
                multiple
                accept={KB_FILE_ACCEPT}
                style={{ display: 'none' }}
                onChange={handleFormFileInput}
                disabled={submitting}
              />
            </div>

            {formFiles.length > 0 && (
              <ul className="repo-file-chip-list">
                {formFiles.map((f, idx) => (
                  <li className="repo-file-chip" key={`${f.name}-${f.size}-${idx}`}>
                    <span className="repo-file-chip-name">{f.name}</span>
                    <span className="repo-file-chip-size">{formatBytes(f.size)}</span>
                    <button
                      type="button"
                      className="repo-file-chip-remove"
                      onClick={() => removeFormFile(idx)}
                      disabled={submitting}
                      aria-label={`Remove ${f.name}`}
                    >
                      <XIcon />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {formError && <p className="settings-error">{formError}</p>}

            <div className="repo-add-actions">
              <button className="btn-primary" type="submit" disabled={submitting}>
                {submitting ? 'Adding…' : 'Add knowledge base'}
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
    {confirmGlobs && (
      <ConfirmDialog
        title="Update file filters?"
        message={
          <>
            This re-scans the repository, re-embeds files that match the new patterns, and{' '}
            <strong>removes files that no longer match</strong>. Your uploaded files are not affected.
          </>
        }
        confirmLabel="Update & re-ingest"
        onConfirm={confirmSaveGlobs}
        onCancel={() => setConfirmGlobs(null)}
      />
    )}
    </>
  )
}
