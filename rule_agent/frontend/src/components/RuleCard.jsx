import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import FieldTable from './FieldTable.jsx'
import Tooltip from './Tooltip.jsx'
import { apiGet } from '../api.js'

const DatabaseIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <ellipse cx="6.5" cy="3.2" rx="4" ry="1.7" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M2.5 3.2v6.6c0 .94 1.79 1.7 4 1.7s4-.76 4-1.7V3.2" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M2.5 6.5c0 .94 1.79 1.7 4 1.7s4-.76 4-1.7" stroke="currentColor" strokeWidth="1.3"/>
  </svg>
)

const WorkflowIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <path d="M2 3.5h9M2 6.5h6.5M2 9.5h8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
  </svg>
)

const FieldsIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <rect x="1.5" y="1.5" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M1.5 5h10M5 1.5v10" stroke="currentColor" strokeWidth="1.3"/>
  </svg>
)

const CodeIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <path d="M4 4L1.5 6.5 4 9M9 4l2.5 2.5L9 9M7.5 2l-2 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const CopyIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <rect x="4" y="4" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M4 8H2.5A1.5 1.5 0 011 6.5V2.5A1.5 1.5 0 012.5 1h4A1.5 1.5 0 018 2.5V4" stroke="currentColor" strokeWidth="1.3"/>
  </svg>
)

const CheckIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const ExportIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M6 1v7M3.5 5.5L6 8l2.5-2.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M1.5 9.5h9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
  </svg>
)

const AskIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M4.5 4.5C4.5 3.7 5.17 3 6 3s1.5.7 1.5 1.5c0 .7-.4 1.2-1 1.4V7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    <circle cx="6" cy="8.5" r=".5" fill="currentColor"/>
  </svg>
)

const RelatedIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <circle cx="3" cy="6.5" r="2" stroke="currentColor" strokeWidth="1.3"/>
    <circle cx="10" cy="3" r="2" stroke="currentColor" strokeWidth="1.3"/>
    <circle cx="10" cy="10" r="2" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M5 6.5h2M7.5 5l.5.5M7.5 8l.5-.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
  </svg>
)

const LinkIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <path d="M5.5 7.5a3 3 0 004.24 0l1.5-1.5a3 3 0 00-4.24-4.24l-.85.84" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    <path d="M7.5 5.5a3 3 0 00-4.24 0L1.76 7a3 3 0 004.24 4.24l.84-.84" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
  </svg>
)

const CATEGORY_COLORS = {
  completeness: { bg: 'rgba(232,0,13,0.08)',   border: 'rgba(232,0,13,0.22)',  color: '#FF4D55' },
  uniqueness:   { bg: 'rgba(232,0,13,0.06)',   border: 'rgba(232,0,13,0.18)',  color: '#FF6670' },
  validity:     { bg: 'rgba(232,0,13,0.08)',   border: 'rgba(232,0,13,0.22)',  color: '#FF4D55' },
  consistency:  { bg: 'rgba(232,0,13,0.06)',   border: 'rgba(232,0,13,0.18)',  color: '#FF6670' },
  accuracy:     { bg: 'rgba(232,0,13,0.10)',   border: 'rgba(232,0,13,0.28)',  color: '#E8000D' },
  timeliness:   { bg: 'rgba(232,0,13,0.06)',   border: 'rgba(232,0,13,0.18)',  color: '#FF6670' },
  conformity:   { bg: 'rgba(232,0,13,0.08)',   border: 'rgba(232,0,13,0.22)',  color: '#FF4D55' },
}

const SEVERITY_MAP = {
  1: 'Critical', '1': 'Critical',
  2: 'High',     '2': 'High',
  3: 'Medium',   '3': 'Medium',
  4: 'Low',      '4': 'Low',
}

function getCatStyle(cat) {
  const fallback = { bg: 'rgba(232,0,13,0.06)', border: 'rgba(232,0,13,0.18)', color: '#FF6670' }
  if (!cat) return fallback
  return CATEGORY_COLORS[cat.toLowerCase()] ?? fallback
}

function buildExportText(rule) {
  const lines = []
  lines.push(`RULE: ${rule.rule_id}`)
  if (rule.quality_category) lines.push(`Category: ${rule.quality_category}`)
  if (rule.severity)         lines.push(`Severity: ${rule.severity}`)
  if (rule.table_checked)    lines.push(`SAP Table: ${rule.table_checked}`)
  if (rule.column_checked)   lines.push(`SAP Column: ${rule.column_checked}`)
  if (rule.origin)           lines.push(`Origin: ${rule.origin}`)
  if (rule.yaml_reference)   lines.push(`YAML Reference: ${rule.yaml_reference}`)
  lines.push('')
  lines.push('DESCRIPTION')
  lines.push(rule.description || '—')
  lines.push('')
  lines.push('BUSINESS EXPLANATION')
  lines.push(rule.business_explanation || '—')
  if (rule.sources?.length) {
    lines.push('')
    lines.push('DATA SOURCES')
    rule.sources.forEach(s => lines.push(`  • ${s}`))
  }
  if (rule.workflow_steps?.length) {
    lines.push('')
    lines.push('WORKFLOW STEPS')
    rule.workflow_steps.forEach((s, i) => lines.push(`  ${i + 1}. ${s}`))
  }
  if (rule.sap_fields?.length) {
    lines.push('')
    lines.push('SAP FIELDS')
    rule.sap_fields.forEach(f => lines.push(`  ${f.field} — ${f.business_name}`))
  }
  lines.push('')
  lines.push('TECHNICAL RULE')
  lines.push(rule.technical_rule || '—')
  return lines.join('\n')
}

