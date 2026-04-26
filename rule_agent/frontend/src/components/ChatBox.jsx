import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import Tooltip from './Tooltip.jsx'
import { apiGet, apiPost } from '../api.js'

const STORAGE_KEY = 'rule_agent_chat_history'

const INITIAL_MESSAGES = [
  {
    role: 'agent',
    text: 'Hello! I can explain any of the 228 Customer data quality rules in detail.\n\nAsk about a specific rule ID, describe what a rule does, or explore by category.',
    ts: null,
  },
]

const SUGGESTIONS = [
  'Find a rule that checks customer email is not empty',
  'Explain rule RCCOMP_103.1',
  'List all completeness rules',
  'Which rules check KNA1?',
]

const RULE_ID_RE = /\b([A-Z]{2,8}_\d+(?:\.\d+)?)\b/g

function addRuleLinks(text) {
  return text.replace(RULE_ID_RE, (match) => `[${match}](#rule:${match})`)
}

function makeMarkdownComponents(onRuleClick) {
  return {
    a: ({ href, children }) => {
      if (href?.startsWith('#rule:')) {
        const ruleId = href.slice(6)
        return (
          <span
            className="rule-link"
            onClick={() => onRuleClick(ruleId)}
            role="button"
            tabIndex={0}
            onKeyDown={e => e.key === 'Enter' && onRuleClick(ruleId)}
          >
            {children}
          </span>
        )
      }
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    },
  }
}

const AgentIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M2.5 7l3.5 3.5 5.5-5.5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const UserIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <circle cx="6.5" cy="4.5" r="2.5" stroke="currentColor" strokeWidth="1.4"/>
    <path d="M1 11.5c0-2.2 2.4-4 5.5-4s5.5 1.8 5.5 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
  </svg>
)

