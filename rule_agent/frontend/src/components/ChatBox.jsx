import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import Tooltip from './Tooltip.jsx'
import YamlValidator from './YamlValidator.jsx'
import { apiGet, apiPost, apiPostStream } from '../api.js'
import { copyText, buildDatabricksNotebook, downloadFile, markdownToJira } from '../utils/exporters.js'

const STORAGE_KEY = 'rule_agent_chat_history'
const MODE_STORAGE_KEY = 'rule_agent_chat_mode'

const WELCOME_MESSAGES = {
  analyst:
    'Hello! I can explain any of the 228 Customer data quality rules in detail.\n\nAsk about a specific rule ID, describe what a rule does, or explore by category.',
  engineer:
    'Hello! You are in **Data Engineer** mode.\n\nPaste a user story or describe a rule change, and I will list the pipeline files to modify, the YAML to write, and how to test it. Answers can be downloaded as a Databricks notebook, and you can check edited pipeline YAML with the **Validate YAML** button above.',
  pm:
    'Hello! You are in **Project Manager** mode.\n\nDescribe a data quality issue or business need in plain language, and I will draft a user story for the engineering backlog — linked to any existing rules that already cover it. Finished drafts can be copied as Jira wiki markup.',
}

// `ts: null` doubles as the welcome marker for histories persisted before
// the isWelcome flag existed.
const initialMessagesFor = (mode) => [
  {
    role: 'agent',
    text: WELCOME_MESSAGES[mode] ?? WELCOME_MESSAGES.analyst,
    ts: null,
    isWelcome: true,
  },
]

const MODES = [
  { id: 'analyst', label: 'Analyst' },
  { id: 'engineer', label: 'Data Engineer' },
  { id: 'pm', label: 'Project Manager' },
]

function getStoredMode() {
  try {
    const stored = localStorage.getItem(MODE_STORAGE_KEY)
    if (stored && MODES.some(m => m.id === stored)) return stored
  } catch {}
  return 'analyst'
}

const MODE_SUGGESTIONS = {
  analyst: [
    'Find a rule that checks customer email is not empty',
    'Explain rule RCCOMP_103.1',
    'List all completeness rules',
    'Which rules check KNA1?',
  ],
  engineer: [
    'Paste a user story to see which files to change',
    'How do I change the threshold in rule RCACCU_383.6?',
    'Which pipeline files implement postal code checks?',
  ],
  pm: [
    'Customers are being created with invalid postal codes',
    'We need a check that customer emails are unique',
    'Help me write a story for tightening address validation',
  ],
}

const MODE_PLACEHOLDERS = {
  analyst: 'Ask about a rule, describe what it does, or follow up on a rule…',
  engineer: 'Paste the user story to implement — I will list the files to change and how to test it…',
  pm: 'Describe the issue or need in plain language — I will draft the user story…',
}

const MODE_HERO = {
  analyst: {
    title: 'How can I help you today?',
    sub: 'Ask about any Customer data quality rule — by ID, by what it checks, or by category. I will explain it in plain business language.',
  },
  engineer: {
    title: 'Data Engineer mode',
    sub: 'Paste a user story or describe a rule change. I will list the pipeline files to modify, the YAML to write, and how to test it — downloadable as a Databricks notebook.',
  },
  pm: {
    title: 'Project Manager mode',
    sub: 'Describe a data quality issue or business need in plain language. I will draft a user story for the engineering backlog, linked to any rules that already cover it.',
  },
}

const HeroMark = () => (
  <div className="hero-mark" aria-hidden="true">
    <svg width="26" height="26" viewBox="0 0 17 17" fill="none">
      <path
        d="M2 10.5C5.2 6.6 8.2 12.6 11.2 9.2c1.6-1.8 2.7-3.1 3.8-4.2"
        stroke="#fff" strokeWidth="1.9" strokeLinecap="round"
      />
    </svg>
  </div>
)

