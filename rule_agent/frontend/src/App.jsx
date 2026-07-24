import { useState, useEffect, useCallback, useRef } from 'react'
import ChatBox from './components/ChatBox.jsx'
import ConversationSidebar from './components/ConversationSidebar.jsx'
import Login from './components/Login.jsx'
import Settings from './components/Settings.jsx'
import RuleCard from './components/RuleCard.jsx'
import RuleCardSkeleton from './components/RuleCardSkeleton.jsx'
import ToastHost from './components/Toast.jsx'
import { subscribeToasts, notifyError } from './utils/toast.js'
import { branding } from './config/branding.js'
import {
  getUsername, setUsername, listKBs, getRuleCard,
  listKbRepos, createKbRepo, resyncKbRepo, deleteKbRepo,
} from './api.js'

const THEME_KEY = 'rule_agent_theme'
const ACTIVE_KB_KEY = 'rule_agent_active_kb'

const LogoMark = () => (
  <div className="topbar-logo">
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none" aria-hidden="true">
      <path
        d="M2 10.5C5.2 6.6 8.2 12.6 11.2 9.2c1.6-1.8 2.7-3.1 3.8-4.2"
        stroke="#fff" strokeWidth="1.9" strokeLinecap="round"
      />
    </svg>
  </div>
)

const SidebarTabToggle = ({ open, onClick }) => (
  <button
    className={`conv-float-toggle${open ? ' open' : ''}`}
    onClick={onClick}
    aria-label={open ? 'Collapse chat history' : 'Expand chat history'}
  >
    <span className="cft-logo" aria-hidden="true">
      <svg width="15" height="15" viewBox="0 0 17 17" fill="none">
        <path d="M2 10.5C5.2 6.6 8.2 12.6 11.2 9.2c1.6-1.8 2.7-3.1 3.8-4.2"
          stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" />
      </svg>
    </span>
    <span className="cft-arrow" aria-hidden="true">
      <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
        <path d="M4.5 2L8.5 6L4.5 10" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  </button>
)

const SunIcon = () => (
  <svg width="15" height="15" viewBox="0 0 15 15" fill="none" aria-hidden="true">
    <circle cx="7.5" cy="7.5" r="2.8" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M7.5 1v1.4M7.5 12.6V14M14 7.5h-1.4M2.4 7.5H1M11.9 3.1l-1 1M4.1 10.9l-1 1M11.9 11.9l-1-1M4.1 4.1l-1-1"
      stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
  </svg>
)

const MoonIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M12 9.3A6 6 0 0 1 4.7 2a5.5 5.5 0 1 0 7.3 7.3z"
      stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const SettingsIcon = () => (
  <svg width="15" height="15" viewBox="0 0 15 15" fill="none" aria-hidden="true">
    <circle cx="7.5" cy="7.5" r="2.2" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M7.5 1.5v1.6M7.5 11.9v1.6M13.5 7.5h-1.6M3.1 7.5H1.5M11.7 3.3l-1.1 1.1M4.4 10.6l-1.1 1.1M11.7 11.7l-1.1-1.1M4.4 4.4 3.3 3.3"
      stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
  </svg>
)

