# Mobile-Responsive UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `rule_agent/frontend` fully usable on phones (≤768px) — chat, conversation history, rule detail, Browse, Tree, Graph — via full-screen overlay drawers, without changing any desktop (>768px) behavior.

**Architecture:** One new, additive `@media (max-width: 768px)` block appended to the end of `frontend/src/styles/main.css`, turning the three push-panels (conversation sidebar, rule sidebar, Browse/Tree panel) into full-screen overlays with a shared tap-to-dismiss backdrop. Three small `App.jsx` JSX additions render that backdrop. `GraphView.jsx` gets new touch event handlers (pan + pinch-zoom) added alongside its existing mouse/wheel handlers — no existing code paths are modified, only new listeners added.

**Tech Stack:** React 18 (no router), plain CSS (no CSS-in-JS/Tailwind), D3 (GraphView only). No test framework exists in this frontend (`rule_agent/frontend/package.json` has no jest/vitest/testing-library) — verification is manual via `npm run dev` + browser devtools device emulation, not automated tests. Do not add a test framework; that's out of scope per the design spec (no new dependencies).

**Spec:** `docs/superpowers/specs/2026-07-15-mobile-responsive-ui-design.md`

---

## File Structure

- Modify: `rule_agent/frontend/src/styles/main.css` — append one consolidated `@media (max-width: 768px)` block at the end of the file (after the existing final rule at line 5405). Keeping all mobile rules in one place (rather than scattered next to each component's desktop rules, which is the file's usual convention) makes this large, single-purpose addition easy to review and to delete/adjust as a unit later.
- Modify: `rule_agent/frontend/src/App.jsx` — add three backdrop `<div>` elements (conversation sidebar, rule sidebar, browser panel), each conditionally rendered and wired to the existing close handlers. No new state.
- Modify: `rule_agent/frontend/src/components/GraphView.jsx` — add `onTouchStart`/`onTouchMove`/`onTouchEnd` handlers and a `pinchRef` for two-finger pinch-zoom, attached to the same `.graph-canvas` div that already has `onMouseDown`.

No new files.

---

### Task 1: Mobile media query skeleton + viewport height fix + topbar tightening

**Files:**
- Modify: `rule_agent/frontend/src/styles/main.css:5398-5405` (end of file)

- [ ] **Step 1: Append the media query skeleton with the viewport-height and topbar rules**

Open `rule_agent/frontend/src/styles/main.css`. The file currently ends with:

```css
/* ─── Status pill loading state ──────────────────────────────────────────── */
.status-pill.loading {
  opacity: 0.7;
}

.status-pill.loading .status-dot {
  animation: statusBlink 0.9s ease-in-out infinite;
}
```

Append this after the final `}`:

```css

/* ══════════════════════════════════════════════════════════════════════════
   Mobile (≤768px) — additive only; does not alter any rule above this block
   ══════════════════════════════════════════════════════════════════════════ */
@media (max-width: 768px) {

  /* Avoid mobile-Safari layout jump when the address bar shows/hides */
  .app-shell { height: 100dvh; }

  /* ── Topbar tightening (beyond the existing 880px query) ── */
  .topbar { padding: 0 12px; gap: 8px; }
  .topbar-product { font-size: 16px; }
  .topbar-logo { width: 28px; height: 28px; }
  .sidebar-toggle-btn span { display: none; }
  .theme-toggle-btn,
  .help-btn,
  .sidebar-toggle-btn,
  .view-switch-btn {
    min-width: 40px;
    min-height: 40px;
  }
}
```

- [ ] **Step 2: Verify it doesn't break the build**

Run: `cd rule_agent/frontend && npm run build`
Expected: build succeeds with no errors (CSS is not type-checked, but a broken selector/brace would still be worth catching visually in the next step).

- [ ] **Step 3: Manual check — desktop unaffected, mobile topbar tightens**

