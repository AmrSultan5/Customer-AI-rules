import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import * as d3 from 'd3'
import { apiGet } from '../api.js'

// ── Constants ──────────────────────────────────────────────────────────────
const LEVEL_H   = 118
const RULE_R    = 13
const MIN_SCALE = 0.07
const MAX_SCALE = 3.0

function sevColor(sev) {
  if (sev === 3) return '#ECC94B'
  if (sev === 2) return '#ED8936'
  return '#E8000D'
}
function sevLabel(sev) {
  if (sev === 3) return 'HIGH'
  if (sev === 2) return 'MED'
  return 'CRIT'
}

// Build a pruned copy of rawTree where collapsed nodes have empty children arrays
function visibleTree(node, collapsed) {
  if (node.type === 'rule') return { ...node }
  const isCollapsed = collapsed.has(node.id)
  return {
    ...node,
    _collapsed:   isCollapsed,
    _hiddenCount: node.children?.length ?? 0,
    children: isCollapsed
      ? []
      : (node.children ?? []).map(c => visibleTree(c, collapsed)),
  }
}

// ── Icons ──────────────────────────────────────────────────────────────────
const CloseIcon = () => (
  <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden="true">
    <path d="M2 2l7 7M9 2l-7 7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)
const SearchIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <circle cx="5.5" cy="5.5" r="4" stroke="currentColor" strokeWidth="1.4"/>
    <path d="M9 9l2.5 2.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
  </svg>
)
const FitIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
    <rect x="1" y="1" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M4 4h1.5M4 4v1.5M9 4h-1.5M9 4v1.5M4 9h1.5M4 9v-1.5M9 9h-1.5M9 9v-1.5"
      stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
  </svg>
)

