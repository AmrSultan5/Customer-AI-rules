import { useState, useRef, useEffect, useMemo } from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Tooltip from './Tooltip.jsx'
import RichInput from './RichInput.jsx'
import { apiPost, apiPostStream, getConversation, createConversation } from '../api.js'
import { notifyError } from '../utils/toast.js'
import { copyText } from '../utils/exporters.js'

// react-markdown's default urlTransform sanitizes/strips unknown URL schemes
// (including our custom "rule:" scheme used for rule-id links). Preserve it
// so those links keep routing to the rule card instead of falling through to
// a stripped, empty href.
const ruleUrlTransform = (url) => (url && url.startsWith('rule:') ? url : defaultUrlTransform(url))

const WELCOME_MESSAGE =
  'Hello! Ask me anything about this knowledge base — describe what you\'re looking for, ' +
  'or ask a specific question, and I\'ll ground my answer in the underlying data.'

// `ts: null` doubles as the welcome marker for histories persisted before
// the isWelcome flag existed.
const initialMessages = () => [
  { role: 'agent', text: WELCOME_MESSAGE, ts: null, isWelcome: true },
]

// Map a server conversation (with messages) to the internal message shape.
function mapConversationMessages(detail) {
  const msgs = detail?.messages ?? []
  if (msgs.length === 0) return initialMessages()
  return msgs.map(m => ({
    role: m.role === 'assistant' ? 'agent' : 'user',
    text: m.content,
    ts: m.created_at ? Date.parse(m.created_at) : Date.now(),
    followups: m.suggested_followups ?? [],
    ruleId: m.rule_id ?? null,
  }))
}

const SUGGESTIONS = [
  'What can you help me with?',
  'Summarize what this knowledge base covers',
  'What are the most important things to know?',
  'Explain a specific topic in detail',
]

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