export default function App() {
  const [convSidebarOpen, setConvSidebarOpen] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem(THEME_KEY) || 'dark' } catch { return 'dark' }
  })

  // ── Workspace (username + active conversation) ──────────────────────────────
  const [username, setUsernameState] = useState(() => getUsername())
  const [activeConversation, setActiveConversation] = useState(null) // {id, project_id} | null
  const [convReload, setConvReload] = useState(0)
  const bumpConvReload = useCallback(() => setConvReload(n => n + 1), [])

  // ── Knowledge base registry (multi-KB context, prop-drilled) ────────────────
  const [knowledgeBases, setKnowledgeBases] = useState([])
  const [activeKbId, setActiveKbId] = useState(() => {
    try { return localStorage.getItem(ACTIVE_KB_KEY) || null } catch { return null }
  })
  const [switcherEnabled, setSwitcherEnabled] = useState(false)
  // Surface a KB-load failure at most once (this runs on mount AND on every 3s
  // repo-poll tick, so an un-deduped toast would spam while the backend is down).
  const kbLoadErrorRef = useRef(false)

  const refreshKbs = useCallback(() => {
    return listKBs()
      .then(data => {
        const kbs = data.knowledge_bases ?? []
        setKnowledgeBases(kbs)
        setSwitcherEnabled(!!data.switcher_enabled)
        setActiveKbId(prev => {
          if (prev && kbs.some(k => k.id === prev)) return prev
          return data.active_kb ?? kbs[0]?.id ?? null
        })
        kbLoadErrorRef.current = false
      })
      .catch(() => {
        if (!kbLoadErrorRef.current) {
          kbLoadErrorRef.current = true
          notifyError('Couldn’t reach the server to load knowledge bases. Check that the backend is running.')
        }
      })
  }, [])

  useEffect(() => { refreshKbs() }, [refreshKbs])

  useEffect(() => {
    if (!activeKbId) return
    try { localStorage.setItem(ACTIVE_KB_KEY, activeKbId) } catch {}
  }, [activeKbId])

  // ── App-wide toasts ──────────────────────────────────────────────────────
  const [toasts, setToasts] = useState([])
  const pushToast = useCallback(({ type, message }) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    setToasts(prev => [...prev, { id, type, message }])
  }, [])
  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])
  // Errors raised anywhere in the app (utils/toast) surface as toasts here.
  useEffect(() => subscribeToasts(t => setToasts(prev => [...prev, t])), [])

  // ── Knowledge repositories (self-service ingestion, polled app-wide) ────────
  // Ownership lives here (not in Settings) so a repo keeps updating — and
  // fires its toast — even while Settings is closed.
  const [repos, setRepos] = useState([])
  const [reposLoading, setReposLoading] = useState(false)
  const [reposLoadError, setReposLoadError] = useState('')
  const prevRepoStatusRef = useRef({})

  const loadRepos = useCallback(async ({ silent } = {}) => {
    if (!silent) setReposLoading(true)
    if (!silent) setReposLoadError('')
    try {
      const data = await listKbRepos()
      const next = data.repos ?? []
      const prevMap = prevRepoStatusRef.current

      next.forEach(r => {
        const before = prevMap[r.id]
        if (before && before !== r.status) {
          if (r.status === 'ready') {
            pushToast({ type: 'success', message: `✓ '${r.name}' is ready — select it in the switcher` })
            refreshKbs()
          } else if (r.status === 'error') {
            const reason = r.status_detail || 'An unknown error occurred.'
            const hadContent = (r.chunks > 0) || (r.documents > 0)
            const message = hadContent
              ? `⚠ '${r.name}' couldn't update: ${reason}. Still using the previous version.`
              : `⚠ '${r.name}' couldn't be added: ${reason}`
            pushToast({ type: 'error', message })
          }
        }
      })

      const nextMap = {}
      next.forEach(r => { nextMap[r.id] = r.status })
      prevRepoStatusRef.current = nextMap

      setRepos(next)
    } catch {
      if (!silent) setReposLoadError('Could not load knowledge repositories.')
    } finally {
      if (!silent) setReposLoading(false)
    }
  }, [pushToast, refreshKbs])

  useEffect(() => { loadRepos() }, [loadRepos])

  // Poll every 3s while any repo is still queued/ingesting — regardless of
  // whether Settings is open — so the switcher and toasts stay live.
  useEffect(() => {
    const hasPending = repos.some(r => r.status === 'queued' || r.status === 'ingesting')
    if (!hasPending) return
    const timer = setInterval(async () => {
      await loadRepos({ silent: true })
      refreshKbs()
    }, 3000)
    return () => clearInterval(timer)
  }, [repos, loadRepos, refreshKbs])

  const reloadRepo = useCallback(async (id) => {
    await resyncKbRepo(id)
    await loadRepos({ silent: true })
    refreshKbs()
  }, [loadRepos, refreshKbs])

  const deleteRepo = useCallback(async (id) => {
    await deleteKbRepo(id)
    await loadRepos({ silent: true })
    refreshKbs()
  }, [loadRepos, refreshKbs])

  const addRepo = useCallback(async (payload) => {
    await createKbRepo(payload)
    await loadRepos({ silent: true })
    refreshKbs()
  }, [loadRepos, refreshKbs])

  function handleSelectConversation(conv) {
    setActiveConversation(conv ? { id: conv.id, project_id: conv.project_id } : null)
  }
  function handleChangeUser() {
    setUsername('')
    setUsernameState('')
    setActiveConversation(null)
  }

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try { localStorage.setItem(THEME_KEY, theme) } catch {}
  }, [theme])

  const activeKb = knowledgeBases.find(k => k.id === activeKbId) ?? null
  const showKbSelector = switcherEnabled && knowledgeBases.length > 1

  // ── Rule card (only for entity-capable KBs, e.g. a rule repo) ───────────────
  const entityCapable = !!activeKb?.capabilities?.includes('entity')
  const [activeRuleId, setActiveRuleId] = useState(null)
  const [ruleData, setRuleData] = useState(null)
  const [chatPrefill, setChatPrefill] = useState(null)

  const loadRule = useCallback(async (ruleId) => {
    if (!ruleId || !activeKbId) return
    setActiveRuleId(ruleId)
    setRuleData(null)
    try {
      setRuleData(await getRuleCard(activeKbId, ruleId))
    } catch {
      // Don't leave the loading skeleton hanging forever — close the panel and
      // tell the user instead of failing silently.
      setActiveRuleId(null)
      setRuleData(null)
      notifyError(`Couldn’t load rule ${ruleId}. Please try again.`)
    }
  }, [activeKbId])

  const closeRule = useCallback(() => { setActiveRuleId(null); setRuleData(null) }, [])

  // Clear the rule panel when the active KB changes (rule IDs aren't shared).
  useEffect(() => { setActiveRuleId(null); setRuleData(null) }, [activeKbId])

  if (!username) {
    return <Login onDone={(name) => setUsernameState(name)} />
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">
          <LogoMark />
          <div className="topbar-brand-text">
            <span className="topbar-product">{branding.productName}</span>
            <span className="topbar-sub">{activeKb?.name ?? branding.tagline}</span>
          </div>
        </div>

        <div className="topbar-center" aria-hidden="true" />

        <div className="topbar-actions">
          {showKbSelector && (
            <select
              className="topbar-kb-select"
              value={activeKbId ?? ''}
              onChange={e => {
                const kb = knowledgeBases.find(k => k.id === e.target.value)
                if (kb && !kb.selectable) return // guard: shouldn't fire for a disabled option
                setActiveKbId(e.target.value)
                setActiveConversation(null)
              }}
              aria-label="Active knowledge base"
            >
              {knowledgeBases.map(kb => (
                <option key={kb.id} value={kb.id} disabled={!kb.selectable}>
                  {kb.selectable ? kb.name : `${kb.name} (updating…)`}
                </option>
              ))}
            </select>
          )}
          <button className="header-action-btn" onClick={() => setSettingsOpen(true)}>
            <SettingsIcon /> Settings
          </button>
          <button
            className="theme-toggle-btn"
            onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
            aria-label="Toggle theme"
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
          </button>
        </div>
      </header>

      <div className="app-body" style={{ position: 'relative' }}>
        {convSidebarOpen && (
          <div className="mobile-overlay-backdrop" onClick={() => setConvSidebarOpen(false)} />
        )}
        <ConversationSidebar
          username={username}
          onChangeUser={handleChangeUser}
          activeConversationId={activeConversation?.id ?? null}
          onSelectConversation={handleSelectConversation}
          reloadSignal={convReload}
          open={convSidebarOpen}
          activeKbId={activeKbId}
        />
        <SidebarTabToggle open={convSidebarOpen} onClick={() => setConvSidebarOpen(v => !v)} />

        <main className="chat-main">
          <ChatBox
            conversationId={activeConversation?.id ?? null}
            projectId={activeConversation?.project_id ?? null}
            activeKbId={activeKbId}
            activeKb={activeKb}
            onConversationCreated={(conv) => { handleSelectConversation(conv); bumpConvReload() }}
            onConversationUpdated={bumpConvReload}
            onRuleSelected={entityCapable ? loadRule : undefined}
            prefill={chatPrefill}
          />
        </main>

        {entityCapable && activeRuleId && (
          <aside className="rule-panel">
            <div className="rule-panel-header">
              <span className="rule-panel-title">{activeRuleId}</span>
              <button className="rule-sidebar-close" onClick={closeRule} aria-label="Close rule card">×</button>
            </div>
            <div className="rule-panel-body">
              {ruleData ? (
                <RuleCard
                  rule={ruleData}
                  kbId={activeKbId}
                  onRuleSelected={loadRule}
                  onAskAboutRule={(id) => setChatPrefill({ text: `Explain rule ${id}`, id: Date.now() })}
                />
              ) : (
                <RuleCardSkeleton />
              )}
            </div>
          </aside>
        )}
      </div>

      {settingsOpen && (
        <Settings
          knowledgeBases={knowledgeBases}
          activeKbId={activeKbId}
          switcherEnabled={switcherEnabled}
          onSelectKb={setActiveKbId}
          theme={theme}
          onSetTheme={setTheme}
          onClose={() => setSettingsOpen(false)}
          repos={repos}
          reposLoading={reposLoading}
          reposLoadError={reposLoadError}
          onReloadRepo={reloadRepo}
          onDeleteRepo={deleteRepo}
          onAddRepo={addRepo}
        />
      )}

      <ToastHost toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