const SendIcon = () => (
  <svg width="15" height="15" viewBox="0 0 15 15" fill="none" aria-hidden="true">
    <path d="M2 7.5h11M8.5 3l4.5 4.5L8.5 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const TrashIcon = () => (
  <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden="true">
    <path d="M1.5 3h8M4 3V2h3v1M2.5 3l.5 6.5h5L9 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  if (isToday) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function ChatBox({ onRuleLoaded, prefill, onPrefillConsumed, activeRuleId }) {
  const [messages, setMessages] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        if (Array.isArray(parsed) && parsed.length > 0) return parsed
      }
    } catch {}
    return INITIAL_MESSAGES
  })
  const [input, setInput]           = useState('')
  const [loading, setLoading]       = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const bottomRef        = useRef(null)
  const textareaRef      = useRef(null)
  const sessionStartRef  = useRef(0)
  const prevRuleIdRef    = useRef(activeRuleId)

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(messages)) } catch {}
  }, [messages])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!loading) textareaRef.current?.focus()
  }, [loading])

  // Reset session window when the active rule changes so history stays rule-scoped
  useEffect(() => {
    if (activeRuleId !== prevRuleIdRef.current) {
      prevRuleIdRef.current = activeRuleId
      sessionStartRef.current = messages.length
    }
  }, [activeRuleId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (prefill) {
      setInput(prefill)
      onPrefillConsumed?.()
      setTimeout(() => {
        const ta = textareaRef.current
        if (ta) {
          ta.focus()
          ta.style.height = 'auto'
          ta.style.height = ta.scrollHeight + 'px'
        }
      }, 0)
    }
  }, [prefill]) // eslint-disable-line react-hooks/exhaustive-deps

  function clearHistory() {
    if (!confirmClear) {
      setConfirmClear(true)
      setTimeout(() => setConfirmClear(false), 2500)
      return
    }
    setMessages(INITIAL_MESSAGES)
    sessionStartRef.current = 0
    try { localStorage.removeItem(STORAGE_KEY) } catch {}
    setConfirmClear(false)
  }

  async function send(overrideText) {
    const text = (overrideText ?? input).trim()
    if (!text || loading) return

    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setMessages(prev => [...prev, { role: 'user', text, ts: Date.now() }])
    setLoading(true)

    try {
      // Build history from session start, capped at last 10 turns (20 messages)
      const sessionMsgs = messages.slice(sessionStartRef.current)
      const MAX_HISTORY = 20
      const historyWindow = sessionMsgs.slice(-MAX_HISTORY)
      const history = historyWindow.map(m => ({
        role: m.role === 'user' ? 'user' : 'assistant',
        content: m.text,
      }))

      const chatRes = await apiPost('/chat', {
        message: text,
        context_rule_id: activeRuleId ?? null,
        history,
      })
      if (!chatRes.ok) throw new Error(`Chat API error ${chatRes.status}`)
      const chatData = await chatRes.json()

      setMessages(prev => [...prev, { role: 'agent', text: chatData.response, ts: Date.now() }])

      if (chatData.rule_id) {
        const ruleRes = await apiGet(`/rule/${chatData.rule_id}`)
        if (ruleRes.ok) onRuleLoaded(await ruleRes.json())
      }
    } catch (err) {
      setMessages(prev => [
        ...prev,
        { role: 'agent', text: `Error: ${err.message}`, isError: true, ts: Date.now() },
      ])
    } finally {
      setLoading(false)
    }
  }

  async function handleRuleLinkClick(ruleId) {
    try {
      const res = await apiGet(`/rule/${ruleId}`)
      if (res.ok) onRuleLoaded(await res.json())
    } catch {}
  }

  function onKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  function onInputChange(e) {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = e.target.scrollHeight + 'px'
  }

  const mdComponents = makeMarkdownComponents(handleRuleLinkClick)
  const userMsgCount = messages.filter(m => m.role === 'user').length
  const hasHistory = messages.length > 1

  return (
    <div className="chat-container">
      <div className="chat-panel-header">
        <div className="chat-panel-title">
          <span className="chat-panel-label">AI Assistant</span>
          <div className="chat-panel-live">
            <span className="chat-panel-live-dot" />
            <span className="chat-panel-live-label">Live</span>
          </div>
          {userMsgCount > 0 && (
            <span className="chat-msg-count">{userMsgCount}</span>
          )}
        </div>
        {hasHistory && (
          <Tooltip content={confirmClear ? 'Click again to confirm' : 'Clear chat history'}>
            <button
              className={`clear-btn${confirmClear ? ' confirm' : ''}`}
              onClick={clearHistory}
            >
              {confirmClear ? 'Confirm?' : <><TrashIcon />Clear</>}
            </button>
          </Tooltip>
        )}
      </div>

      <div className="chat-history">
        <div className="chat-history-inner">
          {messages.map((msg, i) => (
            <div key={i} className={`msg-row ${msg.role}`}>
              {msg.role === 'agent' && (
                <div className="msg-avatar agent-avatar"><AgentIcon /></div>
              )}
              <div className="msg-content">
                <div className={`bubble ${msg.role}${msg.isError ? ' error' : ''}`}>
                  {msg.role === 'agent' && !msg.isError ? (
                    <div className="md-body">
                      <ReactMarkdown components={mdComponents}>
                        {addRuleLinks(msg.text)}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <p style={{ whiteSpace: 'pre-line' }}>{msg.text}</p>
                  )}
                </div>
                {msg.ts && (
                  <span className={`msg-time ${msg.role}`}>{formatTime(msg.ts)}</span>
                )}
              </div>
              {msg.role === 'user' && (
                <div className="msg-avatar user-avatar"><UserIcon /></div>
              )}
            </div>
          ))}

          {messages.length === 1 && (
            <div className="suggestions">
              {SUGGESTIONS.map((s, i) => (
                <button key={i} className="suggestion-chip" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          )}

          {loading && (
            <div className="msg-row agent">
              <div className="msg-avatar agent-avatar"><AgentIcon /></div>
              <div className="msg-content">
                <div className="bubble agent">
                  <div className="typing-dots">
                    <span /><span /><span />
                  </div>
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="chat-input-row">
        <div className="chat-input-inner">
          <div className="input-wrap" onClick={() => textareaRef.current?.focus()}>
            <textarea
              ref={textareaRef}
              className="chat-input"
              value={input}
              onChange={onInputChange}
              onKeyDown={onKey}
              placeholder="Ask about a rule, describe what it does, or follow up on a rule…"
              rows={1}
              disabled={loading}
            />
            <Tooltip content="Send message (Enter)">
              <button
                className="send-btn"
                onClick={() => send()}
                disabled={loading || !input.trim()}
              >
                <SendIcon />
              </button>
            </Tooltip>
          </div>
          <div className="input-hint">
            <span className="input-hint-segment">
              <kbd>↵</kbd>
              <span>send</span>
            </span>
            <span className="input-hint-dot" />
            <span className="input-hint-segment">
              <kbd>⇧</kbd><kbd>↵</kbd>
              <span>new line</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