export default function RuleCard({ rule, onAskAboutRule, onRuleSelected }) {
  const [showTechnical, setShowTechnical] = useState(false)
  const [copied, setCopied]               = useState(false)
  const [exportCopied, setExportCopied]   = useState(false)
  const [relatedRules, setRelatedRules]   = useState([])
  const [toast, setToast]                 = useState(false)

  useEffect(() => {
    if (!rule?.rule_id) return
    setRelatedRules([])
    apiGet(`/rules/related/${rule.rule_id}`)
      .then(r => r.ok ? r.json() : [])
      .then(data => setRelatedRules(data))
      .catch(() => {})
  }, [rule?.rule_id])

  if (!rule) return null

  const steps    = rule.workflow_steps ?? []
  const sources  = rule.sources        ?? []
  const hasInfo  = rule.description || rule.origin || rule.table_checked
                   || rule.column_checked || rule.yaml_reference
  const catStyle = getCatStyle(rule.quality_category)

  async function copyTechnical() {
    try {
      await navigator.clipboard.writeText(rule.technical_rule ?? '')
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }

  async function exportRule() {
    const text = buildExportText(rule)
    try {
      await navigator.clipboard.writeText(text)
      setExportCopied(true)
      setToast(true)
      setTimeout(() => { setExportCopied(false); setToast(false) }, 2000)
    } catch {}
  }

  function downloadRule() {
    const text = buildExportText(rule)
    const blob = new Blob([text], { type: 'text/plain' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `${rule.rule_id}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="rule-card">
      <div className="rule-card-stripe" />

      {/* ── Header ────────────────────────────── */}
      <div className="rule-card-header">
        <div className="rule-header-top">
          <div className="rule-id-badge">
            <span className="rule-id-prefix">RULE</span>
            <span className="rule-id-value">{rule.rule_id}</span>
          </div>
          {rule.quality_category && (
            <span
              className="rule-category"
              style={{ background: catStyle.bg, borderColor: catStyle.border, color: catStyle.color }}
            >
              {rule.quality_category}
            </span>
          )}
          <div className="rule-header-actions">
            {onAskAboutRule && (
              <Tooltip content="Pre-fill chat with a question about this rule">
                <button
                  className="icon-btn ask-btn"
                  onClick={() => onAskAboutRule(rule.rule_id)}
                >
                  <AskIcon />
                  <span>Ask about this rule</span>
                </button>
              </Tooltip>
            )}
            <Tooltip content="Copy full rule summary to clipboard">
              <button
                className={`icon-btn${exportCopied ? ' copy-success' : ''}`}
                onClick={exportRule}
              >
                {exportCopied ? <CheckIcon /> : <ExportIcon />}
                <span>{exportCopied ? 'Copied!' : 'Export'}</span>
              </button>
            </Tooltip>
            <Tooltip content="Download rule as .txt file">
              <button className="icon-btn" onClick={downloadRule}>
                <span>↓ .txt</span>
              </button>
            </Tooltip>
          </div>
        </div>
        {toast && <div className="export-toast">Copied to clipboard!</div>}
      </div>

      {/* ── Business Explanation ────────────── */}
      <div className="explanation-block">
        <div className="explanation-header">
          <span className="section-eyebrow accent">Business Explanation</span>
        </div>
        <div className="explanation-text">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{rule.business_explanation}</ReactMarkdown>
        </div>
      </div>

      {/* ── Metadata ────────────────────────── */}
      {hasInfo && (
        <div className="info-card">
          <div className="info-card-header">
            <span className="section-eyebrow">Details</span>
          </div>
          {rule.description && (
            <div className="info-row">
              <span className="info-label">Description</span>
              <span className="info-value">{rule.description}</span>
            </div>
          )}
          {rule.origin && (
            <div className="info-row">
              <span className="info-label">Origin</span>
              <span className="info-value">{rule.origin}</span>
            </div>
          )}
          {rule.table_checked && (
            <div className="info-row">
              <span className="info-label">SAP Table</span>
              <span className="info-value"><span className="mono-pill">{rule.table_checked}</span></span>
            </div>
          )}
          {rule.column_checked && (
            <div className="info-row">
              <span className="info-label">SAP Column</span>
              <span className="info-value"><span className="mono-pill">{rule.column_checked}</span></span>
            </div>
          )}
          {rule.yaml_reference && (
            <div className="info-row">
              <span className="info-label">YAML Ref</span>
              <span className="info-value"><span className="mono-pill">{rule.yaml_reference}</span></span>
            </div>
          )}
        </div>
      )}

      {/* ── Data Sources ────────────────────── */}
      {sources.length > 0 && (
        <div className="section-card">
          <div className="section-card-header">
            <span className="section-icon"><DatabaseIcon /></span>
            <span className="section-eyebrow">Data Sources</span>
            <span className="section-count">{sources.length}</span>
          </div>
          <ul className="tag-list">
            {sources.map((s, i) => <li key={i} className="tag">{s}</li>)}
          </ul>
        </div>
      )}

      {/* ── Workflow Steps ────────────────── */}
      {steps.length > 0 && (
        <div className="section-card">
          <div className="section-card-header">
            <span className="section-icon"><WorkflowIcon /></span>
            <span className="section-eyebrow">Workflow Steps</span>
            <span className="section-count">{steps.length}</span>
          </div>
          <ol className="step-list">
            {steps.slice(0, 10).map((s, i) => (
              <li key={i}>
                <span className="step-num">{i + 1}</span>
                <span className="step-text">{s}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* ── SAP Fields ───────────────────── */}
      {rule.sap_fields?.length > 0 && (
        <div className="section-card">
          <div className="section-card-header">
            <span className="section-icon"><FieldsIcon /></span>
            <span className="section-eyebrow">SAP Fields</span>
            <span className="section-count">{rule.sap_fields.length}</span>
          </div>
          <FieldTable fields={rule.sap_fields} />
        </div>
      )}

      {/* ── Technical Rule ────────────────── */}
      <div className="section-card technical-card">
        <div className="section-card-header">
          <span className="section-icon"><CodeIcon /></span>
          <span className="section-eyebrow">Technical Rule</span>
          <div className="technical-actions">
            <Tooltip content="Copy technical rule to clipboard">
              <button
                className={`icon-btn${copied ? ' copy-success' : ''}`}
                onClick={copyTechnical}
              >
                {copied ? <CheckIcon /> : <CopyIcon />}
                <span>{copied ? 'Copied!' : 'Copy'}</span>
              </button>
            </Tooltip>
          </div>
        </div>
        {rule.yaml_reference && (
          <div className="yaml-source-row">
            <span className="yaml-source-label">Source file:</span>
            <span className="yaml-source-pill">{rule.yaml_reference}</span>
          </div>
        )}
        <div className={`technical-rule-wrap${showTechnical ? ' expanded' : ''}`}>
          <pre className="technical-rule">{rule.technical_rule}</pre>
          {!showTechnical && <div className="technical-rule-fade" />}
        </div>
        <button className="tech-toggle-link" onClick={() => setShowTechnical(v => !v)}>
          {showTechnical ? 'Show less ↑' : 'Show full rule ↓'}
        </button>
      </div>

      {/* ── Rule References ───────────────── */}
      {rule.referenced_rules?.length > 0 && (
        <div className="section-card">
          <div className="section-card-header">
            <span className="section-icon"><LinkIcon /></span>
            <span className="section-eyebrow">Rule References</span>
            <span className="section-count">{rule.referenced_rules.length}</span>
          </div>
          <p className="ref-rules-notice">
            This rule depends on or references the following rule{rule.referenced_rules.length > 1 ? 's' : ''}:
          </p>
          <div className="ref-rules-list">
            {rule.referenced_rules.map(ref => (
              <button
                key={ref.rule_id}
                className={`ref-rule-item${!ref.active ? ' ref-rule-inactive' : ''}`}
                onClick={() => ref.active && onRuleSelected?.(ref.rule_id)}
                disabled={!ref.active}
              >
                <div className="ref-rule-top">
                  <span className="ref-rule-id">{ref.rule_id}</span>
                  <span className={`ref-rule-source-badge${ref.source === 'dependent_on' ? ' badge-dep' : ' badge-logic'}`}>
                    {ref.source === 'dependent_on' ? 'dependency' : 'referenced in logic'}
                  </span>
                  {!ref.active && <span className="ref-rule-inactive-label">inactive</span>}
                </div>
                {ref.description && (
                  <span className="ref-rule-desc">{ref.description.slice(0, 100)}{ref.description.length > 100 ? '…' : ''}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Related Rules ─────────────────── */}
      {relatedRules.length > 0 && (
        <div className="section-card">
          <div className="section-card-header">
            <span className="section-icon"><RelatedIcon /></span>
            <span className="section-eyebrow">Related Rules</span>
            <span className="section-count">{relatedRules.length}</span>
          </div>
          <div className="related-rules-grid">
            {relatedRules.map(r => {
              const cs = getCatStyle(r.quality_category)
              return (
                <button
                  key={r.rule_id}
                  className="related-rule-card"
                  onClick={() => onRuleSelected?.(r.rule_id)}
                >
                  <span className="related-rule-id">{r.rule_id}</span>
                  {r.quality_category && (
                    <span
                      className="related-rule-cat"
                      style={{ color: cs.color, borderColor: cs.border, background: cs.bg }}
                    >
                      {r.quality_category}
                    </span>
                  )}
                  {r.severity && r.severity !== 'nan' && (
                    <span className="related-rule-severity">
                      {SEVERITY_MAP[r.severity] ?? r.severity}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}

    </div>
  )
}