function ChatHero({ mode, onAsk }) {
  const { title, sub } = MODE_HERO[mode] ?? MODE_HERO.analyst
  return (
    <div className="chat-hero">
      <HeroMark />
      <h1 className="hero-title">{title}</h1>
      <p className="hero-sub">{sub}</p>
      <div className="hero-cards">
        {MODE_SUGGESTIONS[mode].map((s, i) => (
          <button key={i} className="hero-card" onClick={() => onAsk(s)}>
            <span className="hero-card-text">{s}</span>
            <span className="hero-card-arrow" aria-hidden="true">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 6h8M6.5 2.5L10 6l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

const RULE_ID_RE = /\b([A-Z]{2,8}_\d+(?:\.\d+)?)\b/g

function addRuleLinks(text) {
  return text.replace(RULE_ID_RE, (match) => `[${match}](#rule:${match})`)
}

function CodeBlockPre({ children }) {
  const preRef = useRef(null)
  const [copied, setCopied] = useState(false)

  async function copy() {
    const ok = await copyText(preRef.current?.innerText ?? '')
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    }
  }

  return (
    <div className="code-block-wrap">
      <button className={`code-copy-btn${copied ? ' copied' : ''}`} onClick={copy}>
        {copied ? 'Copied ✓' : 'Copy'}
      </button>
      <pre ref={preRef}>{children}</pre>
    </div>
  )
}

function makeMarkdownComponents(onRuleClick) {
  return {
    pre: CodeBlockPre,
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

const ThumbIcon = ({ down, filled }) => (
  <svg
    width="12" height="12" viewBox="0 0 12 12" fill={filled ? 'currentColor' : 'none'}
    style={down ? { transform: 'rotate(180deg)' } : undefined} aria-hidden="true"
  >
    <path d="M3.5 5.5v5H1.5v-5h2zm0 0l2.2-3.9a1 1 0 0 1 1.85.65L7.2 4.5h2.6a1 1 0 0 1 .97 1.24l-1 4a1 1 0 0 1-.97.76H3.5"
      stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
  </svg>
)

const DownloadIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M6 1.5v6M3.5 5L6 7.5 8.5 5M1.5 9.5v1h9v-1" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const CopyIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <rect x="3.5" y="3.5" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.2"/>
    <path d="M8.5 3.5v-1a1 1 0 0 0-1-1h-5a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1h1" stroke="currentColor" strokeWidth="1.2"/>
  </svg>
)

function MessageActions({ msg, onFeedback }) {
  const [jiraCopied, setJiraCopied] = useState(false)
  const [mdCopied, setMdCopied]     = useState(false)
  const notebook = msg.mode === 'engineer' ? buildDatabricksNotebook(msg.text) : null

  async function copyJira() {
    if (await copyText(markdownToJira(msg.text))) {
      setJiraCopied(true)
      setTimeout(() => setJiraCopied(false), 1600)
    }
  }

  async function copyMarkdown() {
    if (await copyText(msg.text)) {
      setMdCopied(true)
      setTimeout(() => setMdCopied(false), 1600)
    }
  }

  function downloadNotebook() {
    const name = msg.ruleId ?? new Date().toISOString().slice(0, 10)
    downloadFile(`validation_${name}.py`, notebook, 'text/x-python')
  }

  return (
    <div className="msg-actions">
      <Tooltip content="Good answer">
        <button
          className={`msg-feedback-btn${msg.feedback === 'up' ? ' active' : ''}`}
          onClick={() => onFeedback('up')}
          aria-label="Good answer"
          aria-pressed={msg.feedback === 'up'}
        >
          <ThumbIcon filled={msg.feedback === 'up'} />
        </button>
      </Tooltip>
      <Tooltip content="Bad answer">
        <button
          className={`msg-feedback-btn down${msg.feedback === 'down' ? ' active' : ''}`}
          onClick={() => onFeedback('down')}
          aria-label="Bad answer"
          aria-pressed={msg.feedback === 'down'}
        >
          <ThumbIcon down filled={msg.feedback === 'down'} />
        </button>
      </Tooltip>
      {notebook && (
        <Tooltip content="Download the SQL + PySpark validation cells as a Databricks notebook">
          <button className="msg-action-btn" onClick={downloadNotebook}>
            <DownloadIcon /> Databricks notebook
          </button>
        </Tooltip>
      )}
      {msg.mode === 'pm' && (
        <>
          <Tooltip content="Copy as Jira wiki markup">
            <button className="msg-action-btn" onClick={copyJira}>
              <CopyIcon /> {jiraCopied ? 'Copied ✓' : 'Copy for Jira'}
            </button>
          </Tooltip>
          <Tooltip content="Copy the raw markdown">
            <button className="msg-action-btn" onClick={copyMarkdown}>
              <CopyIcon /> {mdCopied ? 'Copied ✓' : 'Copy markdown'}
            </button>
          </Tooltip>
        </>
      )}
    </div>
  )
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  if (isToday) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const NBSP = ' '

export default function ChatBox({ onRuleLoaded, prefill, onPrefillConsumed, activeRuleId }) {
  const [messages, setMessages] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        if (Array.isArray(parsed) && parsed.length > 0) return parsed
      }
    } catch {}
    return initialMessagesFor(getStoredMode())
  })
  const [input, setInput]           = useState('')
  const [loading, setLoading]       = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [showValidator, setShowValidator] = useState(false)
  const [mode, setMode] = useState(getStoredMode)
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

  function switchMode(nextMode) {
    if (nextMode === mode || loading) return
    setMode(nextMode)
    try { localStorage.setItem(MODE_STORAGE_KEY, nextMode) } catch {}
    // If the chat is untouched, swap the welcome message to the new persona's
    setMessages(prev =>
      prev.length === 1 && prev[0].role === 'agent' && (prev[0].isWelcome || prev[0].ts === null)
        ? initialMessagesFor(nextMode)
        : prev
    )
    // Scope conversation history to the current mode (mirrors the activeRuleId reset)
    sessionStartRef.current = messages.length
  }

  function clearHistory() {
    if (!confirmClear) {
      setConfirmClear(true)
      setTimeout(() => setConfirmClear(false), 2500)
      return
    }
    setMessages(initialMessagesFor(mode))
    sessionStartRef.current = 0
    try { localStorage.removeItem(STORAGE_KEY) } catch {}
    setConfirmClear(false)
  }

  async function send(overrideText) {
    const text = (overrideText ?? input).trim()
    if (!text || loading) return

    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'

    // Build history from session window before appending the new user message
    const sessionMsgs = messages.slice(sessionStartRef.current)
    const MAX_HISTORY = 20
    const historyWindow = sessionMsgs.slice(-MAX_HISTORY)
    const history = historyWindow.map(m => ({
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.text.slice(0, 8000),
    }))

    // Insert user message and streaming placeholder atomically
    setMessages(prev => [
      ...prev,
      { role: 'user', text, ts: Date.now() },
      { role: 'agent', text: NBSP, ts: Date.now(), isStreaming: true, followups: [], mode },
    ])
    setLoading(true)

    try {
      const reader = await apiPostStream('/chat/stream', {
        message: text,
        context_rule_id: activeRuleId ?? null,
        mode,
        history,
      })

      const decoder = new TextDecoder('utf-8', { stream: true })
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Split on double-newline (SSE event boundary), keep incomplete tail in buffer
        const events = buffer.split('\n\n')
        buffer = events.pop() ?? ''

        for (const event of events) {
          const line = event.trim()
          if (!line.startsWith('data:')) continue

          let parsed
          try {
            parsed = JSON.parse(line.slice(5).trim())
          } catch {
            continue
          }

          if (parsed.type === 'status') {
            // Transient progress text (persona retrieval) — replaced by the first real chunk
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last?.isStreaming && (last.text === NBSP || last.isStatus)) {
                updated[updated.length - 1] = { ...last, text: parsed.text, isStatus: true }
              }
              return updated
            })
            await new Promise(r => setTimeout(r, 0))
          }

          if (parsed.type === 'chunk') {
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last?.isStreaming) {
                const existing = (last.text === NBSP || last.isStatus) ? '' : last.text
                updated[updated.length - 1] = { ...last, text: existing + parsed.text, isStatus: false }
              }
              return updated
            })
            // Yield to the event loop so React flushes this update before the next chunk
            await new Promise(r => setTimeout(r, 0))
          }

          if (parsed.type === 'done') {
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last?.isStreaming) {
                updated[updated.length - 1] = {
                  ...last,
                  // A bubble still showing transient status text has no real answer
                  text: last.isStatus ? '' : last.text,
                  isStatus: false,
                  isStreaming: false,
                  ts: Date.now(),
                  followups: parsed.suggested_followups ?? [],
                  ruleId: parsed.rule_id ?? null,
                }
              }
              return updated
            })
            if (parsed.rule_id) {
              const ruleRes = await apiGet(`/rule/${parsed.rule_id}`)
              if (ruleRes.ok) onRuleLoaded(await ruleRes.json())
            }
          }
        }
      }

      // Flush decoder and process any remaining buffer content
      const tail = decoder.decode()
      if (tail) buffer += tail
    } catch (err) {
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last?.isStreaming || (last?.role === 'agent' && last?.text === NBSP)) {
          updated[updated.length - 1] = {
            role: 'agent', text: `Error: ${err.message}`,
            isError: true, ts: Date.now(), followups: [],
          }
        } else {
          updated.push({
            role: 'agent', text: `Error: ${err.message}`,
            isError: true, ts: Date.now(), followups: [],
          })
        }
        return updated
      })
    } finally {
      setLoading(false)
      // If the stream ended without a done event, close any open streaming bubble
      setMessages(prev => {
        const last = prev[prev.length - 1]
        if (last?.isStreaming) {
          return [
            ...prev.slice(0, -1),
            { ...last, isStreaming: false, followups: [] },
          ]
        }
        return prev
      })
    }
  }

  function sendFeedback(index, msg, rating) {
    if (msg.feedback === rating) return
    setMessages(prev => prev.map((m, i) => (i === index ? { ...m, feedback: rating } : m)))
    apiPost('/feedback', {
      rating,
      mode: msg.mode ?? mode,
      rule_id: msg.ruleId ?? activeRuleId ?? null,
    }).catch(() => {})
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
  const isFreshChat =
    messages.length === 1 &&
    messages[0].role === 'agent' &&
    (messages[0].isWelcome || messages[0].ts === null)

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
        <div className="mode-toggle" role="tablist" aria-label="Assistant mode">
          {MODES.map(m => (
            <button
              key={m.id}
              role="tab"
              aria-selected={mode === m.id}
              className={`mode-toggle-btn${mode === m.id ? ' active' : ''}`}
              onClick={() => switchMode(m.id)}
              disabled={loading}
            >
              {m.label}
            </button>
          ))}
        </div>
        {mode === 'engineer' && (
          <Tooltip content="Check an edited pipeline YAML against the repository before committing">
            <button className="yaml-validate-open-btn" onClick={() => setShowValidator(true)}>
              Validate YAML
            </button>
          </Tooltip>
        )}
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
          {isFreshChat ? (
            <ChatHero mode={mode} onAsk={s => send(s)} />
          ) : (
          messages.map((msg, i) =>
            (msg.isWelcome || (msg.role === 'agent' && msg.ts === null)) ? null : (
            <div key={i} className={`msg-row ${msg.role}`}>
              {msg.role === 'agent' && (
                <div className="msg-avatar agent-avatar"><AgentIcon /></div>
              )}
              <div className="msg-content">
                <div className={`bubble ${msg.role}${msg.isError ? ' error' : ''}`}>
                  {msg.role === 'agent' && !msg.isError ? (
                    <div className="md-body">
                      {msg.isStreaming ? (
                        <p>
                          {msg.isStatus ? <em className="status-text">{msg.text}</em> : msg.text}
                          <span className="streaming-cursor" aria-hidden="true" />
                        </p>
                      ) : (
                        <ReactMarkdown components={mdComponents}>
                          {addRuleLinks(msg.text)}
                        </ReactMarkdown>
                      )}
                    </div>
                  ) : (
                    <p style={{ whiteSpace: 'pre-line' }}>{msg.text}</p>
                  )}
                </div>
                {msg.role === 'agent' && !msg.isError && !msg.isStreaming && msg.mode && msg.text && (
                  <MessageActions msg={msg} onFeedback={rating => sendFeedback(i, msg, rating)} />
                )}
                {!msg.isStreaming && msg.followups?.length > 0 && (
                  <div className="followup-chips">
                    {msg.followups.map((q, qi) => (
                      <button key={qi} className="followup-chip" onClick={() => send(q)}>{q}</button>
                    ))}
                  </div>
                )}
                {msg.ts && !msg.isStreaming && (
                  <span className={`msg-time ${msg.role}`}>{formatTime(msg.ts)}</span>
                )}
              </div>
              {msg.role === 'user' && (
                <div className="msg-avatar user-avatar"><UserIcon /></div>
              )}
            </div>
          ))
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {showValidator && <YamlValidator onClose={() => setShowValidator(false)} />}

      <div className="chat-input-row">
        <div className="chat-input-inner">
          <div className="input-wrap" onClick={() => textareaRef.current?.focus()}>
            <textarea
              ref={textareaRef}
              className="chat-input"
              value={input}
              onChange={onInputChange}
              onKeyDown={onKey}
              placeholder={MODE_PLACEHOLDERS[mode]}
              rows={mode === 'analyst' ? 1 : 3}
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
