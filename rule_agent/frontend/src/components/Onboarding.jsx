import { useState, useEffect, useLayoutEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'

// Each step optionally points at a live element via a [data-tour] selector.
// A null target renders a centred welcome card over a dimmed screen.
const STEPS = [
  {
    target: null,
    title: 'Welcome to Rule Intelligence',
    body: 'Your assistant for the Coca-Cola HBC customer data-quality rules. Ask anything in plain language, or explore the catalog visually. Here are the five things worth knowing — about a minute.',
  },
  {
    target: '[data-tour="conv-sidebar"]',
    placement: 'right',
    title: 'Your conversations',
    body: 'All your past chats live here. Start a new one in Analyst, Data Engineer, or Project Manager mode, and organise related chats into projects. Collapse or expand the panel with the arrow button at the top.',
  },
  {
    target: '[data-tour="views"]',
    title: 'Explore the rules',
    body: 'Browse and search all rules, see them as a hierarchical tree, or open an interactive graph of how they relate.',
  },
  {
    target: '[data-tour="modes"]',
    title: 'Switch how you ask',
    body: 'Analyst explains rules and answers questions. Data Engineer drafts the pipeline changes and a downloadable Databricks notebook. Project Manager turns a need into a user story.',
  },
  {
    target: '[data-tour="chat-input"]',
    title: 'Just ask, in plain language',
    body: 'Type any question about a rule, a SAP field, or a data-quality concept. Answers link straight to the rules they mention.',
  },
  {
    target: '[data-tour="rule-card"]',
    title: 'See the full breakdown',
    body: 'Open the Rule Card for the selected rule — its SAP fields, workflow steps, and the technical YAML implementation.',
  },
]

const POP_WIDTH = 320
const MARGIN = 14 // gap between highlight and popover / viewport edges

export default function Onboarding({ open, onClose }) {
  const [step, setStep] = useState(0)
  const [rect, setRect] = useState(null) // bounding rect of the current target, or null

  const current = STEPS[step]
  const isFirst = step === 0
  const isLast = step === STEPS.length - 1

  // Reset to the first step every time the tour is (re)opened.
  useEffect(() => {
    if (open) setStep(0)
  }, [open])

  // Measure the current step's target. Re-measure on step change, resize and scroll.
  useLayoutEffect(() => {
    if (!open) return
    function measure() {
      const sel = STEPS[step]?.target
      if (!sel) { setRect(null); return }
      const el = document.querySelector(sel)
      setRect(el ? el.getBoundingClientRect() : null)
    }
    measure()
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [open, step])

  const next = useCallback(() => {
    setStep(s => (s >= STEPS.length - 1 ? s : s + 1))
  }, [])
  const back = useCallback(() => setStep(s => Math.max(0, s - 1)), [])

  // Keyboard: Esc closes, arrows step.
  useEffect(() => {
    if (!open) return
    function onKey(e) {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight') { isLast ? onClose() : next() }
      else if (e.key === 'ArrowLeft') back()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, isLast, next, back, onClose])

  if (!open) return null

  // Position of the highlight box (padded slightly around the target).
  const PAD = 6
  const hl = rect && {
    top: rect.top - PAD,
    left: rect.left - PAD,
    width: rect.width + PAD * 2,
    height: rect.height + PAD * 2,
  }

  // Position the popover relative to the highlight, flipping above when low on the screen.
  let popStyle
  if (hl) {
    if (current.placement === 'right') {
      const left = Math.min(hl.left + hl.width + MARGIN, window.innerWidth - POP_WIDTH - MARGIN)
      const top = Math.max(MARGIN, Math.min(
        hl.top + hl.height / 2 - 110,
        window.innerHeight - 240 - MARGIN
      ))
      popStyle = { top, left }
    } else {
      const flip = hl.top + hl.height + MARGIN + 180 > window.innerHeight
      const top = flip
        ? Math.max(MARGIN, hl.top - MARGIN) // bottom edge will be anchored via transform
        : hl.top + hl.height + MARGIN
      let left = hl.left + hl.width / 2 - POP_WIDTH / 2
      left = Math.max(MARGIN, Math.min(left, window.innerWidth - POP_WIDTH - MARGIN))
      popStyle = flip
        ? { top, left, transform: 'translateY(-100%)' }
        : { top, left }
    }
  } else {
    // Centred welcome card.
    popStyle = { top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }
  }

  return createPortal(
    <div className="tour-root" role="dialog" aria-modal="true" aria-label="Product walkthrough">
      {hl ? (
        <>
          {/* Four blur+dim panels that together cover everything outside the spotlight */}
          <div className="tour-blur-panel" style={{ top: 0, left: 0, right: 0, height: hl.top }} />
          <div className="tour-blur-panel" style={{ top: hl.top + hl.height, left: 0, right: 0, bottom: 0 }} />
          <div className="tour-blur-panel" style={{ top: hl.top, left: 0, width: hl.left, height: hl.height }} />
          <div className="tour-blur-panel" style={{ top: hl.top, left: hl.left + hl.width, right: 0, height: hl.height }} />
          {/* Spotlight ring */}
          <div className="tour-highlight" style={{ top: hl.top, left: hl.left, width: hl.width, height: hl.height }} />
        </>
      ) : (
        <div className="tour-scrim solid" />
      )}

      <div className="tour-pop" style={{ width: POP_WIDTH, ...popStyle }}>
        <p className="tour-pop-title">{current.title}</p>
        <p className="tour-pop-body">{current.body}</p>

        <div className="tour-pop-footer">
          <div className="tour-dots" aria-hidden="true">
            {STEPS.map((_, i) => (
              <span key={i} className={`tour-dot${i === step ? ' active' : ''}`} />
            ))}
          </div>
          <div className="tour-actions">
            {!isFirst && (
              <button className="tour-btn ghost" onClick={back}>Back</button>
            )}
            <button className="tour-btn primary" onClick={isLast ? onClose : next}>
              {isLast ? 'Done' : 'Next'}
            </button>
          </div>
        </div>

        {!isLast && (
          <button className="tour-skip" onClick={onClose}>Skip tour</button>
        )}
      </div>
    </div>,
    document.body
  )
}
