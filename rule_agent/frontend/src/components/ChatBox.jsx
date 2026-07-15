import { useState, useRef, useEffect, useLayoutEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Tooltip from './Tooltip.jsx'
import YamlValidator from './YamlValidator.jsx'
import RichInput from './RichInput.jsx'
import { apiGet, apiPost, apiPostStream, getConversation, createConversation } from '../api.js'
import { copyText, buildDatabricksNotebook, downloadFile, markdownToJira } from '../utils/exporters.js'

const MODE_STORAGE_KEY = 'rule_agent_chat_mode'
const GENERAL_STORAGE_KEY = 'rule_agent_general_mode'

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

// Map a server conversation (with messages) to the internal message shape.
function mapConversationMessages(detail) {
  const msgs = detail?.messages ?? []
  if (msgs.length === 0) return initialMessagesFor(detail?.persona ?? 'analyst')
  return msgs.map(m => ({
    role: m.role === 'assistant' ? 'agent' : 'user',
    text: m.content,
    ts: m.created_at ? Date.parse(m.created_at) : Date.now(),
    followups: m.suggested_followups ?? [],
    mode: m.role === 'assistant' ? (detail.persona ?? 'analyst') : undefined,
    ruleId: m.rule_id ?? null,
  }))
}

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
    'Which other rules does RCCOMP_149.2 impact?',
  ],
  pm: [
    'Customers are being created with invalid postal codes',
    'We need a check that customer emails are unique',
    'Help me write a story for tightening address validation',
    'Duplicate customer records are reaching reporting',
  ],
}

const MODE_PLACEHOLDERS = {
  analyst: 'Ask about a rule, describe what it does, or follow up on a rule…',
  engineer: 'Paste a user story or describe a rule change…',
  pm: 'Describe the issue or need in plain language…',
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
  // Rule IDs inside fenced blocks or inline code must stay literal — link
  // syntax injected there renders as raw [ID](#rule:ID) text in the code.
  return text
    .split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/)
    .map(seg =>
      seg.startsWith('`') ? seg : seg.replace(RULE_ID_RE, (match) => `[${match}](#rule:${match})`)
    )
    .join('')
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

