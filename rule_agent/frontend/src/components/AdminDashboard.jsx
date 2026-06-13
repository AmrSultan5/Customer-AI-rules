import { useState, useEffect, useCallback, useRef } from 'react'
import { apiFetch } from '../api.js'

// ── Icons ──────────────────────────────────────────────────────────────────
export const RefreshIcon = ({ spinning }) => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true"
    style={{ animation: spinning ? 'adm-spin 0.7s linear infinite' : 'none', display: 'block' }}>
    <path d="M11 6.5A4.5 4.5 0 1 1 6.5 2M6.5 2L9 4.5M6.5 2L4 4.5"
      stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const ZapIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <path d="M7.5 1.5L2 7.5h4.5L5.5 11.5l6-6.5H7L7.5 1.5z"
      stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/>
  </svg>
)

const DatabaseIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <ellipse cx="6.5" cy="3" rx="4.5" ry="1.8" stroke="currentColor" strokeWidth="1.2"/>
    <path d="M2 3v7c0 1 2 1.8 4.5 1.8S11 11 11 10V3" stroke="currentColor" strokeWidth="1.2"/>
    <path d="M2 6.5c0 1 2 1.8 4.5 1.8S11 7.5 11 6.5" stroke="currentColor" strokeWidth="1.2"/>
  </svg>
)

const ClockIcon = () => (
  <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M6 3.5V6l1.5 1.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
  </svg>
)

// ── Charts ─────────────────────────────────────────────────────────────────

