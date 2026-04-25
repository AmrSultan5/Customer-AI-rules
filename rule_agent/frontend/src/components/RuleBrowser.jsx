import { useState, useEffect, useRef } from 'react'
import Tooltip from './Tooltip.jsx'

function getCatColor() {
  return '#E8000D'
}

const SearchIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <circle cx="5.5" cy="5.5" r="4" stroke="currentColor" strokeWidth="1.4"/>
    <path d="M9 9l2.5 2.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
  </svg>
)

const CloseIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

const BrowserIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <rect x="1.5" y="1.5" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M1.5 5h10M5 5v6" stroke="currentColor" strokeWidth="1.3"/>
  </svg>
)

export default function RuleBrowser({ onRuleSelected, onClose }) {
  const [rules, setRules]               = useState([])
  const [loading, setLoading]           = useState(true)
  const [search, setSearch]             = useState('')
  const [activeCategory, setActiveCategory] = useState(null)
  const searchRef = useRef(null)

  useEffect(() => {
    fetch('/api/rules')
      .then(r => r.json())
      .then(data => { setRules(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    searchRef.current?.focus()
  }, [])

  const categories = [...new Set(
    rules.map(r => r.quality_category).filter(c => c && c.toLowerCase() !== 'nan')
  )].sort()

  const q = search.trim().toLowerCase()
  const filtered = rules.filter(r => {
    const matchSearch = !q ||
      r.rule_id.toLowerCase().includes(q) ||
      (r.quality_category || '').toLowerCase().includes(q) ||
      (r.table_checked || '').toLowerCase().includes(q) ||
      (r.description || '').toLowerCase().includes(q)
    const matchCat = !activeCategory || r.quality_category === activeCategory
    return matchSearch && matchCat
  })

  return (
    <div className="rule-browser">
      <div className="browser-header">
        <div className="browser-title">
          <span className="browser-icon-wrap"><BrowserIcon /></span>
          <span className="browser-label">Browse Rules</span>
          <span className="browser-count">{filtered.length}</span>
        </div>
        <Tooltip content="Close rule browser">
          <button className="browser-close-btn" onClick={onClose}>
            <CloseIcon />
          </button>
        </Tooltip>
      </div>

      <div className="browser-search-wrap">
        <span className="browser-search-icon"><SearchIcon /></span>
        <input
          ref={searchRef}
          className="browser-search-input"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search rule ID, category, table…"
        />
        {search && (
          <Tooltip content="Clear search">
            <button className="browser-search-clear" onClick={() => setSearch('')}>
              <CloseIcon />
            </button>
          </Tooltip>
        )}
      </div>

      {categories.length > 0 && (
        <div className="browser-chips">
          {categories.map(cat => (
            <button
              key={cat}
              className={`browser-chip${activeCategory === cat ? ' active' : ''}`}
              onClick={() => setActiveCategory(activeCategory === cat ? null : cat)}
            >
              {cat}
            </button>
          ))}
        </div>
      )}

      <div className="browser-list">
        {loading ? (
          <div className="browser-loading">
            <div className="spinner" />
            <span>Loading rules…</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="browser-empty">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="1.5"/>
              <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
            <span>No rules match your search</span>
          </div>
        ) : (
          filtered.map(r => {
            const catLabel = r.quality_category && r.quality_category.toLowerCase() !== 'nan'
              ? r.quality_category : ''
            return (
              <button
                key={r.rule_id}
                className="browser-rule-item"
                onClick={() => onRuleSelected(r.rule_id)}
              >
                <div className="browser-rule-top">
                  <span className="browser-rule-id">{r.rule_id}</span>
                  {catLabel && (
                    <span
                      className="browser-rule-cat"
                      style={{ color: '#E8000D', borderColor: 'rgba(232,0,13,0.25)', background: 'rgba(232,0,13,0.08)' }}
                    >
                      {catLabel}
                    </span>
                  )}
                </div>
                {r.table_checked && r.table_checked !== 'nan' && (
                  <span className="browser-rule-table">{r.table_checked}</span>
                )}
                {r.description && r.description !== 'nan' && (
                  <p className="browser-rule-desc">{r.description.slice(0, 90)}{r.description.length > 90 ? '…' : ''}</p>
                )}
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