export default function ChatBox({
  onRuleLoaded, prefill, onPrefillConsumed, activeRuleId,
  conversationId = null,
  conversationPersona = null,
  projectId = null,
  onConversationCreated,
  onConversationUpdated,
  onStartNewChat,
}) {
  const [messages, setMessages] = useState(() => initialMessagesFor(getStoredMode()))
  const [loading, setLoading]       = useState(false)
  const [showValidator, setShowValidator] = useState(false)
  const [mode, setMode] = useState(conversationPersona ?? getStoredMode)
  const [generalMode, setGeneralMode] = useState(() => {
    try { return localStorage.getItem(GENERAL_STORAGE_KEY) === '1' } catch {}
    return false
  })
  const [editorHasContent, setEditorHasContent] = useState(false)
  const bottomRef        = useRef(null)
  const richInputRef     = useRef(null)
  const loadedConvRef    = useRef(null)   // conversation id whose messages are in state
  const modeRef          = useRef(mode)
  const sliderRef        = useRef(null)
  const modeBtnRefs      = useRef({})

  useEffect(() => { modeRef.current = mode }, [mode])

  // Sync the persona toggle to the active conversation's persona.
  useEffect(() => {
    if (conversationId != null && conversationPersona) setMode(conversationPersona)
  }, [conversationId, conversationPersona])

  // Load messages when the active conversation changes (skip if ChatBox just
  // created it during send — loadedConvRef already points at it).
  useEffect(() => {
    let cancelled = false
    if (conversationId == null) {
      loadedConvRef.current = null
      setMessages(initialMessagesFor(modeRef.current))
      return
    }
    if (conversationId === loadedConvRef.current) return
    ;(async () => {
      try {
        const detail = await getConversation(conversationId)
        if (cancelled) return
        loadedConvRef.current = conversationId
        setMessages(mapConversationMessages(detail))
      } catch {}
    })()
    return () => { cancelled = true }
  }, [conversationId, conversationPersona])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  useEffect(() => {
    richInputRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!loading) richInputRef.current?.focus()
  }, [loading])

  // Position slider before first paint (no animation)
  useLayoutEffect(() => {
    const slider = sliderRef.current
    const btn = modeBtnRefs.current[mode]
    if (!slider || !btn) return
    slider.style.transitionDuration = '0s'
    slider.style.left  = `${btn.offsetLeft}px`
    slider.style.width = `${btn.offsetWidth}px`
    void slider.offsetWidth   // force reflow before re-enabling
    slider.style.transitionDuration = ''
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Slide to new position on mode change (after paint so CSS transition fires)
  useEffect(() => {
    const slider = sliderRef.current
    const btn = modeBtnRefs.current[mode]
    if (!slider || !btn) return
    slider.style.left  = `${btn.offsetLeft}px`
    slider.style.width = `${btn.offsetWidth}px`
  }, [mode])

  useEffect(() => {
    if (prefill) {
      richInputRef.current?.setContent(prefill)
      onPrefillConsumed?.()
    }
  }, [prefill]) // eslint-disable-line react-hooks/exhaustive-deps

  // Switching persona starts a separate thread (a conversation is bound to one
  // persona). Deselect the current conversation and reset to a fresh draft.
  function switchMode(nextMode) {
    if (nextMode === mode || loading) return
    setMode(nextMode)
    try { localStorage.setItem(MODE_STORAGE_KEY, nextMode) } catch {}
    loadedConvRef.current = null
    setMessages(initialMessagesFor(nextMode))
    onStartNewChat?.(nextMode)
  }

  function toggleGeneralMode() {
    if (loading) return
    setGeneralMode(prev => {
      const next = !prev
      try { localStorage.setItem(GENERAL_STORAGE_KEY, next ? '1' : '0') } catch {}
      return next
    })
  }

  // "New chat" — drop the active conversation and start a fresh draft (same persona).
  function newChat() {
    if (loading) return
    loadedConvRef.current = null
    setMessages(initialMessagesFor(mode))
    onStartNewChat?.(mode)
  }

  async function send(overrideText) {
    let text
    if (overrideText !== undefined) {
      text = overrideText.trim()
    } else {
      text = richInputRef.current?.getMarkdown()?.trim() ?? ''
      if (text) richInputRef.current?.clear()
    }
    if (!text || loading) return

    // Ensure a server-side conversation exists; history is loaded from the DB,
    // so the client no longer sends a history window.
    let cid = conversationId
    let createdConv = null
    if (cid == null) {
      try {
        createdConv = await createConversation({ persona: mode, project_id: projectId ?? null })
        cid = createdConv.id
        loadedConvRef.current = cid
      } catch {
        // fall through with cid=null → backend stays stateless for this turn
      }
    }

    // Insert user message and streaming placeholder atomically
    setMessages(prev => [
      ...prev,
      { role: 'user', text, ts: Date.now() },
      { role: 'agent', text: NBSP, ts: Date.now(), isStreaming: true, followups: [], mode },
    ])
    setLoading(true)
    if (createdConv) onConversationCreated?.(createdConv)

    try {
      const reader = await apiPostStream('/chat/stream', {
        message: text,
        context_rule_id: activeRuleId ?? null,
        mode,
        history: [],
        general: mode === 'analyst' && generalMode,
        conversation_id: cid,
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
      // Refresh the sidebar so the new conversation, its preview, and the
      // auto-generated title appear.
      if (cid != null) onConversationUpdated?.()
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

  const mdComponents = makeMarkdownComponents(handleRuleLinkClick)
  const userMsgCount  = messages.filter(m => m.role === 'user').length
  const hasHistory    = messages.length > 1
  const isFreshChat   =
    messages.length === 1 &&
    messages[0].role === 'agent' &&
    (messages[0].isWelcome || messages[0].ts === null)
  const currentPlaceholder =
    mode === 'analyst' && generalMode
      ? 'Ask anything — rules, data quality concepts, tools, process…'
      : MODE_PLACEHOLDERS[mode]

  return (
    <div className="chat-container">
      <div className="chat-panel-header">
        <div className="chat-header-left">
          <span className="chat-panel-label">AI Assistant</span>
          <div className="chat-panel-live">
            <span className="chat-panel-live-dot" />
            <span className="chat-panel-live-label">Live</span>
          </div>
          {activeRuleId && (
            <span className="active-rule-chip" title={`Rule ${activeRuleId} is in context`}>
              <span className="active-rule-chip-dot" aria-hidden="true" />
              {activeRuleId}
            </span>
          )}
          {userMsgCount > 0 && (
            <span className="chat-msg-count">{userMsgCount}</span>
          )}
        </div>

        <div className="chat-header-center">
          <div className="mode-toggle" data-tour="modes" role="tablist" aria-label="Assistant mode">
            <div className="mode-toggle-slider" ref={sliderRef} aria-hidden="true" />
            {MODES.map(m => (
              <button
                key={m.id}
                ref={el => { modeBtnRefs.current[m.id] = el }}
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
        </div>

        <div className="chat-header-right">
          {hasHistory ? (
            <Tooltip content="Start a new chat">
              <button className="clear-btn" onClick={newChat}>
                <TrashIcon />New chat
              </button>
            </Tooltip>
          ) : (
            /* Invisible placeholder keeps the header from reflowing when the
               first message arrives. */
            <button className="clear-btn is-hidden" tabIndex={-1} aria-hidden="true">
              <TrashIcon />New chat
            </button>
          )}
          {mode === 'analyst' && (
            <Tooltip
              content={
                generalMode
                  ? 'General Q&A is ON — I can also answer questions beyond the rule catalog (git, Databricks, data quality concepts…). Click to return to rules only.'
                  : 'Rules only — click to also allow general questions beyond the rule catalog'
              }
            >
              <button
                className={`header-action-btn${generalMode ? ' active' : ''}`}
                onClick={toggleGeneralMode}
                disabled={loading}
                aria-pressed={generalMode}
              >
                <span className={`action-dot${generalMode ? ' on' : ''}`} aria-hidden="true" />
                General Q&A
              </button>
            </Tooltip>
          )}
          {mode === 'engineer' && (
            <Tooltip content="Check an edited pipeline YAML against the repository before committing">
              <button className="header-action-btn" onClick={() => setShowValidator(true)}>
                Validate YAML
              </button>
            </Tooltip>
          )}
        </div>
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
                {msg.role === 'agent' && !msg.isError && msg.isStreaming && msg.text === NBSP && !msg.isStatus ? (
                  // Initial wait state — compact typing-dots bubble instead of a huge empty box
                  <div className="bubble agent bubble-typing" aria-label="Thinking…">
                    <div className="typing-dots">
                      <span /><span /><span />
                    </div>
                  </div>
                ) : (
                <div className={`bubble ${msg.role}${msg.isError ? ' error' : ''}`}>
                  {msg.role === 'agent' && !msg.isError ? (
                    <div className="md-body">
                      {msg.isStreaming && msg.isStatus ? (
                        // Transient progress line — plain italic, not markdown
                        <p>
                          <em className="status-text">{msg.text}</em>
                          <span className="streaming-cursor" aria-hidden="true" />
                        </p>
                      ) : msg.isStreaming ? (
                        // Answer text: render markdown live so it's formatted as it streams
                        <>
                          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                            {addRuleLinks(msg.text)}
                          </ReactMarkdown>
                          <span className="streaming-cursor" aria-hidden="true" />
                        </>
                      ) : (
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                          {addRuleLinks(msg.text)}
                        </ReactMarkdown>
                      )}
                    </div>
                  ) : (
                    <div className="md-body">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
                    </div>
                  )}
                </div>
                )}
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
          <div className="input-wrap" data-tour="chat-input" onClick={() => richInputRef.current?.focus()}>
            <RichInput
              ref={richInputRef}
              onSend={() => send()}
              placeholder={currentPlaceholder}
              disabled={loading}
              onIsEmptyChange={(empty) => setEditorHasContent(!empty)}
            />
            <Tooltip content="Send message (Enter)">
              <button
                className="send-btn"
                onClick={() => send()}
                disabled={loading || !editorHasContent}
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
