import { useState, useEffect, useRef } from 'react'
import Tooltip from './Tooltip.jsx'

// ── Icons ──────────────────────────────────────────────────────────────────

const CloseIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

const SearchIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <circle cx="5.5" cy="5.5" r="4" stroke="currentColor" strokeWidth="1.4"/>
    <path d="M9 9l2.5 2.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
  </svg>
)

const ChevronIcon = () => (
  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
    <path d="M3.5 2l3 3-3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const FolderIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M1 3.5h4l1 1.5h5v5.5H1V3.5z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
  </svg>
)

const TagIcon = () => (
  <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden="true">
    <rect x="1" y="1" width="9" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.2"/>
    <path d="M3 3.8h5M3 5.5h5M3 7.2h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
  </svg>
)

const DocIcon = () => (
  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
    <path d="M1.5 1h5l2 2v6.5H1.5V1z" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round"/>
    <path d="M6.5 1v2h2" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round"/>
    <path d="M3 5h4M3 6.5h3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round"/>
  </svg>
)

// ── Helpers ────────────────────────────────────────────────────────────────

function matchesSearch(node, q) {
  if (!q) return true
  if (node.name.toLowerCase().includes(q)) return true
  if (node.type === 'rule') {
    if ((node.description || '').toLowerCase().includes(q)) return true
    if ((node.table || '').toLowerCase().includes(q)) return true
  }
  if (node.children) return node.children.some(c => matchesSearch(c, q))
  return false
}

function collectAllBranchIds(node, ids = new Set()) {
  if (node.type !== 'rule' && node.children?.length) {
    ids.add(node.id)
    node.children.forEach(c => collectAllBranchIds(c, ids))
  }
  return ids
}

function collectSearchOpenIds(node, q, ids = new Set()) {
  if (node.type === 'rule') return ids
  const hasMatch = node.children?.some(c => matchesSearch(c, q))
  if (hasMatch) {
    ids.add(node.id)
    node.children.forEach(c => collectSearchOpenIds(c, q, ids))
  }
  return ids
}

function countVisibleRules(tree, q) {
  let n = 0
  function walk(node) {
    if (node.type === 'rule') { if (matchesSearch(node, q)) n++; return }
    node.children?.forEach(walk)
  }
  tree.children.forEach(walk)
  return n
}

// ── TreeNode ───────────────────────────────────────────────────────────────