Run: `cd rule_agent/frontend && npm run dev`, open the printed local URL in a browser.
- At the default (wide) window size, confirm the topbar looks exactly as before (brand text, view switcher labels, status pill all visible).
- Open devtools device toolbar, set width to 375px (e.g. iPhone SE). Confirm: topbar padding tightens, brand text shrinks, "Rule Card" button loses its label (icon only — this will fully apply once Task 3 also hides the sidebar-toggle-btn text; for now just confirm no layout overflow/horizontal scroll on the topbar).

- [ ] **Step 4: Commit**

```bash
git add rule_agent/frontend/src/styles/main.css
git commit -m "feat(mobile): add mobile breakpoint skeleton, viewport-height fix, topbar tightening"
```

---

### Task 2: Conversation history sidebar → full-screen overlay

**Files:**
- Modify: `rule_agent/frontend/src/styles/main.css` (append to the `@media (max-width: 768px)` block added in Task 1)
- Modify: `rule_agent/frontend/src/App.jsx:379-387`

- [ ] **Step 1: Append backdrop base style + conversation sidebar overlay rules to the CSS**

Inside the same `@media (max-width: 768px) { ... }` block from Task 1, right before its closing `}`, add:

```css

  /* ── Shared overlay backdrop (mobile only) ── */
  .mobile-overlay-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 55;
    animation: mobileBackdropIn 200ms ease both;
  }

  @keyframes mobileBackdropIn {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  /* ── Conversation history sidebar → full-screen overlay ── */
  .conv-sidebar {
    position: fixed;
    inset: 0;
    width: 0;
    z-index: 56;
    border-right: none;
  }
  .conv-sidebar:not(.collapsed) {
    width: 100vw;
  }
  .conv-float-toggle.open {
    left: calc(100vw - 44px);
    top: 16px;
    transform: none;
    width: 32px;
    height: 32px;
    border-radius: 8px;
  }
```

- [ ] **Step 2: Add the backdrop element in App.jsx**

In `rule_agent/frontend/src/App.jsx`, find:

```jsx
        <ConversationSidebar
          username={username}
          onChangeUser={handleChangeUser}
          activeConversationId={activeConversation?.id ?? null}
          onSelectConversation={handleSelectConversation}
          reloadSignal={convReload}
          open={convSidebarOpen}
        />
        <SidebarTabToggle open={convSidebarOpen} onClick={() => setConvSidebarOpen(v => !v)} />
```

Replace with:

```jsx
        {convSidebarOpen && (
          <div className="mobile-overlay-backdrop" onClick={() => setConvSidebarOpen(false)} />
        )}
        <ConversationSidebar
          username={username}
          onChangeUser={handleChangeUser}
          activeConversationId={activeConversation?.id ?? null}
          onSelectConversation={handleSelectConversation}
          reloadSignal={convReload}
          open={convSidebarOpen}
        />
        <SidebarTabToggle open={convSidebarOpen} onClick={() => setConvSidebarOpen(v => !v)} />
```

- [ ] **Step 3: Manual check**