function ChatHero({ kbName, onAsk }) {
  return (
    <div className="chat-hero">
      <HeroMark />
      <h1 className="hero-title">How can I help you today?</h1>
      <p className="hero-sub">
        {kbName ? `Ask me anything about ${kbName}.` : 'Ask me anything about this knowledge base.'}
      </p>
      <div className="hero-cards">
        {SUGGESTIONS.map((s, i) => (
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

// Entity-id auto-linking (rule cards). Rule IDs in agent answers become
// clickable links (href "rule:<id>") that open the rule card — only when the
// active KB is entity-capable (onRuleSelected is provided). Code spans/blocks
// are left untouched.
const RULE_ID_RE = /\b([A-Z]{2,8}_\d+(?:\.\d+)?)\b/g

function linkifyRules(text, enabled) {
  if (!enabled || !text) return text
  return text
    .split(/(```[\s\S]*?```|`[^`]*`)/g)
    .map(seg => (seg.startsWith('`') ? seg : seg.replace(RULE_ID_RE, m => `[${m}](rule:${m})`)))
    .join('')
}

function makeMdComponents(onRuleSelected) {
  return {
    pre: CodeBlockPre,
    a: ({ href, children }) => {
      if (href && href.startsWith('rule:')) {
        const id = href.slice(5)
        return (
          <a className="rule-link" href="#"
            onClick={e => { e.preventDefault(); onRuleSelected?.(id) }}>
            {children}
          </a>
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

const ThumbIcon = ({ down, filled }) => (
  <svg
    width="12" height="12" viewBox="0 0 12 12" fill={filled ? 'currentColor' : 'none'}
    style={down ? { transform: 'rotate(180deg)' } : undefined} aria-hidden="true"
  >
    <path d="M3.5 5.5v5H1.5v-5h2zm0 0l2.2-3.9a1 1 0 0 1 1.85.65L7.2 4.5h2.6a1 1 0 0 1 .97 1.24l-1 4a1 1 0 0 1-.97.76H3.5"
      stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
  </svg>
)

const CopyIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <rect x="3.5" y="3.5" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.2"/>
    <path d="M8.5 3.5v-1a1 1 0 0 0-1-1h-5a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1h1" stroke="currentColor" strokeWidth="1.2"/>
  </svg>
)

function MessageActions({ msg, onFeedback }) {
  const [mdCopied, setMdCopied] = useState(false)

  async function copyMarkdown() {
    if (await copyText(msg.text)) {
      setMdCopied(true)
      setTimeout(() => setMdCopied(false), 1600)
    }
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
      <Tooltip content="Copy the raw markdown">
        <button className="msg-action-btn" onClick={copyMarkdown}>
          <CopyIcon /> {mdCopied ? 'Copied ✓' : 'Copy'}
        </button>
      </Tooltip>
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

const NBSP = ' '

export default function ChatBox({
  conversationId = null,
  projectId = null,
  activeKbId = null,
  activeKb = null,
  onConversationCreated,
  onConversationUpdated,
  onRuleSelected = null,
  prefill = null,
}) {
  const md = useMemo(() => makeMdComponents(onRuleSelected), [onRuleSelected])
  // A repo-backed KB that's queued/ingesting (a reload in progress on the KB
  // you're currently chatting in) — keep the conversation but freeze input
  // until it flips back to "ready". Static KBs are always "ready", so this
  // never triggers for them.
  const kbUpdating = activeKb?.status === 'queued' || activeKb?.status === 'ingesting'
  // A repo-backed KB whose last reload failed but that still has previous
  // content being served — non-blocking: the chat keeps working against the
  // old version, so only a warning banner shows (input stays enabled).
  const kbStale = activeKb?.status === 'error'
  const [messages, setMessages] = useState(() => initialMessages())
  const [loading, setLoading] = useState(false)
  const [editorHasContent, setEditorHasContent] = useState(false)
  const bottomRef        = useRef(null)
  const richInputRef     = useRef(null)
  const loadedConvRef    = useRef(null)   // conversation id whose messages are in state
  const lastPrefillRef   = useRef(null)   // prefill token already sent (avoid re-send)

  // Load messages when the active conversation changes (skip if ChatBox just
  // created it during send — loadedConvRef already points at it).
  useEffect(() => {
    let cancelled = false
    if (conversationId == null) {
      loadedConvRef.current = null
      setMessages(initialMessages())
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
  }, [conversationId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  useEffect(() => {
    richInputRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!loading) richInputRef.current?.focus()
  }, [loading])

  async function send(overrideText) {
    let text
    if (overrideText !== undefined) {
      text = overrideText.trim()
    } else {
      text = richInputRef.current?.getMarkdown()?.trim() ?? ''
      if (text) richInputRef.current?.clear()
    }
    if (!text || loading || kbUpdating) return

    // Ensure a server-side conversation exists; history is loaded from the DB,
    // so the client no longer sends a history window.
    let cid = conversationId
    let createdConv = null
    if (cid == null) {
      try {
        createdConv = await createConversation({
          project_id: projectId ?? null,
          knowledge_base_id: activeKbId ?? null,
        })
        cid = createdConv.id
        loadedConvRef.current = cid
      } catch {
        // Persistence is down (e.g. a locked/unreachable DB). We still answer
        // this turn statelessly, but the user MUST be told — otherwise the chat
        // silently loses all memory of previous turns with no indication why.
        notifyError('Couldn’t save this chat — your messages won’t be remembered after you leave this page.')
      }
    }

    // Insert user message and streaming placeholder atomically
    setMessages(prev => [
      ...prev,
      { role: 'user', text, ts: Date.now() },
      { role: 'agent', text: NBSP, ts: Date.now(), isStreaming: true, followups: [] },
    ])
    setLoading(true)
    if (createdConv) onConversationCreated?.(createdConv)

    // KB-scoped route (falls back to the pinned/active KB server-side when
    // the switcher is disabled, so it's always safe to pass through).
    const streamPath = activeKbId ? `/kb/${activeKbId}/chat/stream` : '/chat/stream'

    try {
      const reader = await apiPostStream(streamPath, {
        message: text,
        general: false,
        history: [],
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
            // Transient progress text — replaced by the first real chunk
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
            // Open the rule card for the resolved entity (entity-capable KBs).
            if (parsed.rule_id && onRuleSelected) onRuleSelected(parsed.rule_id)
          }
        }
      }

      // Flush decoder and process any remaining buffer content
      const tail = decoder.decode()
      if (tail) buffer += tail
    } catch (err) {
      // A 409 means the KB flipped to queued/ingesting mid-flight (e.g. a
      // reload started right after this send went out) — surface it like
      // any other stream error rather than a raw status code.
      const isKbUpdating = /\b409\b/.test(err.message)
      const errText = isKbUpdating
        ? 'This knowledge base is updating — please wait for it to finish, then try again.'
        : `Error: ${err.message}`
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last?.isStreaming || (last?.role === 'agent' && last?.text === NBSP)) {
          updated[updated.length - 1] = {
            role: 'agent', text: errText,
            isError: true, ts: Date.now(), followups: [],
          }
        } else {
          updated.push({
            role: 'agent', text: errText,
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
    const feedbackPath = activeKbId ? `/kb/${activeKbId}/feedback` : '/feedback'
    apiPost(feedbackPath, {
      rating,
      rule_id: msg.ruleId ?? null,
    }).catch(() => {})
  }

  // "Ask about this rule" (from the rule card) → send that question.
  useEffect(() => {
    if (!prefill?.id || lastPrefillRef.current === prefill.id) return
    lastPrefillRef.current = prefill.id
    if (prefill.text) send(prefill.text)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill])

  const userMsgCount  = messages.filter(m => m.role === 'user').length
  const isFreshChat   =
    messages.length === 1 &&
    messages[0].role === 'agent' &&
    (messages[0].isWelcome || messages[0].ts === null)

  return (
    <div className="chat-container">
      <div className="chat-panel-header">
        <div className="chat-header-left">
          <span className="chat-panel-label">AI Assistant</span>
          <div className="chat-panel-live">
            <span className="chat-panel-live-dot" />
            <span className="chat-panel-live-label">Live</span>
          </div>
          {userMsgCount > 0 && (
            <span className="chat-msg-count">{userMsgCount}</span>
          )}
        </div>
      </div>

      <div className="chat-history">
        <div className="chat-history-inner">
          {isFreshChat ? (
            <ChatHero kbName={activeKb?.name} onAsk={s => send(s)} />
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
                          <ReactMarkdown remarkPlugins={[remarkGfm]} components={md} urlTransform={ruleUrlTransform}>
                            {linkifyRules(msg.text, !!onRuleSelected)}
                          </ReactMarkdown>
                          <span className="streaming-cursor" aria-hidden="true" />
                        </>
                      ) : (
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={md} urlTransform={ruleUrlTransform}>
                          {linkifyRules(msg.text, !!onRuleSelected)}
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
                {msg.role === 'agent' && !msg.isError && !msg.isStreaming && msg.text && (
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

      <div className="chat-input-row">
        <div className="chat-input-inner">
          {kbUpdating && (
            <div className="chat-kb-updating-banner" role="status">
              Updating this knowledge base — you can chat again once it's ready.
            </div>
          )}
          {!kbUpdating && kbStale && (
            <div className="chat-kb-stale-banner" role="status">
              Last update failed: {activeKb?.status_detail || 'The last update to this knowledge base failed.'} Still answering from the previous version.
            </div>
          )}
          <div
            className={`input-wrap${kbUpdating ? ' input-wrap-disabled' : ''}`}
            data-tour="chat-input"
            onClick={() => !kbUpdating && richInputRef.current?.focus()}
          >
            <RichInput
              ref={richInputRef}
              onSend={() => send()}
              placeholder="Ask a question about the knowledge base…"
              disabled={loading || kbUpdating}
              onIsEmptyChange={(empty) => setEditorHasContent(!empty)}
            />
            <Tooltip content="Send message (Enter)">
              <button
                className="send-btn"
                onClick={() => send()}
                disabled={loading || !editorHasContent || kbUpdating}
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
