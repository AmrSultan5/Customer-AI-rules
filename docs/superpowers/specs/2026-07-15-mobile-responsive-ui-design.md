# Mobile-Responsive UI

## Goal

Make the Rule Agent frontend (`rule_agent/frontend`) fully usable on phones (chat,
conversation history, rule detail panel, Browse, Tree, Graph) without changing
desktop/laptop behavior in any way.

## Constraints

- No changes to existing desktop CSS rules or their visual output at widths above
  the new breakpoint.
- No new dependencies.
- Admin pages (`AdminDashboard.jsx`, `AdminPage.jsx`) are out of scope — desktop-only,
  no regressions required beyond what already exists (tables already scroll via
  existing `overflow-x` patterns elsewhere in the app).

## Breakpoint

New `@media (max-width: 768px)` block(s) added to `frontend/src/styles/main.css`,
additive only. Existing breakpoints (640px, 860px, 880px, 960px, 1100px) are
untouched.

## Layout strategy

`.app-body` is currently a flex row: `.conv-sidebar` (280px) | main content
(`.browser-panel` 320px + `.chat-main`, or `.chat-main` alone) | `.rule-sidebar`
(400px, collapsible). Graph view already renders as a full-screen `.graph-overlay`
regardless of width.

Below 768px, chat becomes the single full-width view. The three panel types below
become full-screen overlays stacked above chat, reusing existing open/close state
in `App.jsx` — no new navigation model, no new state machine:

1. **Conversation history (`.conv-sidebar`)** — opens to 100vw instead of 280px.
   The floating tab toggle (`.conv-float-toggle`) repositions under the media query
   from `left: 280px` (its desktop "open" position) to a fixed top-right corner
   affordance, since sliding to the panel's edge no longer makes sense at full
   width. A new backdrop element is added (rendered in `App.jsx`, hidden via CSS
   above the breakpoint) that closes the panel on tap, reusing the existing
   `setConvSidebarOpen` handler.

2. **Rule detail sidebar (`.rule-sidebar`)** — opens to 100vw instead of 400px.
   Already has a header close (`×`) button wired to `setSidebarOpen(false)`; add a
   backdrop for tap-to-dismiss convenience, same pattern as above.

3. **Browse/Tree (`.browser-panel`)** — currently a 320px push-panel; adopts the
   same full-screen overlay treatment `.graph-overlay` already uses. Existing close
   buttons inside `RuleBrowser`/`TreeView` continue to work; add a backdrop for
   consistency.

All three backdrops are simple `<div className="mobile-overlay-backdrop" onClick={...}/>`
elements, CSS-gated with `display: none` above 768px so they have zero effect on
desktop markup/behavior beyond being present-but-invisible in the DOM.

## Graph view touch support

`GraphView.jsx` currently wires pan (`onMouseDown`/`mousemove`/`mouseup`) and zoom
(`wheel`) to mouse-only events; there is no touch handling at all. Add, alongside
the existing handlers (not replacing them):

- `touchstart`/`touchmove`/`touchend` for single-finger drag-to-pan, mirroring the
  existing `dragRef`-based mouse pan logic.
- Two-finger pinch-to-zoom: track the distance between two active touch points on
  `touchmove` and scale `tx.k` proportionally to the change in distance, reusing
  the existing `MIN_SCALE`/`MAX_SCALE` clamps from `zoomBy`.

This is purely additive (new event listeners); existing mouse/wheel code paths are
untouched, so desktop interaction is unaffected.

## Topbar

At ≤768px (beyond what the existing 880px query already hides — `.topbar-sub`,
view-switch button labels, `.status-pill`):

- Reduce topbar horizontal padding and brand font size slightly so the brand mark,
  view switcher, and action icons fit without overflow at ~375–430px widths.
- "Rule Card" button drops to icon-only (label hidden), matching how view-switch
  buttons already lose their labels at 880px.
- Icon buttons (`theme-toggle-btn`, `help-btn`, `sidebar-toggle-btn`, view-switch
  buttons) get a minimum 40×40px tap target via padding, for touch accuracy.

## Chat area

Message bubbles and the input row are already fluid (`max-width: 800px` +
`width: 100%`, bubble `max-width: 100%`, `overflow-wrap: anywhere`), so they should
reflow correctly with only minor padding reduction. `FieldTable` already wraps in
`.field-table-wrapper { overflow-x: auto }`, so wide rule-field tables scroll
horizontally rather than breaking layout — no change needed.

## Viewport height

`.app-shell` uses `height: 100vh`. Inside the mobile media query only, override to
`height: 100dvh` (`100vh` remains as the pre-`dvh` fallback via cascade order) to
avoid the layout jump that occurs on mobile Safari when the address bar
shows/hides. Desktop rule is untouched.

## Out of scope

- Admin dashboard responsiveness.
- Any new bottom-tab-bar or app-shell navigation model — reusing existing
  toggle/close state exactly as-is.
- Changing default panel-open state on load (still closed by default on both
  desktop and mobile).

## Testing

No unit-testable business logic changes (CSS + touch-event wiring). Verification
is manual: load the app at ≤768px viewport (browser devtools device emulation) and
confirm each panel opens full-screen, closes via backdrop tap and existing close
controls, Graph view pans/zooms via touch, and the desktop layout (>768px) is
pixel-identical to before the change.