With `npm run dev` running and devtools set to 375px width:
- Tap the conversation-history toggle tab on the left edge. Confirm the sidebar slides in and covers the full screen, with the toggle button now sitting as a small square in the top-right corner.
- Tap the backdrop is not visible while the sidebar is fully covering the screen (that's expected — the backdrop sits behind a full-width panel). Tap the top-right toggle button to close; confirm it closes.
- Resize devtools back to a wide desktop width (e.g. 1440px). Confirm the conversation sidebar behaves exactly as before (280px push-panel, floating tab slides to `left: 280px`).

- [ ] **Step 4: Commit**

```bash
git add rule_agent/frontend/src/styles/main.css rule_agent/frontend/src/App.jsx
git commit -m "feat(mobile): conversation sidebar becomes full-screen overlay on mobile"
```

---

### Task 3: Rule detail sidebar → full-screen overlay

**Files:**
- Modify: `rule_agent/frontend/src/styles/main.css` (append to the mobile block)
- Modify: `rule_agent/frontend/src/App.jsx:427-434`

- [ ] **Step 1: Append rule sidebar overlay rules to the CSS**

Inside the `@media (max-width: 768px) { ... }` block, before its closing `}`, add:

```css

  /* ── Rule detail sidebar → full-screen overlay ── */
  .rule-sidebar {
    position: fixed;
    inset: 0;
    width: 0;
    z-index: 56;
    border-left: none;
  }
  .rule-sidebar.open {
    width: 100vw;
  }
```

- [ ] **Step 2: Add the backdrop element in App.jsx**

In `rule_agent/frontend/src/App.jsx`, find:

```jsx
        <aside className={`rule-sidebar${sidebarOpen ? ' open' : ''}`}>
          <div className="rule-sidebar-header">
            <span className="rule-sidebar-title">Rule Details</span>
```

Replace with:

```jsx
        {sidebarOpen && (
          <div className="mobile-overlay-backdrop" onClick={() => setSidebarOpen(false)} />
        )}
        <aside className={`rule-sidebar${sidebarOpen ? ' open' : ''}`}>
          <div className="rule-sidebar-header">
            <span className="rule-sidebar-title">Rule Details</span>
```

- [ ] **Step 3: Manual check**

At 375px width: load any rule (e.g. via a chat message that returns a rule card, or the "Try asking" chips on the empty state), tap the "Rule Card" topbar button. Confirm the rule panel covers the full screen. Confirm its existing `×` close button (top-right of the panel header) still closes it. At desktop width, confirm the rule sidebar still opens as a 400px push-panel exactly as before.

- [ ] **Step 4: Commit**

```bash
git add rule_agent/frontend/src/styles/main.css rule_agent/frontend/src/App.jsx
git commit -m "feat(mobile): rule detail sidebar becomes full-screen overlay on mobile"
```

---

### Task 4: Browse/Tree panel → full-screen overlay + chat padding

**Files:**
- Modify: `rule_agent/frontend/src/styles/main.css` (append to the mobile block)
- Modify: `rule_agent/frontend/src/App.jsx:396-410`

- [ ] **Step 1: Append browser-panel overlay + chat padding rules to the CSS**

Inside the `@media (max-width: 768px) { ... }` block, before its closing `}`, add:

```css

  /* ── Browse/Tree panel → full-screen overlay (Graph is already full-screen) ── */
  .browser-panel {
    position: fixed;
    inset: 0;
    width: 100vw;
    z-index: 56;
    border-right: none;
  }

  /* ── Chat area padding ── */
  .chat-history { padding: 16px 12px; }
  .chat-input-row { padding: 6px 12px 14px; }
```

- [ ] **Step 2: Add the backdrop element in App.jsx**

In `rule_agent/frontend/src/App.jsx`, find:

```jsx
        {(showBrowser || showTree) && !showGraph && (
          <div className="browser-panel">
```

Replace with:

```jsx
        {(showBrowser || showTree) && !showGraph && (
          <>
            <div
              className="mobile-overlay-backdrop"
              onClick={() => { setShowBrowser(false); setShowTree(false) }}
            />
            <div className="browser-panel">
```

Then find the matching closing tags a few lines down:

```jsx
            )}
          </div>
        )}

        <main className="chat-main">
```

Replace with:

```jsx
            )}
            </div>
          </>
        )}

        <main className="chat-main">
```

- [ ] **Step 3: Manual check**

At 375px width: tap "Browse" in the view switcher. Confirm the rule browser covers the full screen. Tap its existing close (×) control; confirm it returns to chat. Repeat for "Tree". Confirm "Graph" still works as before (it was already full-screen). At desktop width, confirm Browse/Tree still render as the 320px push-panel exactly as before.

- [ ] **Step 4: Commit**

```bash
git add rule_agent/frontend/src/styles/main.css rule_agent/frontend/src/App.jsx
git commit -m "feat(mobile): browse/tree panel becomes full-screen overlay, tighten chat padding"
```

---

### Task 5: GraphView touch pan (single finger)

**Files:**
- Modify: `rule_agent/frontend/src/components/GraphView.jsx:209-226` (add new function after `onMouseDown`)
- Modify: `rule_agent/frontend/src/components/GraphView.jsx:344-348` (attach new handlers to `.graph-canvas`)

- [ ] **Step 1: Add a `pinchRef` next to the existing `dragRef`**

In `rule_agent/frontend/src/components/GraphView.jsx`, find:

```jsx
  const containerRef = useRef(null)
  const searchRef    = useRef(null)
  const dragRef      = useRef(null)
```

Replace with:

```jsx
  const containerRef = useRef(null)
  const searchRef    = useRef(null)
  const dragRef      = useRef(null)
  const pinchRef      = useRef(null)
```

- [ ] **Step 2: Add touch handlers after the existing `onMouseDown`**

Find the existing `onMouseDown` function (ends right before `function toggle(id) {`):

```jsx
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

  function toggle(id) {
```

Insert a new block between them (leaving `onMouseDown` and `toggle` untouched):

```jsx
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

  // Touch pan (single finger). Pinch-zoom (two fingers) is added in Task 6.
  function onTouchStart(e) {
    if (e.touches.length === 1) {
      const t = e.touches[0]
      dragRef.current = { sx: t.clientX, sy: t.clientY, tx: tx.x, ty: tx.y }
    }
  }

  function onTouchMove(e) {
    if (e.touches.length === 1 && dragRef.current) {
      e.preventDefault()
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
```

- [ ] **Step 3: Attach the new handlers and disable native touch scrolling on the canvas**

Find:

```jsx
      <div
        ref={containerRef}
        className="graph-canvas"
        onMouseDown={onMouseDown}
        style={{ cursor: dragRef.current ? 'grabbing' : 'grab' }}
      >
```

Replace with:

```jsx
      <div
        ref={containerRef}
        className="graph-canvas"
        onMouseDown={onMouseDown}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        style={{ cursor: dragRef.current ? 'grabbing' : 'grab', touchAction: 'none' }}
      >
```

`touchAction: 'none'` stops the browser's native scroll/zoom gestures from fighting with our own pan/zoom on the canvas; it's an inline style (not a CSS rule), has no effect on desktop (no touch input there), and doesn't touch any existing CSS file rule.

- [ ] **Step 4: Manual check**

Run `npm run dev`, open devtools, enable device toolbar (this simulates touch events in Chrome). Open Graph view, drag on the canvas with the simulated touch pointer. Confirm the graph pans. Confirm mouse drag-to-pan still works identically when device toolbar is off.

- [ ] **Step 5: Commit**

```bash
git add rule_agent/frontend/src/components/GraphView.jsx
git commit -m "feat(mobile): add single-finger touch pan to Graph view"
```

---

### Task 6: GraphView pinch-to-zoom (two fingers)

**Files:**
- Modify: `rule_agent/frontend/src/components/GraphView.jsx` (extend the touch handlers added in Task 5)

- [ ] **Step 1: Add a distance helper and extend the touch handlers for two-finger pinch**

Find the touch handlers added in Task 5:

```jsx
  // Touch pan (single finger). Pinch-zoom (two fingers) is added in Task 6.
  function onTouchStart(e) {
    if (e.touches.length === 1) {
      const t = e.touches[0]
      dragRef.current = { sx: t.clientX, sy: t.clientY, tx: tx.x, ty: tx.y }
    }
  }

  function onTouchMove(e) {
    if (e.touches.length === 1 && dragRef.current) {
      e.preventDefault()
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
```

Replace with:

```jsx
  // Touch pan (single finger) + pinch-to-zoom (two fingers).
  function touchDistance(touches) {
    const dx = touches[0].clientX - touches[1].clientX
    const dy = touches[0].clientY - touches[1].clientY
    return Math.hypot(dx, dy)
  }

  function onTouchStart(e) {
    if (e.touches.length === 1) {
      const t = e.touches[0]
      dragRef.current = { sx: t.clientX, sy: t.clientY, tx: tx.x, ty: tx.y }
    } else if (e.touches.length === 2) {
      dragRef.current = null
      pinchRef.current = { dist: touchDistance(e.touches), k: tx.k }
    }
  }

  function onTouchMove(e) {
    if (e.touches.length === 1 && dragRef.current) {
      e.preventDefault()
      const t = e.touches[0]
      const { tx: stx, ty: sty, sx, sy } = dragRef.current
      setTx(prev => ({ ...prev, x: stx + t.clientX - sx, y: sty + t.clientY - sy }))
    } else if (e.touches.length === 2 && pinchRef.current) {
      e.preventDefault()
      const rect = containerRef.current.getBoundingClientRect()
      const midX = (e.touches[0].clientX + e.touches[1].clientX) / 2 - rect.left
      const midY = (e.touches[0].clientY + e.touches[1].clientY) / 2 - rect.top
      const factor = touchDistance(e.touches) / pinchRef.current.dist
      setTx(t => {
        const k = Math.min(Math.max(pinchRef.current.k * factor, MIN_SCALE), MAX_SCALE)
        return { x: midX - (midX - t.x) * (k / t.k), y: midY - (midY - t.y) * (k / t.k), k }
      })
    }
  }

  function onTouchEnd(e) {
    if (e.touches.length === 0) {
      dragRef.current = null
      pinchRef.current = null
    }
  }
```

- [ ] **Step 2: Manual check**

Chrome devtools device toolbar supports simulating pinch via Ctrl+scroll or the two-finger touch emulation — alternatively, test on a real phone against the dev server (find your machine's LAN IP, run `npm run dev -- --host`, open `http://<lan-ip>:5173` on the phone). Confirm two-finger pinch zooms in/out smoothly and stays clamped between the existing min/max zoom (same limits the +/- buttons and mouse wheel already respect). Confirm single-finger pan and mouse-based pan/zoom still work unchanged.

- [ ] **Step 3: Commit**

```bash
git add rule_agent/frontend/src/components/GraphView.jsx
git commit -m "feat(mobile): add two-finger pinch-to-zoom to Graph view"
```

---

### Task 7: Full manual verification pass

**Files:** none (verification only)

- [ ] **Step 1: Desktop regression check**

Run `cd rule_agent/frontend && npm run dev`. At a desktop window width (≥1024px), click through every view (Chat, Browse, Tree, Graph), open both sidebars, and confirm the app looks and behaves pixel-identical to how it did before this change (this is the hard constraint from the spec — no desktop regressions).

- [ ] **Step 2: Mobile walkthrough at 375px and 768px**

In devtools device toolbar, test at both 375px (phone) and 768px (the breakpoint edge) widths:
- Chat: send a message, confirm bubbles/input reflow without horizontal scroll.
- Open conversation history via the floating tab; confirm full-screen overlay, confirm the corner toggle closes it.
- Open a rule card, confirm the rule sidebar overlay opens full-screen and its `×` closes it.
- Open Browse, then Tree; confirm both take over the full screen and their close controls work.
- Open Graph; confirm it's full-screen (as it always was), pan/zoom via touch works, and the existing close button works.
- Rotate width just above 768px (e.g. 769px, 800px) and confirm the layout snaps back to the desktop push-panel behavior.

- [ ] **Step 3: Report results**

If every check in Steps 1–2 passes, the feature is complete — no further commit needed for this task. If anything fails, fix it in the relevant task's files and amend that task's commit history with a new fix commit (do not silently move on).

---

## Self-Review Notes

- Spec coverage: viewport-height fix (Task 1), topbar tightening (Task 1), conversation sidebar overlay (Task 2), rule sidebar overlay (Task 3), browse/tree overlay (Task 4), chat padding (Task 4), Graph touch pan (Task 5), Graph pinch-zoom (Task 6), full manual verification incl. desktop-unaffected check (Task 7). Admin pages explicitly out of scope per spec — no task touches them.
- All CSS additions live inside the single new `@media (max-width: 768px)` block; no existing rule is edited, satisfying "don't change the laptop version."
- `GraphView.jsx` changes only add new functions/handlers and a new ref; the existing `onMouseDown`, `onWheel`, and `zoomBy` are untouched.
