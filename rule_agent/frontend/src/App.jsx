import { useState, useEffect, useCallback, useRef } from 'react'
import ChatBox from './components/ChatBox.jsx'
import RuleCard from './components/RuleCard.jsx'
import RuleBrowser from './components/RuleBrowser.jsx'
import TreeView from './components/TreeView.jsx'
import GraphView from './components/GraphView.jsx'
import Tooltip from './components/Tooltip.jsx'
import Onboarding from './components/Onboarding.jsx'
import ConversationSidebar from './components/ConversationSidebar.jsx'
import Login from './components/Login.jsx'
import { apiGet, apiFetch, getUsername, setUsername } from './api.js'

const RULE_HISTORY_KEY = 'rule_agent_rule_history'
const PINNED_RULES_KEY = 'pinned_rules'
const THEME_KEY        = 'rule_agent_theme'
const ONBOARDING_KEY   = 'rule_agent_onboarding_done'
const MAX_RECENT = 20

const LogoMark = () => (
  <div className="topbar-logo">
    {/* Ribbon wave — nod to the Coca-Cola dynamic ribbon */}
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none" aria-hidden="true">
      <path
        d="M2 10.5C5.2 6.6 8.2 12.6 11.2 9.2c1.6-1.8 2.7-3.1 3.8-4.2"
        stroke="#fff" strokeWidth="1.9" strokeLinecap="round"
      />
    </svg>
  </div>
)

const BrowserToggleIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="1.5" y="1.5" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M1.5 5.5h11M5.5 5.5v7" stroke="currentColor" strokeWidth="1.3"/>
  </svg>
)

const TreeToggleIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <circle cx="7" cy="2" r="1.4" stroke="currentColor" strokeWidth="1.3"/>
    <circle cx="2.5" cy="11.5" r="1.4" stroke="currentColor" strokeWidth="1.3"/>
    <circle cx="11.5" cy="11.5" r="1.4" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M7 3.4v3.6M7 7H2.5M7 7h4.5M2.5 10.1V7M11.5 10.1V7"
      stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
  </svg>
)

const GraphToggleIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <circle cx="7"  cy="2"  r="1.5" stroke="currentColor" strokeWidth="1.3"/>
    <circle cx="2"  cy="11" r="1.5" stroke="currentColor" strokeWidth="1.3"/>
    <circle cx="12" cy="11" r="1.5" stroke="currentColor" strokeWidth="1.3"/>
    <circle cx="7"  cy="7.5" r="1.5" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M7 3.5v2.5M7 9l-5 1.5M7 9l5 1.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
  </svg>
)


const PanelIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="1" y="1" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M9 1v12" stroke="currentColor" strokeWidth="1.3"/>
  </svg>
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

const CloseIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
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

const HelpIcon = () => (
  <svg width="15" height="15" viewBox="0 0 15 15" fill="none" aria-hidden="true">
    <circle cx="7.5" cy="7.5" r="6" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M5.7 5.6a1.8 1.8 0 1 1 2.6 1.9c-.6.3-.8.7-.8 1.3"
      stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    <circle cx="7.5" cy="10.8" r="0.7" fill="currentColor"/>
  </svg>
)

const PinIcon = ({ filled }) => (
  <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden="true">
    <path
      d="M5.5 1L6.8 4.2H10L7.3 6.2 8.3 9.5 5.5 7.5 2.7 9.5 3.7 6.2 1 4.2h3.2L5.5 1z"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinejoin="round"
      fill={filled ? 'currentColor' : 'none'}
    />
  </svg>
)

function loadFromStorage(key, fallback) {
  try {
    const stored = localStorage.getItem(key)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (Array.isArray(parsed)) return parsed
    }
  } catch {}
  return fallback
}