// ── Smart Tooltip ──────────────────────────────────────────────────────────
function NodeTooltip({ node, x, y, k, cw, ch }) {
  if (!node) return null
  const px = x + node.x * k
  const py = y + node.y * k
  const TW = 264, TH = 112, M = 14
  const left = (px + 18 + TW > cw - M) ? px - TW - 18 : px + 18
  const top  = Math.max(M, Math.min(py - 10, ch - TH - M))
  const d    = node.data
  return (
    <div className="graph-node-tooltip" style={{ left, top }}>
      <div className="gnt-header">
        <span className={`gnt-type-badge gnt-type-badge--${d.type}`}>{d.type}</span>
        <span className="gnt-id">{d.name}</span>
      </div>
      {d.description && (
        <span className="gnt-desc">
          {d.description.length > 110 ? d.description.slice(0, 109) + '…' : d.description}
        </span>
      )}
      <div className="gnt-footer">
        {d.table && <span className="gnt-table">{d.table}</span>}
        {d.type !== 'rule' && d.count != null && <span className="gnt-count">{d.count} rules</span>}
        {d.type === 'rule' && d.severity != null && (
          <span className="gnt-sev" style={{ color: sevColor(d.severity) }}>{sevLabel(d.severity)}</span>
        )}
      </div>
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────────────────────
export default function GraphView({ onRuleSelected, onClose }) {
  const containerRef = useRef(null)
  const searchRef    = useRef(null)
  const dragRef      = useRef(null)
  const pinchRef     = useRef(null)

  const [rawTree,     setRawTree]     = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)
  const [search,      setSearch]      = useState('')
  const [collapsed,   setCollapsed]   = useState(new Set())
  const [tx,          setTx]          = useState({ x: 0, y: 60, k: 1 })
  const [dims,        setDims]        = useState({ w: 900, h: 600 })
  const [hoveredNode, setHoveredNode] = useState(null)
  const [clickedId,   setClickedId]   = useState(null)
  const [isDark,      setIsDark]      = useState(() => document.documentElement.dataset.theme !== 'light')
  const hasInitialFit = useRef(false)

  // Theme observer
  useEffect(() => {
    const mo = new MutationObserver(() =>
      setIsDark(document.documentElement.dataset.theme !== 'light')
    )
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => mo.disconnect()
  }, [])

  // Keyboard shortcuts
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') { onClose(); return }
      const tag = document.activeElement?.tagName
      if (e.key === '/' && tag !== 'INPUT' && tag !== 'TEXTAREA') {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Fetch
  useEffect(() => {
    apiGet('/tree')
      .then(r => { if (!r.ok) throw new Error(); return r.json() })
      .then(data => {
        const catIds = new Set()
        data.children?.forEach(sd => sd.children?.forEach(cat => catIds.add(cat.id)))
        setCollapsed(catIds)
        setRawTree(data)
        setLoading(false)
      })
      .catch(() => { setError('Failed to load graph data.'); setLoading(false) })
  }, [])

  // Resize
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      setDims({ w: Math.max(width, 1), h: Math.max(height, 1) })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // Layout — computed on the visible (pruned) tree so the initial collapsed view
  // is compact. Spacing is fixed-floored at 100 px so expanding never bunches nodes.
  const layout = useMemo(() => {
    if (!rawTree) return null
    const vTree = visibleTree(rawTree, collapsed)
    const root  = d3.hierarchy(vTree, d => d.children?.length ? d.children : null)
    const leafCount   = root.leaves().length
    // Adaptive but never below 100 px — prevents branch-node overlap on expansion
    const nodeSpacing = Math.max(100, Math.min(180, 2800 / Math.max(leafCount, 1)))
    d3.tree()
      .nodeSize([nodeSpacing, LEVEL_H])
      .separation((a, b) => {
        const aR = a.data.type === 'rule', bR = b.data.type === 'rule'
        if (aR && bR)   return a.parent === b.parent ? 0.38 : 1.1  // compact circles
        return           a.parent === b.parent ? 1.0 : 1.6          // spacious boxes
      })(root)
    return { nodes: root.descendants(), links: root.links() }
  }, [rawTree, collapsed])

  // Fit to screen
  const fit = useCallback(() => {
    if (!layout || !dims.w) return
    const xs = layout.nodes.map(n => n.x)
    const ys = layout.nodes.map(n => n.y)
    const minX = Math.min(...xs) - 120, maxX = Math.max(...xs) + 120
    const minY = Math.min(...ys) - 80,  maxY = Math.max(...ys) + 80
    const pad  = 72
    const k    = Math.min((dims.w - pad * 2) / (maxX - minX), (dims.h - pad * 2) / (maxY - minY), 1.2)
    setTx({ x: dims.w / 2 - ((minX + maxX) / 2) * k, y: dims.h / 2 - ((minY + maxY) / 2) * k, k })
  }, [layout, dims])

  // Auto-fit only once on initial data load — not on every collapse/expand
  useEffect(() => {
    if (!layout || hasInitialFit.current) return
    hasInitialFit.current = true
    fit()
  }, [layout, fit])

  // Wheel zoom
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    function onWheel(e) {
      e.preventDefault()
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12
      const rect   = el.getBoundingClientRect()
      const mx = e.clientX - rect.left, my = e.clientY - rect.top
      setTx(t => {
        const k = Math.min(Math.max(t.k * factor, MIN_SCALE), MAX_SCALE)
        return { x: mx - (mx - t.x) * (k / t.k), y: my - (my - t.y) * (k / t.k), k }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // Drag pan
  function onMouseDown(e) {
    if (e.button !== 0) return
    e.preventDefault()
    dragRef.current = { sx: e.clientX, sy: e.clientY, tx: tx.x, ty: tx.y }
    function onMove(ev) {
      if (!dragRef.current) return
      const { tx: stx, ty: sty, sx, sy } = dragRef.current
      setTx(t => ({ ...t, x: stx + ev.clientX - sx, y: sty + ev.clientY - sy }))
    }
    function onUp() {
      dragRef.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  // Touch pan (single finger). Pinch-zoom (two fingers) is added in a later task.
  function onTouchStart(e) {
    if (e.touches.length === 1) {
      const t = e.touches[0]
      dragRef.current = { sx: t.clientX, sy: t.clientY, tx: tx.x, ty: tx.y }
    } else {
      dragRef.current = null
    }
  }

  function onTouchMove(e) {
    // No e.preventDefault() here — React 17+ attaches touchmove listeners as
    // passive by default, so it would be a silent no-op (and log a console
    // warning). `touchAction: 'none'` on the canvas (added below) is what
    // actually suppresses native scroll/zoom gestures.
    if (e.touches.length === 1 && dragRef.current) {
      const t = e.touches[0]
      const { tx: stx, ty: sty, sx, sy } = dragRef.current
      setTx(prev => ({ ...prev, x: stx + t.clientX - sx, y: sty + t.clientY - sy }))
    }
  }

  function onTouchEnd(e) {
    if (e.touches.length === 0) {
      dragRef.current = null
    }
  }

  function toggle(id) {
    setCollapsed(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  function expandAll() { setCollapsed(new Set()) }
  function collapseToCategories() {
    if (!rawTree) return
    const s = new Set()
    rawTree.children?.forEach(sd => sd.children?.forEach(cat => s.add(cat.id)))
    setCollapsed(s)
  }
  function collapseToSubdomains() {
    if (!rawTree) return
    const s = new Set()
    rawTree.children?.forEach(sd => s.add(sd.id))
    setCollapsed(s)
  }
  function zoomBy(factor) {
    setTx(t => {
      const k = Math.min(Math.max(t.k * factor, MIN_SCALE), MAX_SCALE)
      return { x: dims.w / 2 - (dims.w / 2 - t.x) * (k / t.k), y: dims.h / 2 - (dims.h / 2 - t.y) * (k / t.k), k }
    })
  }

  // Search
  const q = search.trim().toLowerCase()
  function nodeMatches(node) {
    if (!q) return false
    const d = node.data
    return d.name?.toLowerCase().includes(q) || d.description?.toLowerCase().includes(q) || d.table?.toLowerCase().includes(q)
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const matchCount = useMemo(() => (!q || !layout) ? 0 : layout.nodes.filter(n => nodeMatches(n)).length, [layout, q])
  const visibleRules = useMemo(() => layout?.nodes.filter(n => n.data.type === 'rule').length ?? 0, [layout])

  // Theme-aware colors
  const typeStroke = { root: '#E8000D', subdomain: '#63B3ED', category: '#ED8936' }
  const typeFill = {
    root:      isDark ? 'rgba(232,0,13,0.14)'   : 'rgba(232,0,13,0.18)',
    subdomain: isDark ? 'rgba(99,179,237,0.08)' : 'rgba(99,179,237,0.15)',
    category:  isDark ? 'rgba(237,137,54,0.08)' : 'rgba(237,137,54,0.14)',
  }
  const typeText = {
    root:      '#E8000D',
    subdomain: isDark ? '#63B3ED' : '#2672B0',
    category:  isDark ? '#ED8936' : '#C96A00',
  }
  const ruleFillDefault    = isDark ? 'rgba(232,0,13,0.09)'   : 'rgba(232,0,13,0.13)'
  const ruleStrokeDefault  = isDark ? 'rgba(232,0,13,0.42)'   : 'rgba(232,0,13,0.55)'
  const ruleTextDefault    = isDark ? 'rgba(245,245,245,0.60)': 'rgba(30,30,30,0.68)'
  const linkColors = {
    rule:      isDark ? 'rgba(232,0,13,0.11)'   : 'rgba(232,0,13,0.20)',
    category:  isDark ? 'rgba(237,137,54,0.20)' : 'rgba(237,137,54,0.34)',
    subdomain: isDark ? 'rgba(99,179,237,0.28)' : 'rgba(99,179,237,0.44)',
  }

  const linkGen = d3.linkVertical().x(d => d.x).y(d => d.y)

  return (
    <div className="graph-overlay">

      {/* ── Header ── */}
      <div className="graph-topbar">
        <div className="graph-topbar-left">
          <span className="graph-topbar-icon">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="2" r="1.6" stroke="currentColor" strokeWidth="1.3"/>
              <circle cx="2.5" cy="12.5" r="1.6" stroke="currentColor" strokeWidth="1.3"/>
              <circle cx="13.5" cy="12.5" r="1.6" stroke="currentColor" strokeWidth="1.3"/>
              <circle cx="8" cy="8" r="1.6" stroke="currentColor" strokeWidth="1.3"/>
              <path d="M8 3.6v2.8M8 9.6l-5.5 1.9M8 9.6l5.5 1.9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
            </svg>
          </span>
          <span className="graph-topbar-title">Rule Graph</span>
          {rawTree && <span className="graph-topbar-badge">{rawTree.count} rules</span>}
        </div>

        <div className="graph-topbar-search">
          <span className="graph-search-icon"><SearchIcon /></span>
          <input
            ref={searchRef}
            className="graph-search-input"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search nodes… (press / to focus)"
            spellCheck={false}
          />
          {q && matchCount > 0 && (
            <span className="graph-search-match-count">{matchCount} match{matchCount !== 1 ? 'es' : ''}</span>
          )}
          {q && matchCount === 0 && (
            <span className="graph-search-no-match">no matches</span>
          )}
          {search && (
            <button className="graph-search-clear" onClick={() => { setSearch(''); searchRef.current?.focus() }}>
              <CloseIcon />
            </button>
          )}
        </div>

        <div className="graph-topbar-right">
          <button className="graph-ctrl-btn" onClick={expandAll}>Expand all</button>
          <span className="graph-ctrl-sep" />
          <button className="graph-ctrl-btn" onClick={collapseToCategories}>Categories</button>
          <span className="graph-ctrl-sep" />
          <button className="graph-ctrl-btn" onClick={collapseToSubdomains}>Domains</button>
          <span className="graph-ctrl-sep" />
          <button className="graph-ctrl-btn graph-fit-btn" onClick={fit} title="Fit to screen">
            <FitIcon /><span>Fit</span>
          </button>
          <button className="graph-close-btn" onClick={onClose} aria-label="Close graph view" title="Close (Esc)">
            <CloseIcon />
          </button>
        </div>
      </div>

      {/* ── Canvas ── */}
      <div
        ref={containerRef}
        className="graph-canvas"
        onMouseDown={onMouseDown}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        style={{ cursor: dragRef.current ? 'grabbing' : 'grab', touchAction: 'none' }}
      >
        {loading && (
          <div className="graph-state-center">
            <div className="graph-loader">
              <div className="graph-loader-ring" />
              <div className="graph-loader-inner" />
            </div>
            <span>Building graph…</span>
          </div>
        )}
        {error && (
          <div className="graph-state-center graph-state-error">
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
              <circle cx="11" cy="11" r="9.5" stroke="currentColor" strokeWidth="1.4"/>
              <path d="M11 7v5M11 14.5v.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
            </svg>
            {error}
          </div>
        )}

        {layout && (
          <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, overflow: 'visible' }}>
            <defs>
              <filter id="gf-rule" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="2.5" result="b"/>
                <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
              </filter>
              <filter id="gf-branch" x="-40%" y="-40%" width="180%" height="180%">
                <feGaussianBlur stdDeviation="5" result="b"/>
                <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
              </filter>
              <filter id="gf-root" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="8" result="b"/>
                <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
              </filter>
            </defs>

            <g transform={`translate(${tx.x},${tx.y}) scale(${tx.k})`}>

              {/* Links */}
              <g>
                {layout.links.map((link, i) => {
                  const tType = link.target.data.type
                  const sType = link.source.data.type
                  const stroke = tType === 'rule' ? linkColors.rule : tType === 'category' ? linkColors.category : linkColors.subdomain
                  const sw = sType === 'root' ? 1.8 : tType === 'subdomain' ? 1.4 : tType === 'category' ? 1.1 : 0.85
                  return (
                    <path key={i} d={linkGen(link)} fill="none" stroke={stroke} strokeWidth={sw} strokeLinecap="round"/>
                  )
                })}
              </g>

              {/* Nodes */}
              <g>
                {layout.nodes.map(node => {
                  const { id, type, name, severity, count, _collapsed, _hiddenCount } = node.data
                  const isRule  = type === 'rule'
                  const isRoot  = type === 'root'
                  const hovered = hoveredNode?.data.id === id
                  const matched = nodeMatches(node)
                  const clicked = clickedId === id

                  if (isRule) {
                    const sc = sevColor(severity)
                    const strokeC = matched ? '#fff' : hovered ? sc : ruleStrokeDefault
                    const fillC   = matched ? 'rgba(255,255,255,0.14)' : hovered ? `${sc}22` : ruleFillDefault
                    const textC   = matched ? '#E8000D' : hovered ? sc : ruleTextDefault
                    return (
                      <g
                        key={id}
                        transform={`translate(${node.x},${node.y})`}
                        style={{ cursor: 'pointer' }}
                        onClick={() => { setClickedId(id); setTimeout(() => setClickedId(null), 600); onRuleSelected(id) }}
                        onMouseEnter={() => setHoveredNode(node)}
                        onMouseLeave={() => setHoveredNode(null)}
                        filter={hovered ? 'url(#gf-rule)' : undefined}
                      >
                        {severity >= 2 && (
                          <circle r={RULE_R + 4.5} fill="none" stroke={sc} strokeWidth={0.55} opacity={hovered ? 0.55 : 0.22}/>
                        )}
                        <circle r={RULE_R} fill={fillC} stroke={strokeC} strokeWidth={hovered || matched ? 1.8 : 0.95}/>
                        {clicked && (
                          <circle r={RULE_R} fill="none" stroke={sc} strokeWidth={1.4} className="node-click-ripple"/>
                        )}
                        <text
                          y={3.5}
                          textAnchor="middle"
                          fill={textC}
                          fontSize={6.5}
                          fontFamily="JetBrains Mono, monospace"
                          fontWeight="700"
                          style={{ pointerEvents: 'none', userSelect: 'none' }}
                        >
                          {name.length > 10 ? name.slice(0, 9) + '…' : name}
                        </text>
                      </g>
                    )
                  }

                  // Branch node
                  const w = isRoot ? 160 : type === 'subdomain' ? 144 : 126
                  const h = isRoot ? 42  : type === 'subdomain' ? 36  : 34
                  const rx = isRoot ? 12 : 8
                  const accentC = typeStroke[type]
                  const strokeC = matched ? '#fff' : hovered ? accentC : `${accentC}68`
                  const fillC   = matched ? (isDark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.04)') : typeFill[type]
                  const textC   = matched ? (isDark ? '#fff' : '#111') : typeText[type]
                  const sw      = hovered || matched ? 1.5 : 1.0

                  return (
                    <g
                      key={id}
                      transform={`translate(${node.x},${node.y})`}
                      style={{ cursor: isRoot ? 'default' : 'pointer' }}
                      onClick={isRoot ? undefined : () => toggle(id)}
                      onMouseEnter={() => setHoveredNode(node)}
                      onMouseLeave={() => setHoveredNode(null)}
                      filter={hovered ? 'url(#gf-branch)' : (isRoot ? 'url(#gf-root)' : undefined)}
                    >
                      {/* Main rect */}
                      <rect x={-w/2} y={-h/2} width={w} height={h} rx={rx} fill={fillC} stroke={strokeC} strokeWidth={sw}/>
                      {/* Top accent stripe — two rects trick for top-only rounding */}
                      <rect x={-w/2} y={-h/2} width={w} height={isRoot ? 3.5 : 2.8} rx={rx}
                        fill={accentC} opacity={isRoot ? 0.95 : 0.65} style={{ pointerEvents: 'none' }}/>
                      <rect x={-w/2} y={-h/2 + 1.6} width={w} height={isRoot ? 2 : 1.5}
                        fill={fillC} style={{ pointerEvents: 'none' }}/>

                      {/* Label */}
                      <text
                        y={isRoot ? 5.5 : 4.5}
                        textAnchor="middle"
                        fill={textC}
                        fontSize={isRoot ? 13 : type === 'subdomain' ? 11 : 10}
                        fontFamily="DM Sans, sans-serif"
                        fontWeight={isRoot ? '700' : '600'}
                        style={{ pointerEvents: 'none', userSelect: 'none' }}
                      >
                        {name.length > (isRoot ? 24 : 20) ? name.slice(0, isRoot ? 23 : 19) + '…' : name}
                      </text>

                      {/* Count badge */}
                      {count != null && (
                        <text
                          x={w/2 - 7} y={-h/2 + 12}
                          textAnchor="end"
                          fill={accentC}
                          fontSize={7.5}
                          fontWeight="700"
                          opacity={0.72}
                          style={{ pointerEvents: 'none', userSelect: 'none' }}
                        >{count}</text>
                      )}

                      {/* Collapsed pill */}
                      {_collapsed && _hiddenCount > 0 && (
                        <g style={{ pointerEvents: 'none' }}>
                          <rect x={-22} y={h/2 + 5} width={44} height={18} rx={9}
                            fill={typeFill[type]} stroke={`${accentC}80`} strokeWidth={0.9}/>
                          <text y={h/2 + 17} textAnchor="middle" fill={accentC} fontSize={8.5} fontWeight="800">
                            +{_hiddenCount}
                          </text>
                        </g>
                      )}
                    </g>
                  )
                })}
              </g>
            </g>
          </svg>
        )}

        {/* Hover tooltip */}
        {hoveredNode && (
          <NodeTooltip node={hoveredNode} x={tx.x} y={tx.y} k={tx.k} cw={dims.w} ch={dims.h}/>
        )}

        {/* Zoom controls */}
        <div className="graph-zoom-controls">
          <button className="graph-zoom-btn" onClick={() => zoomBy(1.25)} title="Zoom in">+</button>
          <button className="graph-zoom-pct-btn" onClick={fit} title="Click to fit">
            {Math.round(tx.k * 100)}%
          </button>
          <button className="graph-zoom-btn" onClick={() => zoomBy(1 / 1.25)} title="Zoom out">−</button>
        </div>

        {/* Visible rule count */}
        {!loading && layout && (
          <div className="graph-node-count">
            {visibleRules} / {rawTree?.count ?? '…'} rules visible
          </div>
        )}
      </div>

      {/* ── Legend ── */}
      <div className="graph-legend">
        <div className="graph-legend-nodes">
          <span className="graph-legend-item">
            <span className="graph-legend-swatch" style={{ background: 'rgba(99,179,237,0.55)', borderColor: '#63B3ED' }}/>
            Sub-domain
          </span>
          <span className="graph-legend-item">
            <span className="graph-legend-swatch" style={{ background: 'rgba(237,137,54,0.55)', borderColor: '#ED8936' }}/>
            Category
          </span>
          <span className="graph-legend-item">
            <span className="graph-legend-swatch graph-legend-swatch--circle" style={{ background: 'rgba(232,0,13,0.5)', borderColor: '#E8000D' }}/>
            Rule
          </span>
          <span className="graph-legend-divider"/>
          <span className="graph-legend-item">
            <span className="graph-legend-swatch graph-legend-swatch--circle" style={{ background: '#ECC94B', borderColor: '#ECC94B' }}/>
            High sev
          </span>
          <span className="graph-legend-item">
            <span className="graph-legend-swatch graph-legend-swatch--circle" style={{ background: '#E8000D', borderColor: '#E8000D' }}/>
            Critical
          </span>
        </div>
        <div className="graph-legend-shortcuts">
          <span className="graph-legend-divider"/>
          <span className="graph-legend-hint">
            <kbd className="graph-kbd">Scroll</kbd> zoom ·{' '}
            <kbd className="graph-kbd">Drag</kbd> pan ·{' '}
            <kbd className="graph-kbd">Click</kbd> expand ·{' '}
            <kbd className="graph-kbd">Esc</kbd> close ·{' '}
            <kbd className="graph-kbd">/</kbd> search
          </span>
        </div>
      </div>
    </div>
  )
}