function HorizontalBarChart({ data, maxBars = 10 }) {
  if (!data.length) return <EmptyChart label="No rule views yet — start exploring rules to populate this chart" />
  const slice  = data.slice(0, maxBars)
  const maxVal = Math.max(...slice.map(d => d.views), 1)
  const ROW_H  = 30
  const LABEL_W = 150
  const BAR_W   = 580
  const COUNT_W = 46
  const SVG_W   = LABEL_W + BAR_W + COUNT_W
  const SVG_H   = slice.length * ROW_H

  return (
    <svg viewBox={`0 0 ${SVG_W} ${SVG_H}`} className="adm-bar-svg" aria-label="Top rules bar chart">
      {slice.map((d, i) => {
        const filled = Math.max(4, (d.views / maxVal) * BAR_W)
        const y      = i * ROW_H
        const isTop  = i === 0
        return (
          <g key={d.rule_id} transform={`translate(0,${y})`}>
            <text x={LABEL_W - 10} y={ROW_H / 2 + 4} textAnchor="end" className="adm-bar-label"
              style={{ fill: isTop ? 'var(--accent)' : 'var(--text-secondary)', fontWeight: isTop ? 600 : 400 }}>
              {d.rule_id}
            </text>
            <rect x={LABEL_W} y={ROW_H / 2 - 7} width={BAR_W} height={14} rx={5} fill="var(--adm-track)"/>
            <rect x={LABEL_W} y={ROW_H / 2 - 7} width={filled} height={14} rx={5}
              fill={isTop ? 'var(--accent)' : 'var(--adm-bar)'}/>
            <text x={LABEL_W + BAR_W + 8} y={ROW_H / 2 + 4} className="adm-bar-count"
              style={{ fill: isTop ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
              {d.views}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function Sparkline({ data }) {
  if (!data.length) return <EmptyChart label="No activity data yet" height={70} />
  const W = 1200; const H = 110; const PAD = 8
  const maxV = Math.max(...data.map(d => d.views), 1)
  const pts = data.map((d, i) => [
    PAD + (i / Math.max(data.length - 1, 1)) * (W - PAD * 2),
    H - PAD - (d.views / maxV) * (H - PAD * 2),
  ])
  const area = [`M${pts[0][0]} ${H}`, ...pts.map(([x, y]) => `L${x} ${y}`), `L${pts.at(-1)[0]} ${H}`, 'Z'].join(' ')
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x} ${y}`).join(' ')

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="adm-sparkline" aria-label="30-day activity sparkline">
      <defs>
        <linearGradient id="adm-spark-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.28"/>
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0"/>
        </linearGradient>
      </defs>
      <path d={area} fill="url(#adm-spark-grad)"/>
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx={pts.at(-1)[0]} cy={pts.at(-1)[1]} r="4" fill="var(--accent)"/>
    </svg>
  )
}

function CoverageArc({ pct }) {
  const r = 42; const cx = 56; const cy = 56
  const circ  = 2 * Math.PI * r
  const filled = (pct / 100) * circ
  return (
    <svg viewBox="0 0 112 112" className="adm-donut" aria-label={`Coverage ${pct}%`}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--adm-track)" strokeWidth="9"/>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--accent)" strokeWidth="9"
        strokeDasharray={`${filled} ${circ}`} strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ transition: 'stroke-dasharray 1s ease' }}/>
      <text x={cx} y={cy - 2} textAnchor="middle" className="adm-donut-pct">{pct}%</text>
      <text x={cx} y={cy + 15} textAnchor="middle" className="adm-donut-label">Covered</text>
    </svg>
  )
}

function EmptyChart({ label, height = 160 }) {
  return (
    <div className="adm-empty-chart" style={{ minHeight: height }}>
      <span className="adm-empty-chart-label">{label}</span>
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────

function formatTokens(n) {
  if (n == null || n === undefined) return undefined
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatCost(n) {
  if (n == null) return null
  if (n > 0 && n < 0.01) return '< $0.01'
  return `$${n.toFixed(2)}`
}

// Backend daily_activity only includes days that have rows; fill the gaps so
// the 30-day sparkline has a true time axis. Dates are UTC to match the
// backend's DATE(viewed_at) over ISO-8601 UTC timestamps.
function fillDailySeries(raw, days = 30) {
  const byDate = new Map(raw.map(d => [d.date, d.views]))
  return Array.from({ length: days }, (_, i) => {
    const date = new Date(Date.now() - (days - 1 - i) * 86_400_000).toISOString().slice(0, 10)
    return { date, views: byDate.get(date) ?? 0 }
  })
}

function prettyIntent(intent) {
  return String(intent).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const MODE_LABELS = {
  analyst:  'Analyst',
  engineer: 'Data Engineer',
  pm:       'Project Manager',
}

const CALL_TYPE_LABELS = {
  explain_rule: 'Rule Explanation',
  chat:         'Chat',
  stream:       'Chat (Streaming)',
  other:        'Other',
}

// ── Stat (KPI band cell) ───────────────────────────────────────────────────

function Stat({ label, value, sub, accent }) {
  const isLoading = value === undefined
  return (
    <div className={`adm-stat${accent ? ' adm-stat-accent' : ''}`}>
      <span className="adm-stat-label">{label}</span>
      {isLoading
        ? <span className="adm-skeleton-row" style={{ width: '58%', height: 28 }} />
        : <span className="adm-stat-value">{value}</span>
      }
      <span className="adm-stat-sub">{sub || ' '}</span>
    </div>
  )
}

// ── Recent Activity ────────────────────────────────────────────────────────

function timeAgo(iso) {
  const s = Math.floor((Date.now() - new Date(iso)) / 1000)
  if (s < 60)  return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function RecentActivity({ views }) {
  if (!views.length) return (
    <EmptyChart label="No activity recorded yet" height={120} />
  )
  return (
    <ul className="adm-activity-list">
      {views.map((v, i) => (
        <li key={i} className="adm-activity-item">
          <span className="adm-activity-rule">{v.rule_id}</span>
          <span className="adm-activity-time"><ClockIcon />{timeAgo(v.viewed_at)}</span>
        </li>
      ))}
    </ul>
  )
}

// ── Chat intents ───────────────────────────────────────────────────────────

function IntentBars({ items }) {
  if (!items.length) return <EmptyChart label="No chat intents recorded yet" height={120} />
  const max = Math.max(...items.map(d => d.count), 1)
  return (
    <ul className="adm-bar-list">
      {items.map(d => (
        <li key={d.intent} className="adm-bar-list-item">
          <span className="adm-bar-list-label">{prettyIntent(d.intent)}</span>
          <span className="adm-bar-list-track">
            <span className="adm-bar-list-fill" style={{ width: `${(d.count / max) * 100}%` }} />
          </span>
          <span className="adm-bar-list-count">{d.count}</span>
        </li>
      ))}
    </ul>
  )
}

// ── Trending rules (sustained interest over 30 days) ──────────────────────

function TrendingRules({ rules }) {
  if (!rules.length) return (
    <EmptyChart label="No trend data yet — needs views across multiple days" height={120} />
  )
  return (
    <ul className="adm-activity-list">
      {rules.map(r => (
        <li key={r.rule_id} className="adm-activity-item">
          <span className="adm-activity-rule">{r.rule_id}</span>
          <span className="adm-activity-time">
            {r.active_days} active day{r.active_days === 1 ? '' : 's'}
          </span>
        </li>
      ))}
    </ul>
  )
}

// ── Feedback split by chat mode ────────────────────────────────────────────

function FeedbackByMode({ byMode }) {
  const agg = {}
  for (const r of byMode) {
    const m = agg[r.mode] ?? (agg[r.mode] = { up: 0, down: 0 })
    if (r.rating === 'up')   m.up   += r.count
    if (r.rating === 'down') m.down += r.count
  }
  const rows = Object.entries(agg)
    .map(([mode, v]) => ({ mode, ...v, total: v.up + v.down }))
    .filter(r => r.total > 0)
    .sort((a, b) => b.total - a.total)

  if (!rows.length) return <EmptyChart label="No feedback votes yet" height={120} />
  return (
    <ul className="adm-mode-list">
      {rows.map(r => {
        const pct = Math.round((r.up / r.total) * 100)
        return (
          <li key={r.mode} className="adm-mode-item">
            <div className="adm-mode-top">
              <span className="adm-mode-name">{MODE_LABELS[r.mode] ?? r.mode}</span>
              <span className="adm-mode-stats">{r.up} up · {r.down} down · {pct}% positive</span>
            </div>
            <div className="adm-mode-track">
              <div className="adm-mode-fill" style={{ width: `${pct}%` }} />
            </div>
          </li>
        )
      })}
    </ul>
  )
}

// ── Most downvoted rules ───────────────────────────────────────────────────

function DownvotedRules({ rules }) {
  if (!rules.length) return (
    <EmptyChart label="No downvoted answers — nothing needs attention" height={120} />
  )
  return (
    <ul className="adm-activity-list">
      {rules.map(r => (
        <li key={r.rule_id} className="adm-activity-item">
          <span className="adm-activity-rule">{r.rule_id}</span>
          <span className="adm-down-stats">
            <span className="adm-down-count">{r.down} down</span>
            <span className="adm-up-count">{r.up} up</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

// ── Token usage by call type ───────────────────────────────────────────────

function TokenBreakdown({ rows }) {
  if (!rows.length) return <EmptyChart label="No LLM calls recorded yet" height={120} />
  return (
    <table className="adm-token-table">
      <thead>
        <tr>
          <th>Call Type</th><th>Calls</th><th>Prompt</th><th>Completion</th><th>Total</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={r.call_type}>
            <td className="adm-token-type">{CALL_TYPE_LABELS[r.call_type] ?? r.call_type}</td>
            <td>{r.calls.toLocaleString()}</td>
            <td>{formatTokens(r.prompt_tokens)}</td>
            <td>{formatTokens(r.completion_tokens)}</td>
            <td className="adm-token-total">{formatTokens(r.total_tokens)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ── Skeleton loaders ───────────────────────────────────────────────────────

const SkeletonRows = ({ n = 6, widths }) => (
  <div className="adm-skeleton-rows">
    {Array.from({ length: n }).map((_, i) => (
      <div key={i} className="adm-skeleton-row"
        style={{ width: widths ? `${widths[i] ?? 60}%` : `${90 - i * 9}%` }} />
    ))}
  </div>
)

// ── Dashboard content ──────────────────────────────────────────────────────

export default function AdminDashboard({ token, onRefresh }) {
  const [data,       setData]       = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [spin,       setSpin]       = useState(false)
  const [updatedAt,  setUpdatedAt]  = useState(null)
  // Rule count from the public /health endpoint — shows immediately, no auth
  const [ruleCount,  setRuleCount]  = useState(null)
  const [reloading,  setReloading]  = useState(false)
  const [reloadMsg,  setReloadMsg]  = useState(null) // { ok, text }
  const [llmChecking, setLlmChecking] = useState(false)
  const [llmStatus,   setLlmStatus]   = useState(null) // { ok, text }
  const loadingRef = useRef(false)

  // Fetch rule count from the public health endpoint right away
  useEffect(() => {
    apiFetch('/health')
      .then(r => r.json())
      .then(d => { if (typeof d.rules_loaded === 'number') setRuleCount(d.rules_loaded) })
      .catch(() => {})
  }, [])

  // silent=true refreshes data in place without flashing the skeleton loaders
  const load = useCallback(async (silent = false) => {
    if (loadingRef.current) return
    loadingRef.current = true
    if (!silent) { setLoading(true); setSpin(true); setError(null) }
    try {
      const res = await apiFetch('/admin/dashboard', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (res.status === 401) throw new Error('invalid_token')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
      setUpdatedAt(new Date())
      setError(null)
    } catch (e) {
      if (e.message === 'invalid_token') {
        setError(e.message)
        onRefresh?.()
      } else if (!silent) {
        // a failed background refresh keeps showing the last good data
        setError(e.message)
      }
    } finally {
      loadingRef.current = false
      if (!silent) {
        setLoading(false)
        setTimeout(() => setSpin(false), 700)
      }
    }
  }, [token, onRefresh])

  useEffect(() => { load() }, [load])

  // Auto-refresh every 60s while the tab is visible
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load(true)
    }, 60_000)
    return () => clearInterval(id)
  }, [load])

  async function checkLlm() {
    if (llmChecking) return
    setLlmChecking(true); setLlmStatus(null)
    try {
      const res = await apiFetch('/admin/probe-llm', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (res.status === 401) { onRefresh?.(); return }
      const body = await res.json().catch(() => ({}))
      if (res.ok && body.llm === 'ok') {
        setLlmStatus({ ok: true, text: 'LLM connected' })
      } else {
        setLlmStatus({
          ok: false,
          text: `LLM degraded${body.llm_error ? ` (${body.llm_error})` : ''}`,
        })
      }
    } catch {
      setLlmStatus({ ok: false, text: 'Could not reach the server.' })
    } finally {
      setLlmChecking(false)
      setTimeout(() => setLlmStatus(null), 12000)
    }
  }

  async function reloadData() {
    if (reloading) return
    setReloading(true); setReloadMsg(null)
    try {
      const res = await apiFetch('/admin/reload', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const body = await res.json().catch(() => ({}))
      if (res.ok && body.ok) {
        setReloadMsg({
          ok: true,
          text: `Reloaded — ${body.rules_loaded} rules, ${body.yaml_pipelines} pipelines, ${body.custom_ops} custom ops`,
        })
        if (typeof body.rules_loaded === 'number') setRuleCount(body.rules_loaded)
        load()
      } else {
        setReloadMsg({ ok: false, text: body.error ?? `Reload failed (HTTP ${res.status})` })
      }
    } catch {
      setReloadMsg({ ok: false, text: 'Could not reach the server.' })
    } finally {
      setReloading(false)
      setTimeout(() => setReloadMsg(null), 8000)
    }
  }

  const ov = data?.overview ?? {}
  // Prefer the live health count; fall back to what analytics returns
  const totalRules = ruleCount ?? ov.total_rules
  const fb = data?.feedback ?? { up: 0, down: 0 }
  const fbTotal = (fb.up ?? 0) + (fb.down ?? 0)

  return (
    <div className="adm-content">
      {/* Hero header */}
      <div className="adm-hero">
        <div className="adm-hero-left">
          <h1 className="adm-hero-title">Rule Health</h1>
          <div className="adm-hero-meta">
            <span className="adm-live"><span className="adm-live-dot" />Live</span>
            <span className="adm-hero-sep">·</span>
            <span>Auto-refreshes every 60s</span>
            {updatedAt && (
              <>
                <span className="adm-hero-sep">·</span>
                <span>Updated {updatedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
              </>
            )}
          </div>
        </div>
        <div className="adm-hero-actions">
          {llmStatus && (
            <span className={`adm-status ${llmStatus.ok ? 'ok' : 'fail'}`}>{llmStatus.text}</span>
          )}
          {reloadMsg && (
            <span className={`adm-status ${reloadMsg.ok ? 'ok' : 'fail'}`}>{reloadMsg.text}</span>
          )}
          <button
            className="adm-btn"
            onClick={checkLlm}
            disabled={llmChecking}
            title="Probe Azure OpenAI connectivity (makes one real LLM call)"
          >
            <ZapIcon />
            {llmChecking ? 'Checking…' : 'Check LLM'}
          </button>
          <button
            className="adm-btn"
            onClick={reloadData}
            disabled={reloading}
            title="Re-read the rule inventory Excel, golden/ YAML pipelines, and custom operations from disk"
          >
            <DatabaseIcon />
            {reloading ? 'Reloading…' : 'Reload Data'}
          </button>
          <button className="adm-btn" onClick={() => load()} disabled={loading}>
            <RefreshIcon spinning={spin} />
            Refresh
          </button>
        </div>
      </div>

      <div className="adm-scroll">
        <div className="adm-scroll-inner">
          {error && error !== 'invalid_token' && (
            <div className="adm-error-banner">
              Could not load analytics data: {error}. Interact with rules to start populating data.
            </div>
          )}

          {/* KPI band */}
          <section className="adm-band" aria-label="Key metrics">
            {/* Active Rules loads from /health independently — always visible */}
            <Stat
              accent
              label="Active Rules"
              value={totalRules != null ? totalRules.toLocaleString() : undefined}
              sub="Customer domain"
            />
            <Stat label="Total Views"     value={loading ? undefined : ov.total_views?.toLocaleString()}             sub={loading ? '' : `${ov.views_today ?? 0} today`} />
            <Stat label="This Week"       value={loading ? undefined : ov.views_this_week?.toLocaleString()}         sub="Last 7 days" />
            <Stat label="Rules Accessed"  value={loading ? undefined : ov.unique_rules_accessed?.toLocaleString()}   sub={loading ? '' : `of ${totalRules ?? '—'} total`} />
            <Stat label="AI Chat Queries" value={loading ? undefined : ov.chat_queries_with_rule?.toLocaleString()}  sub="Linked to a rule" />
            <Stat
              label="Tokens Used"
              value={loading ? undefined : formatTokens(ov.total_tokens_used)}
              sub={loading ? '' : `${formatTokens(ov.total_prompt_tokens) ?? 0} in · ${formatTokens(ov.total_completion_tokens) ?? 0} out${ov.estimated_cost_usd != null ? ` · ≈ ${formatCost(ov.estimated_cost_usd)}` : ''}`}
            />
            <Stat
              label="Answer Feedback"
              value={loading ? undefined : (fbTotal ? `${Math.round((fb.up / fbTotal) * 100)}%` : '—')}
              sub={loading ? '' : (fbTotal ? `${fb.up} up · ${fb.down} down` : 'No votes yet')}
            />
          </section>

          {/* Main grid */}
          <div className="adm-grid">
            {/* Top rules bar chart */}
            <section className="adm-card">
              <div className="adm-card-header">
                <span className="adm-card-title">Most Asked Rules</span>
                <span className="adm-card-badge">Top 15</span>
              </div>
              {loading ? <SkeletonRows n={7} /> : <HorizontalBarChart data={data?.top_rules ?? []} maxBars={15} />}
            </section>

            {/* Right column */}
            <div className="adm-right-col">
              <section className="adm-card">
                <div className="adm-card-header">
                  <span className="adm-card-title">Catalogue Coverage</span>
                </div>
                <div className="adm-coverage-body">
                  {loading
                    ? <div className="adm-skeleton-circle" />
                    : <CoverageArc pct={ov.coverage_pct ?? 0} />
                  }
                  <div className="adm-coverage-text">
                    <p className="adm-coverage-headline">
                      {ov.unique_rules_accessed ?? 0} of {ov.total_rules ?? '—'} rules explored
                    </p>
                    <p className="adm-coverage-hint">
                      {!ov.coverage_pct
                        ? 'Start exploring rules to track coverage'
                        : ov.coverage_pct < 50
                        ? 'Significant discovery opportunity remains'
                        : ov.coverage_pct < 80
                        ? 'Good adoption — keep driving exploration'
                        : 'Excellent catalogue engagement'}
                    </p>
                  </div>
                </div>
              </section>

              <section className="adm-card">
                <div className="adm-card-header">
                  <span className="adm-card-title">Recent Activity</span>
                </div>
                {loading ? <SkeletonRows n={5} widths={[70, 60, 75, 55, 65]} /> : <RecentActivity views={data?.recent_views ?? []} />}
              </section>
            </div>
          </div>

          {/* Insight grid — chat intents, trending, feedback by mode */}
          <div className="adm-grid-3">
            <section className="adm-card">
              <div className="adm-card-header">
                <span className="adm-card-title">Chat Intents</span>
                <span className="adm-card-badge">What users ask</span>
              </div>
              {loading ? <SkeletonRows n={5} /> : <IntentBars items={data?.intent_distribution ?? []} />}
            </section>

            <section className="adm-card">
              <div className="adm-card-header">
                <span className="adm-card-title">Trending Rules</span>
                <span className="adm-card-badge">Last 30 days</span>
              </div>
              {loading ? <SkeletonRows n={5} /> : <TrendingRules rules={data?.trending_rules ?? []} />}
            </section>

            <section className="adm-card">
              <div className="adm-card-header">
                <span className="adm-card-title">Feedback by Mode</span>
                <span className="adm-card-badge">Answer quality</span>
              </div>
              {loading ? <SkeletonRows n={5} /> : <FeedbackByMode byMode={data?.feedback?.by_mode ?? []} />}
            </section>
          </div>

          {/* Quality + cost grid */}
          <div className="adm-grid-2">
            <section className="adm-card">
              <div className="adm-card-header">
                <span className="adm-card-title">Most Downvoted Rules</span>
                <span className="adm-card-badge">Review queue</span>
              </div>
              {loading ? <SkeletonRows n={4} /> : <DownvotedRules rules={data?.downvoted_rules ?? []} />}
            </section>

            <section className="adm-card">
              <div className="adm-card-header">
                <span className="adm-card-title">Token Usage by Call Type</span>
              </div>
              {loading ? <SkeletonRows n={4} /> : <TokenBreakdown rows={data?.tokens_by_call_type ?? []} />}
            </section>
          </div>

          {/* Sparkline */}
          <section className="adm-card adm-card-spark">
            <div className="adm-card-header">
              <span className="adm-card-title">30-Day Activity Trend</span>
              <span className="adm-card-badge">{data?.daily_activity?.length ?? 0} days with data</span>
            </div>
            {loading
              ? <div className="adm-skeleton-spark" />
              : data?.daily_activity?.length
              ? <Sparkline data={fillDailySeries(data.daily_activity)} />
              : <EmptyChart label="No activity data yet" height={70} />}
          </section>

          <p className="adm-footer">
            Rule Intelligence &middot; Coca-Cola HBC &middot; Data Quality Platform
          </p>
        </div>
      </div>
    </div>
  )
}
