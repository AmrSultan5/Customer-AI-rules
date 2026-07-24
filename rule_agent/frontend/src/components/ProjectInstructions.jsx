import { useState } from 'react'
import { updateProject } from '../api.js'
import { notifyError } from '../utils/toast.js'

/**
 * Modal editor for a project's standing-instructions string.
 * The text is prepended to every chat in the project (server-side injection).
 */
export default function ProjectInstructions({ project, onClose, onSaved }) {
  const [text, setText] = useState(project.instructions ?? '')
  const [saving, setSaving] = useState(false)

  async function save() {
    setSaving(true)
    try {
      const updated = await updateProject(project.id, { instructions: text })
      onSaved?.(updated)
      onClose?.()
    } catch {
      setSaving(false)
      notifyError('Couldn’t save the project instructions. Please try again.')
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card project-instructions" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Project instructions</h3>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <p className="modal-hint">
          These instructions are added to <strong>every chat</strong> in
          “{project.name}”. Keep them short and directive — e.g.
          “Scope answers to the Q4 dataset” or “Always cite the source document”.
        </p>
        <textarea
          className="instructions-textarea"
          value={text}
          onChange={e => setText(e.target.value)}
          rows={6}
          placeholder="Standing instructions for this project…"
          autoFocus
        />
        <div className="modal-actions">
          <button className="btn-secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