function TreeNode({ node, depth, openIds, onToggle, onRuleSelected, search }) {
  const q = search.toLowerCase()
  if (!matchesSearch(node, q)) return null

  const isRule     = node.type === 'rule'
  const hasKids    = node.children?.length > 0
  const isOpen     = openIds.has(node.id)

  const sevColor =
    node.severity === 1 ? 'var(--accent)' :
    node.severity === 2 ? 'var(--warning)' :
    node.severity === 3 ? '#ECC94B' :
    'var(--text-muted)'

  function handleClick() {
    if (isRule) onRuleSelected(node.id)
    else onToggle(node.id)
  }

  function handleKey(e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleClick() }
  }

  return (
    <div className="tree-node">
      <div
        className={`tree-node-row tree-type-${node.type}`}
        onClick={handleClick}
        onKeyDown={handleKey}
        role="button"
        tabIndex={0}
        aria-expanded={!isRule ? isOpen : undefined}
      >
        <span className={`tree-chevron${isOpen ? ' open' : ''}${isRule ? ' tree-chevron-hidden' : ''}`}>
          <ChevronIcon />
        </span>

        <span className={`tree-node-icon tree-icon-${node.type}`}>
          {node.type === 'subdomain' ? <FolderIcon /> :
           node.type === 'category'  ? <TagIcon />    :
           <DocIcon />}
        </span>

        <span className="tree-node-label">
          {isRule ? (
            <>
              <span className="tree-rule-id">{node.name}</span>
              {node.description && (
                <span className="tree-rule-desc">
                  {node.description.length > 58
                    ? node.description.slice(0, 58) + '…'
                    : node.description}
                </span>
              )}
            </>
          ) : (
            <span className="tree-branch-name">{node.name}</span>
          )}
        </span>

        <span className="tree-node-meta">
          {isRule && node.severity ? (
            <span className="tree-rule-sev" style={{ color: sevColor }}>
              S{node.severity}
            </span>
          ) : (
            !isRule && node.count !== undefined && (
              <span className="tree-node-count">{node.count}</span>
            )
          )}
        </span>
      </div>

      {hasKids && isOpen && (
        <div className={`tree-children tree-children-d${depth}`}>
          {node.children.map(child => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              openIds={openIds}
              onToggle={onToggle}
              onRuleSelected={onRuleSelected}
              search={search}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── TreeView ───────────────────────────────────────────────────────────────

export default function TreeView({ onRuleSelected, onClose }) {
  const [tree,    setTree]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [search,  setSearch]  = useState('')
  const [openIds, setOpenIds] = useState(new Set())
  const searchRef   = useRef(null)
  const prevQRef    = useRef('')

  // Fetch tree data once
  useEffect(() => {
    fetch('/api/tree')
      .then(r => { if (!r.ok) throw new Error('fetch'); return r.json() })
      .then(data => {
        setTree(data)
        // Default: open all subdomain-level nodes
        setOpenIds(new Set(data.children.map(n => n.id)))
        setLoading(false)
      })
      .catch(() => { setError('Could not load rule tree.'); setLoading(false) })
  }, [])

  // Focus search on mount
  useEffect(() => { searchRef.current?.focus() }, [])

  // Auto-expand matching paths when search changes; restore defaults on clear
  useEffect(() => {
    if (!tree) return
    const q = search.trim().toLowerCase()
    if (q) {
      const ids = new Set()
      tree.children.forEach(n => collectSearchOpenIds(n, q, ids))
      setOpenIds(ids)
    } else if (prevQRef.current) {
      setOpenIds(new Set(tree.children.map(n => n.id)))
    }
    prevQRef.current = q
  }, [search, tree])

  function toggleNode(id) {
    setOpenIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function expandAll() {
    if (!tree) return
    const ids = new Set()
    tree.children.forEach(n => collectAllBranchIds(n, ids))
    setOpenIds(ids)
  }

  function collapseAll() { setOpenIds(new Set()) }

  const q            = search.trim().toLowerCase()
  const displayCount = tree ? (q ? countVisibleRules(tree, q) : tree.count) : 0

  return (
    <div className="rule-browser tree-view">

      {/* ── Header ── */}
      <div className="browser-header">
        <div className="browser-title">
          <span className="browser-icon-wrap tree-header-icon">
            <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
              <circle cx="6.5" cy="1.8" r="1.3" stroke="currentColor" strokeWidth="1.2"/>
              <circle cx="2"   cy="10.5" r="1.3" stroke="currentColor" strokeWidth="1.2"/>
              <circle cx="11" cy="10.5" r="1.3" stroke="currentColor" strokeWidth="1.2"/>
              <path d="M6.5 3.1v3M6.5 6.1H2M6.5 6.1H11M2 9.2V6.1M11 9.2V6.1"
                stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
            </svg>
          </span>
          <span className="browser-label">Rule Tree</span>
          {!loading && <span className="browser-count">{displayCount}</span>}
        </div>
        <Tooltip content="Close tree view">
          <button className="browser-close-btn" onClick={onClose} aria-label="Close tree">
            <CloseIcon />
          </button>
        </Tooltip>
      </div>

      {/* ── Search ── */}
      <div className="browser-search-wrap">
        <span className="browser-search-icon"><SearchIcon /></span>
        <input
          ref={searchRef}
          className="browser-search-input"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filter by rule ID, description…"
          aria-label="Filter rules"
        />
        {search && (
          <Tooltip content="Clear filter">
            <button className="browser-search-clear" onClick={() => setSearch('')} aria-label="Clear">
              <CloseIcon />
            </button>
          </Tooltip>
        )}
      </div>

      {/* ── Toolbar ── */}
      <div className="tree-toolbar">
        <button className="tree-ctrl-btn" onClick={expandAll}>Expand all</button>
        <span className="tree-ctrl-sep" />
        <button className="tree-ctrl-btn" onClick={collapseAll}>Collapse all</button>
        {q && (
          <>
            <span className="tree-ctrl-sep" />
            <span className="tree-filter-hint">
              {displayCount} match{displayCount !== 1 ? 'es' : ''}
            </span>
          </>
        )}
      </div>

      {/* ── Content ── */}
      <div className="browser-list tree-list">
        {loading ? (
          <div className="browser-loading">
            <div className="spinner" />
            <span>Building tree…</span>
          </div>
        ) : error ? (
          <div className="browser-empty">{error}</div>
        ) : tree ? (
          tree.children.length === 0 ? (
            <div className="browser-empty">No rules found.</div>
          ) : (
            tree.children.map(node => (
              <TreeNode
                key={node.id}
                node={node}
                depth={0}
                openIds={openIds}
                onToggle={toggleNode}
                onRuleSelected={onRuleSelected}
                search={search}
              />
            ))
          )
        ) : null}
      </div>
    </div>
  )
}