export default function App() {
  const [recentRules, setRecentRules] = useState(() => loadFromStorage(RULE_HISTORY_KEY, []))
  const [pinnedRules, setPinnedRules] = useState(() => loadFromStorage(PINNED_RULES_KEY, []))
  const [activeRuleId, setActiveRuleId]   = useState(null)
  const [activeRuleData, setActiveRuleData] = useState(null)
  const ruleDataCache = useRef(new Map())
  const [showBrowser, setShowBrowser]     = useState(false)
  const [showTree,    setShowTree]        = useState(false)
  const [showGraph,   setShowGraph]       = useState(false)
  const [chatPrefill, setChatPrefill]     = useState('')
  const [sidebarOpen, setSidebarOpen]     = useState(false)
  const [convSidebarOpen, setConvSidebarOpen] = useState(true)
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem(THEME_KEY) || 'dark' } catch { return 'dark' }
  })
  const [rulesLoaded, setRulesLoaded] = useState(null)
  const [rulesReady, setRulesReady] = useState(false)
  const [showTour, setShowTour] = useState(false)

  // ── Workspace (username + active conversation) ──────────────────────────────
  const [username, setUsernameState] = useState(() => getUsername())
  const [activeConversation, setActiveConversation] = useState(null) // {id, persona, project_id} | null
  const [convReload, setConvReload] = useState(0)
  const bumpConvReload = useCallback(() => setConvReload(n => n + 1), [])

  function handleSelectConversation(conv) {
    setActiveConversation(conv ? { id: conv.id, persona: conv.persona, project_id: conv.project_id } : null)
  }
  function handleChangeUser() {
    setUsername('')
    setUsernameState('')
    setActiveConversation(null)
  }

  // Auto-launch the walkthrough on the first visit.
  useEffect(() => {
    try {
      if (localStorage.getItem(ONBOARDING_KEY) !== '1') setShowTour(true)
    } catch {}
  }, [])

  const closeTour = useCallback(() => {
    setShowTour(false)
    try { localStorage.setItem(ONBOARDING_KEY, '1') } catch {}
  }, [])

  // Fetch live rule count from /health (public endpoint, no auth needed)
  useEffect(() => {
    apiFetch('/health')
      .then(r => r.json())
      .then(d => { if (typeof d.rules_loaded === 'number') setRulesLoaded(d.rules_loaded) })
      .catch(() => {})
      .finally(() => setRulesReady(true))
  }, [])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try { localStorage.setItem(THEME_KEY, theme) } catch {}
  }, [theme])

  useEffect(() => {
    try { localStorage.setItem(RULE_HISTORY_KEY, JSON.stringify(recentRules)) } catch {}
  }, [recentRules])

  useEffect(() => {
    try { localStorage.setItem(PINNED_RULES_KEY, JSON.stringify(pinnedRules)) } catch {}
  }, [pinnedRules])

  const pinnedIds = new Set(pinnedRules.map(r => r.rule_id))
  const allTabs   = [...pinnedRules, ...recentRules]

  function _extractStub(ruleData) {
    return {
      rule_id:          ruleData.rule_id,
      description:      ruleData.description ?? '',
      quality_category: ruleData.quality_category ?? '',
      severity:         ruleData.severity ?? '',
      table_checked:    ruleData.table_checked ?? '',
    }
  }

  function onRuleLoaded(ruleData) {
    const id = ruleData.rule_id
    ruleDataCache.current.set(id, ruleData)
    setActiveRuleData(ruleData)
    setActiveRuleId(id)
    setSidebarOpen(true)
    if (!pinnedIds.has(id)) {
      setRecentRules(prev => {
        if (prev.find(r => r.rule_id === id)) return prev
        return [...prev, _extractStub(ruleData)].slice(-MAX_RECENT)
      })
    }
  }

  const loadRuleById = useCallback(async (ruleId) => {
    if (ruleDataCache.current.has(ruleId)) {
      setActiveRuleData(ruleDataCache.current.get(ruleId))
      setActiveRuleId(ruleId)
      setSidebarOpen(true)
      return
    }
    try {
      const res = await apiGet(`/rule/${ruleId}`)
      if (res.ok) onRuleLoaded(await res.json())
    } catch {}
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pinnedRules, recentRules])

  function closeTab(ruleId, e) {
    e.stopPropagation()
    const isPinned = pinnedIds.has(ruleId)
    if (isPinned) {
      setPinnedRules(prev => prev.filter(r => r.rule_id !== ruleId))
    } else {
      setRecentRules(prev => prev.filter(r => r.rule_id !== ruleId))
    }
    if (activeRuleId === ruleId) {
      const remaining = allTabs.filter(r => r.rule_id !== ruleId)
      const nextId = remaining[remaining.length - 1]?.rule_id ?? null
      setActiveRuleId(nextId)
      if (nextId) {
        const cached = ruleDataCache.current.get(nextId)
        setActiveRuleData(cached ?? null)
        if (!cached) loadRuleById(nextId)
      } else {
        setActiveRuleData(null)
      }
    }
  }

  function togglePin(ruleId, e) {
    e.stopPropagation()
    if (pinnedIds.has(ruleId)) {
      const ruleData = pinnedRules.find(r => r.rule_id === ruleId)
      setPinnedRules(prev => prev.filter(r => r.rule_id !== ruleId))
      if (ruleData) setRecentRules(prev => [ruleData, ...prev].slice(0, MAX_RECENT))
    } else {
      const ruleData = recentRules.find(r => r.rule_id === ruleId)
      setRecentRules(prev => prev.filter(r => r.rule_id !== ruleId))
      if (ruleData) setPinnedRules(prev => [...prev, ruleData])
    }
  }

  function handleAskAboutRule(ruleId) {
    setChatPrefill(`Explain rule ${ruleId}`)
  }

  const hasBothGroups = pinnedRules.length > 0 && recentRules.length > 0

  if (!username) {
    return <Login onDone={(name) => setUsernameState(name)} />
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">
          <LogoMark />
          <div className="topbar-brand-text">
            <span className="topbar-product">Rule Intelligence</span>
            <span className="topbar-sub">Coca-Cola HBC · Customer Data Quality</span>
          </div>
        </div>

        <nav className="view-switcher" data-tour="views" aria-label="View">
          <Tooltip content="Browse and search all data quality rules">
            <button
              className={`view-switch-btn${showBrowser ? ' active' : ''}`}
              onClick={() => { setShowBrowser(v => !v); setShowTree(false); setShowGraph(false) }}
            >
              <BrowserToggleIcon />
              <span>Browse</span>
            </button>
          </Tooltip>
          <Tooltip content="Explore rules as a hierarchical tree">
            <button
              className={`view-switch-btn${showTree ? ' active' : ''}`}
              onClick={() => { setShowTree(v => !v); setShowBrowser(false); setShowGraph(false) }}
            >
              <TreeToggleIcon />
              <span>Tree</span>
            </button>
          </Tooltip>
          <Tooltip content="Visualise all rules as an interactive node graph">
            <button
              className={`view-switch-btn${showGraph ? ' active' : ''}`}
              onClick={() => { setShowGraph(v => !v); setShowBrowser(false); setShowTree(false) }}
            >
              <GraphToggleIcon />
              <span>Graph</span>
            </button>
          </Tooltip>
        </nav>

        <div className="topbar-actions">
          <span className={`status-pill${!rulesReady ? ' loading' : ''}`}>
            <span className="status-dot" />
            {!rulesReady
              ? 'Connecting…'
              : rulesLoaded !== null
                ? `${rulesLoaded} Active Rules`
                : '— Offline'}
          </span>
          <Tooltip content={sidebarOpen ? 'Close rule panel' : activeRuleId ? `View ${activeRuleId}` : 'Open rule panel'}>
            <button
              data-tour="rule-card"
              className={`sidebar-toggle-btn${sidebarOpen ? ' active' : ''}${activeRuleId && !sidebarOpen ? ' has-rule' : ''}`}
              onClick={() => setSidebarOpen(v => !v)}
            >
              <PanelIcon />
              {activeRuleId && !sidebarOpen
                ? <span className="sidebar-toggle-rule-id">{activeRuleId}</span>
                : <span>Rule Card</span>
              }
            </button>
          </Tooltip>
          <span className="topbar-divider" />
          <Tooltip content="Take the tour">
            <button
              className="help-btn"
              onClick={() => setShowTour(true)}
              aria-label="Take the walkthrough"
            >
              <HelpIcon />
            </button>
          </Tooltip>
          <Tooltip content={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
            <button
              className="theme-toggle-btn"
              onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
            </button>
          </Tooltip>
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
        />
        <SidebarTabToggle open={convSidebarOpen} onClick={() => setConvSidebarOpen(v => !v)} />

        {showGraph && (
          <GraphView
            onRuleSelected={id => { loadRuleById(id); setShowGraph(false) }}
            onClose={() => setShowGraph(false)}
          />
        )}

        {(showBrowser || showTree) && !showGraph && (
          <div className="browser-panel">
            {showTree ? (
              <TreeView
                onRuleSelected={loadRuleById}
                onClose={() => setShowTree(false)}
              />
            ) : (
              <RuleBrowser
                onRuleSelected={loadRuleById}
                onClose={() => setShowBrowser(false)}
              />
            )}
          </div>
        )}

        <main className="chat-main">
          <ChatBox
            onRuleLoaded={onRuleLoaded}
            prefill={chatPrefill}
            onPrefillConsumed={() => setChatPrefill('')}
            activeRuleId={activeRuleId}
            conversationId={activeConversation?.id ?? null}
            conversationPersona={activeConversation?.persona ?? null}
            projectId={activeConversation?.project_id ?? null}
            onConversationCreated={(conv) => { handleSelectConversation(conv); bumpConvReload() }}
            onConversationUpdated={bumpConvReload}
            onStartNewChat={() => setActiveConversation(null)}
          />
        </main>

        <aside className={`rule-sidebar${sidebarOpen ? ' open' : ''}`}>
          <div className="rule-sidebar-header">
            <span className="rule-sidebar-title">Rule Details</span>
            <button className="rule-sidebar-close" onClick={() => setSidebarOpen(false)} aria-label="Close rule panel">
              <CloseIcon />
            </button>
          </div>

          {allTabs.length > 0 && (
            <div className="rule-tabs">
              {pinnedRules.map(rule => (
                <button
                  key={rule.rule_id}
                  className={`rule-tab pinned${rule.rule_id === activeRuleId ? ' active' : ''}`}
                  onClick={() => loadRuleById(rule.rule_id)}
                >
                  <span className="rule-tab-pin-indicator" aria-label="Pinned">
                    <PinIcon filled />
                  </span>
                  <span className="rule-tab-id">{rule.rule_id}</span>
                  <Tooltip content="Unpin tab">
                    <span
                      className="rule-tab-pin"
                      onClick={e => togglePin(rule.rule_id, e)}
                      role="button"
                    >
                      <PinIcon filled />
                    </span>
                  </Tooltip>
                  <Tooltip content="Close tab">
                    <span
                      className="rule-tab-close"
                      onClick={e => closeTab(rule.rule_id, e)}
                      role="button"
                    >×</span>
                  </Tooltip>
                </button>
              ))}

              {hasBothGroups && (
                <div className="tabs-separator">
                  <span className="tabs-sep-line" />
                  <span className="tabs-sep-label">Recent</span>
                  <span className="tabs-sep-line" />
                </div>
              )}

              {recentRules.map(rule => (
                <button
                  key={rule.rule_id}
                  className={`rule-tab${rule.rule_id === activeRuleId ? ' active' : ''}`}
                  onClick={() => loadRuleById(rule.rule_id)}
                >
                  <span className="rule-tab-id">{rule.rule_id}</span>
                  <Tooltip content="Pin tab">
                    <span
                      className="rule-tab-pin"
                      onClick={e => togglePin(rule.rule_id, e)}
                      role="button"
                    >
                      <PinIcon filled={false} />
                    </span>
                  </Tooltip>
                  <Tooltip content="Close tab">
                    <span
                      className="rule-tab-close"
                      onClick={e => closeTab(rule.rule_id, e)}
                      role="button"
                    >×</span>
                  </Tooltip>
                </button>
              ))}
            </div>
          )}

          <div className="rule-panel-body">
            {activeRuleData ? (
              <RuleCard
                rule={activeRuleData}
                onAskAboutRule={handleAskAboutRule}
                onRuleSelected={loadRuleById}
              />
            ) : (
              <EmptyState onAsk={text => setChatPrefill(text)} />
            )}
          </div>
        </aside>
      </div>

      <Onboarding open={showTour} onClose={closeTour} />
    </div>
  )
}

function EmptyState({ onAsk }) {
  const chips = [
    'Explain rule RCCOMP_103.1',
    'SAP fields in RCACTI_1',
    'List all completeness rules',
  ]

  return (
    <div className="empty-state">
      <div className="empty-visual">
        <div className="empty-ring empty-ring-3" />
        <div className="empty-ring empty-ring-2" />
        <div className="empty-ring empty-ring-1" />
        <div className="empty-icon-core">
          <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true">
            <rect x="3" y="3.5" width="20" height="19" rx="3" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M8 10h10M8 14h7M8 18h9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </div>
      </div>

      <div className="empty-text">
        <p className="empty-title">Select a rule to begin</p>
        <p className="empty-hint">
          Ask the agent about any data quality rule to see its full breakdown,
          SAP fields, workflow steps, and technical implementation.
        </p>
      </div>

      <div className="empty-examples">
        <span className="empty-example-label">Try asking</span>
        <div className="empty-chips">
          {chips.map(s => (
            <button key={s} className="empty-chip" onClick={() => onAsk?.(s)}>{s}</button>
          ))}
        </div>
      </div>

      <p className="empty-watermark">Powered by Coca-Cola HBC Data Intelligence</p>
    </div>
  )
}
