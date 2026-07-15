import { useState, useEffect, useCallback } from 'react'
import Tooltip from './Tooltip.jsx'
import ProjectInstructions from './ProjectInstructions.jsx'
import { ConfirmDialog, RenameDialog } from './Dialog.jsx'
import {
  listProjects, createProject, deleteProject,
  listConversations, createConversation, renameConversation,
  moveConversation, deleteConversation,
} from '../api.js'

const PERSONAS = [
  { id: 'analyst', label: 'Analyst', short: 'A' },
  { id: 'engineer', label: 'Engineer', short: 'E' },
  { id: 'pm', label: 'PM', short: 'PM' },
]

const personaLabel = (id) => PERSONAS.find(p => p.id === id)?.label ?? id

// Titles are plain text in the sidebar; strip markdown formatting the title
// generator sometimes emits (and that older stored titles still contain).
// Underscores stay — rule IDs like RCCOMP_103.1 legitimately contain them.
const cleanTitle = (t) => (t ?? '').replace(/[*`#]+/g, '').trim() || 'New chat'

function PersonaPicker({ onPick, onCancel }) {
  return (
    <div className="persona-picker">
      {PERSONAS.map(p => (
        <button key={p.id} className="persona-pick-btn" onClick={() => onPick(p.id)}>
          {p.label}
        </button>
      ))}
      <button className="persona-pick-cancel" onClick={onCancel} aria-label="Cancel">×</button>
    </div>
  )
}

const ChevronRightIcon = () => (
  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
    <path d="M3.5 2L7 5L3.5 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const InstructionsIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="2" y="1.5" width="10" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.25" />
    <path d="M4.5 4.5h5M4.5 7h3M4.5 9.5h4" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
  </svg>
)

const ProjectDeleteIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M2 4h10M5 4V2.5a.5.5 0 0 1 .5-.5h3a.5.5 0 0 1 .5.5V4M3.5 4l.5 8h6l.5-8"
      stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const SwitchUserIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M9.5 3.5L12 6M12 6L9.5 8.5M12 6H5M4.5 10.5L2 8M2 8L4.5 5.5M2 8H9"
      stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const EditIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M8.5 1.5a1.2 1.2 0 0 1 1.7 1.7L3.5 9.9 1 10.5l.6-2.5 6.9-6.5z"
      stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const MoveIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <rect x="1" y="1" width="10" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
    <path d="M1 4.5h10M4.5 1v3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
)

const TrashMenuIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M1.5 3.5h9M4 3.5V2.5h4v1M3 3.5l.5 7h5l.5-7"
      stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

function ConversationRow({ conv, active, projects, onSelect, onChanged }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [dialog, setDialog] = useState(null) // null | 'rename' | 'delete'

  async function doRename(title) {
    setDialog(null)
    await renameConversation(conv.id, title)
    onChanged()
  }

  async function move(e) {
    const val = e.target.value
    const projectId = val === '' ? null : Number(val)
    await moveConversation(conv.id, projectId)
    setMenuOpen(false)
    onChanged()
  }

  async function doDelete() {
    setDialog(null)
    await deleteConversation(conv.id)
    onChanged()
  }

  return (
    <>
      <div className={`conv-row${active ? ' active' : ''}`}>
        <Tooltip content={cleanTitle(conv.title)}>
          <button className="conv-main" onClick={() => onSelect(conv)}>
            <span className={`conv-persona-badge persona-${conv.persona}`}>{personaLabel(conv.persona)}</span>
            <span className="conv-title">{cleanTitle(conv.title)}</span>
          </button>
        </Tooltip>
        <button className="conv-kebab" onClick={() => setMenuOpen(o => !o)} aria-label="Conversation actions">⋯</button>
        {menuOpen && (
          <div className="conv-menu" onMouseLeave={() => setMenuOpen(false)}>
            <button onClick={() => { setMenuOpen(false); setDialog('rename') }}>
              <EditIcon /> Rename
            </button>
            <label className="conv-menu-move">
              <MoveIcon /> Move to
              <select value={conv.project_id ?? ''} onChange={move}>
                <option value="">Chats</option>
                {projects.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </label>
            <div className="conv-menu-sep" />
            <button className="conv-menu-danger" onClick={() => { setMenuOpen(false); setDialog('delete') }}>
              <TrashMenuIcon /> Delete
            </button>
          </div>
        )}
      </div>

      {dialog === 'rename' && (
        <RenameDialog
          title="Rename conversation"
          initialValue={cleanTitle(conv.title) === 'New chat' && !conv.title ? '' : cleanTitle(conv.title)}
          placeholder="Conversation title…"
          onSave={doRename}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog === 'delete' && (
        <ConfirmDialog
          title="Delete conversation"
          message="This conversation and all its messages will be permanently deleted. This cannot be undone."
          confirmLabel="Delete"
          danger
          onConfirm={doDelete}
          onCancel={() => setDialog(null)}
        />
      )}
    </>
  )
}

export default function ConversationSidebar({
  username,
  onChangeUser,
  activeConversationId,
  onSelectConversation,
  reloadSignal,
  open = true,
}) {
  const [projects, setProjects] = useState([])
  const [conversations, setConversations] = useState([])
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [collapsed, setCollapsed] = useState({})       // projectId → bool
  const [pickerFor, setPickerFor] = useState(undefined) // 'loose' | projectId | undefined
  const [instructionsProject, setInstructionsProject] = useState(null)
  const [deleteProjectTarget, setDeleteProjectTarget] = useState(null) // project | null

  const reload = useCallback(async () => {
    if (!username) return
    try {
      const [pj, cv] = await Promise.all([listProjects(), listConversations()])
      setProjects(pj)
      setConversations(cv)
    } catch { }
  }, [username])

  useEffect(() => { reload() }, [reload, reloadSignal])

  async function addProject() {
    const name = newProjectName.trim()
    if (!name) { setNewProjectOpen(false); return }
    await createProject(name)
    setNewProjectName('')
    setNewProjectOpen(false)
    reload()
  }

  async function removeProject() {
    const p = deleteProjectTarget
    setDeleteProjectTarget(null)
    if (!p) return
    await deleteProject(p.id)
    reload()
  }

  async function startChat(persona, projectId = null) {
    setPickerFor(undefined)
    const conv = await createConversation({ persona, project_id: projectId })
    await reload()
    onSelectConversation(conv)
  }

  const looseConvs = conversations.filter(c => c.project_id == null)
  const convsByProject = (pid) => conversations.filter(c => c.project_id === pid)

  return (
    <aside className={`conv-sidebar${open ? '' : ' collapsed'}`} data-tour="conv-sidebar">
      <div className="conv-sidebar-user">
        <span className="conv-user-name" title={username}>{username}</span>
        <div className="conv-sidebar-user-actions">
          <Tooltip content="Switch user">
            <button className="conv-user-switch" onClick={onChangeUser} aria-label="Switch user">
              <SwitchUserIcon />
            </button>
          </Tooltip>
        </div>
      </div>

      <div className="conv-sidebar-actions">
        {pickerFor === 'loose' ? (
          <PersonaPicker onPick={(p) => startChat(p, null)} onCancel={() => setPickerFor(undefined)} />
        ) : (
          <button className="conv-new-btn" onClick={() => setPickerFor('loose')}>+ New chat</button>
        )}
        {newProjectOpen ? (
          <div className="conv-new-project">
            <input
              autoFocus
              value={newProjectName}
              onChange={e => setNewProjectName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') addProject(); if (e.key === 'Escape') setNewProjectOpen(false) }}
              placeholder="Project name"
            />
            <button onClick={addProject}>Add</button>
          </div>
        ) : (
          <button className="conv-new-project-btn" onClick={() => setNewProjectOpen(true)}>+ New project</button>
        )}
      </div>

      <div className="conv-sidebar-list">
        {projects.map(p => {
          const isCollapsed = collapsed[p.id]
          const convs = convsByProject(p.id)
          return (
            <div key={p.id} className="conv-project">
              <div className="conv-project-header">
                <button
                  className="conv-project-toggle"
                  onClick={() => setCollapsed(c => ({ ...c, [p.id]: !c[p.id] }))}
                >
                  <span className={`conv-caret${isCollapsed ? '' : ' open'}`}>
                    <ChevronRightIcon />
                  </span>
                  <span className="conv-project-name">{p.name}</span>
                  {p.instructions ? <span className="conv-instr-dot" title="Has standing instructions" /> : null}
                </button>
                <div className="conv-project-actions">
                  <Tooltip content="Project instructions">
                    <button className="conv-proj-action-btn" onClick={() => setInstructionsProject(p)} aria-label="Project instructions">
                      <InstructionsIcon />
                    </button>
                  </Tooltip>
                  <Tooltip content="Delete project">
                    <button className="conv-proj-action-btn conv-proj-action-danger" onClick={() => setDeleteProjectTarget(p)} aria-label="Delete project">
                      <ProjectDeleteIcon />
                    </button>
                  </Tooltip>
                </div>
              </div>
              {!isCollapsed && (
                <div className="conv-project-body">
                  {convs.map(c => (
                    <ConversationRow
                      key={c.id}
                      conv={c}
                      active={c.id === activeConversationId}
                      projects={projects}
                      onSelect={onSelectConversation}
                      onChanged={reload}
                    />
                  ))}
                  {pickerFor === p.id ? (
                    <PersonaPicker onPick={(persona) => startChat(persona, p.id)} onCancel={() => setPickerFor(undefined)} />
                  ) : (
                    <button className="conv-add-in-project" onClick={() => setPickerFor(p.id)}>+ chat</button>
                  )}
                </div>
              )}
            </div>
          )
        })}

        {looseConvs.length > 0 && (
          <div className="conv-project">
            <div className="conv-project-header">
              <span className="conv-project-name loose">Chats</span>
            </div>
            <div className="conv-project-body">
              {looseConvs.map(c => (
                <ConversationRow
                  key={c.id}
                  conv={c}
                  active={c.id === activeConversationId}
                  projects={projects}
                  onSelect={onSelectConversation}
                  onChanged={reload}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {instructionsProject && (
        <ProjectInstructions
          project={instructionsProject}
          onClose={() => setInstructionsProject(null)}
          onSaved={() => { setInstructionsProject(null); reload() }}
        />
      )}

      {deleteProjectTarget && (
        <ConfirmDialog
          title={`Delete "${deleteProjectTarget.name}"?`}
          message="The project will be deleted. Its conversations will become loose chats and remain accessible."
          confirmLabel="Delete project"
          danger
          onConfirm={removeProject}
          onCancel={() => setDeleteProjectTarget(null)}
        />
      )}
    </aside>
  )
}
