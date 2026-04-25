import { useState, useEffect, useCallback } from 'react'
import ChatBox from './components/ChatBox.jsx'
import RuleCard from './components/RuleCard.jsx'
import RuleBrowser from './components/RuleBrowser.jsx'
import Tooltip from './components/Tooltip.jsx'

const RULE_HISTORY_KEY = 'rule_agent_rule_history'
const PINNED_RULES_KEY = 'pinned_rules'
const MAX_RECENT = 20

const LogoMark = () => (
  <div className="topbar-logo">
    <span style={{ fontFamily: 'DM Serif Display, serif', fontSize: '16px', color: '#fff', lineHeight: 1, userSelect: 'none' }}>R</span>
  </div>
)

const BrowserToggleIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="1.5" y="1.5" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M1.5 5.5h11M5.5 5.5v7" stroke="currentColor" strokeWidth="1.3"/>
  </svg>
)

const PanelIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="1" y="1" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M9 1v12" stroke="currentColor" strokeWidth="1.3"/>
  </svg>
)

const CloseIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
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
  const [showBrowser, setShowBrowser]     = useState(false)
  const [chatPrefill, setChatPrefill]     = useState('')
  const [sidebarOpen, setSidebarOpen]     = useState(false)

  useEffect(() => {
    try { localStorage.setItem(RULE_HISTORY_KEY, JSON.stringify(recentRules)) } catch {}
  }, [recentRules])

  useEffect(() => {
    try { localStorage.setItem(PINNED_RULES_KEY, JSON.stringify(pinnedRules)) } catch {}
  }, [pinnedRules])

  const pinnedIds = new Set(pinnedRules.map(r => r.rule_id))
  const allTabs   = [...pinnedRules, ...recentRules]
  const activeRule = allTabs.find(r => r.rule_id === activeRuleId) ?? null

  function onRuleLoaded(ruleData) {
    const id = ruleData.rule_id
    if (pinnedIds.has(id)) { setActiveRuleId(id); setSidebarOpen(true); return }
    if (recentRules.find(r => r.rule_id === id)) { setActiveRuleId(id); setSidebarOpen(true); return }
    setRecentRules(prev => [...prev, ruleData].slice(-MAX_RECENT))
    setActiveRuleId(id)
    setSidebarOpen(true)
  }

  const loadRuleById = useCallback(async (ruleId) => {
    try {
      const res = await fetch(`/api/rule/${ruleId}`)
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
      setActiveRuleId(remaining[remaining.length - 1]?.rule_id ?? null)
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

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">
          <LogoMark />
          <span className="topbar-product">Rule Intelligence</span>
          <span className="topbar-brand-sep" />
          <span className="topbar-sub">by Coca-Cola HBC</span>
        </div>
        <div className="topbar-actions">
          <span className="pro-badge">PRO</span>
          <span className="status-pill">
            <span className="status-dot" />
            228 Active Rules
          </span>
          <span className="topbar-divider" />
          <Tooltip content="Browse and search all 228 data quality rules">
            <button
              className={`browser-toggle-btn${showBrowser ? ' active' : ''}`}
              onClick={() => setShowBrowser(v => !v)}
            >
              <BrowserToggleIcon />
              <span>Browse Rules</span>
            </button>
          </Tooltip>
          <Tooltip content={sidebarOpen ? 'Close rule panel' : activeRuleId ? `View ${activeRuleId}` : 'Open rule panel'}>
            <button
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
        </div>
      </header>

      <div className="app-body">
        {showBrowser && (
          <div className="browser-panel">
            <RuleBrowser
              onRuleSelected={loadRuleById}
              onClose={() => setShowBrowser(false)}
            />
          </div>
        )}

        <main className="chat-main">
          <ChatBox
            onRuleLoaded={onRuleLoaded}
            prefill={chatPrefill}
            onPrefillConsumed={() => setChatPrefill('')}
            activeRuleId={activeRuleId}
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
                  onClick={() => setActiveRuleId(rule.rule_id)}
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
                  onClick={() => setActiveRuleId(rule.rule_id)}
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
            {activeRule ? (
              <RuleCard
                rule={activeRule}
                onAskAboutRule={handleAskAboutRule}
                onRuleSelected={loadRuleById}
              />
            ) : (
              <EmptyState onAsk={text => setChatPrefill(text)} />
            )}
          </div>
        </aside>
      </div>
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
