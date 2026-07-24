import { useState, useRef, useEffect, useCallback, useId } from 'react'

const ChevronIcon = () => (
  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
    <path d="M2 3.75 5 6.75 8 3.75" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const CheckIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M2.2 6.3 4.8 9 9.8 3.4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

/**
 * Custom KB switcher — replaces a native <select> with a keyboard-accessible
 * popover listbox so non-selectable (still-ingesting) KBs can render as a
 * disabled row with a spinner instead of a flat "(updating…)" option label.
 *
 * Same value/onChange(kbId) contract as the <select> it replaces. Selecting
 * a non-selectable item is a no-op, matching the previous `disabled` guard.
 */
export default function KbDropdown({
  knowledgeBases,
  value,
  onChange,
  ariaLabel = 'Knowledge base',
  className = '',
}) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const rootRef = useRef(null)
  const triggerRef = useRef(null)
  const listRef = useRef(null)
  const btnId = useId()
  const listId = useId()

  const selected = knowledgeBases.find(kb => kb.id === value) ?? null

  const close = useCallback((refocus) => {
    setOpen(false)
    setActiveIndex(-1)
    if (refocus) triggerRef.current?.focus()
  }, [])

  // Close on outside click.
  useEffect(() => {
    if (!open) return
    function onDocMouseDown(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) close(false)
    }
    document.addEventListener('mousedown', onDocMouseDown)
    return () => document.removeEventListener('mousedown', onDocMouseDown)
  }, [open, close])

  // On open: seed the active row from the current selection and focus the list.
  useEffect(() => {
    if (!open) return
    const idx = knowledgeBases.findIndex(kb => kb.id === value)
    setActiveIndex(idx >= 0 ? idx : 0)
    listRef.current?.focus()
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open || activeIndex < 0) return
    listRef.current?.querySelector(`[data-index="${activeIndex}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [open, activeIndex])

  const isSelectable = (idx) => knowledgeBases[idx]?.selectable !== false

  function moveActive(delta) {
    setActiveIndex(i => {
      const count = knowledgeBases.length
      if (count === 0) return i
      let next = i
      for (let step = 0; step < count; step++) {
        next = (next + delta + count) % count
        if (isSelectable(next)) return next
      }
      return i
    })
  }

  function jumpTo(start, delta) {
    const count = knowledgeBases.length
    if (count === 0) return
    let idx = start
    for (let step = 0; step < count; step++) {
      if (isSelectable(idx)) { setActiveIndex(idx); return }
      idx = (idx + delta + count) % count
    }
  }

  function selectIndex(idx) {
    const kb = knowledgeBases[idx]
    if (!kb || !isSelectable(idx)) return
    onChange(kb.id)
    close(true)
  }

  function onTriggerKeyDown(e) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setOpen(true)
    }
  }

  function onListKeyDown(e) {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        moveActive(1)
        break
      case 'ArrowUp':
        e.preventDefault()
        moveActive(-1)
        break
      case 'Home':
        e.preventDefault()
        jumpTo(0, 1)
        break
      case 'End':
        e.preventDefault()
        jumpTo(knowledgeBases.length - 1, -1)
        break
      case 'Enter':
      case ' ':
        e.preventDefault()
        selectIndex(activeIndex)
        break
      case 'Escape':
        e.preventDefault()
        close(true)
        break
      case 'Tab':
        close(false)
        break
      default:
        break
    }
  }

  return (
    <div className={`kb-dropdown ${className}`} ref={rootRef}>
      <button
        type="button"
        id={btnId}
        ref={triggerRef}
        className="kb-dropdown-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={ariaLabel}
        onClick={() => setOpen(o => !o)}
        onKeyDown={onTriggerKeyDown}
      >
        <span className="kb-dropdown-trigger-label">
          {selected ? selected.name : 'Select knowledge base'}
        </span>
        <span className={`kb-dropdown-chevron${open ? ' open' : ''}`} aria-hidden="true">
          <ChevronIcon />
        </span>
      </button>

      {open && (
        <ul
          className="kb-dropdown-list"
          role="listbox"
          id={listId}
          aria-labelledby={btnId}
          aria-activedescendant={activeIndex >= 0 ? `${listId}-opt-${activeIndex}` : undefined}
          ref={listRef}
          tabIndex={-1}
          onKeyDown={onListKeyDown}
        >
          {knowledgeBases.map((kb, idx) => {
            const disabled = kb.selectable === false
            const isSelected = kb.id === value
            return (
              <li
                key={kb.id}
                id={`${listId}-opt-${idx}`}
                data-index={idx}
                role="option"
                aria-selected={isSelected}
                aria-disabled={disabled}
                className={`kb-dropdown-item${isSelected ? ' selected' : ''}${disabled ? ' disabled' : ''}${idx === activeIndex ? ' active' : ''}`}
                onMouseEnter={() => setActiveIndex(idx)}
                onClick={() => selectIndex(idx)}
              >
                <span className="kb-dropdown-item-check" aria-hidden="true">
                  {isSelected && <CheckIcon />}
                </span>
                <span className="kb-dropdown-item-label">{kb.name}</span>
                {disabled && (
                  <span className="kb-dropdown-item-status">
                    <span className="kb-dropdown-spinner" aria-hidden="true" />
                    updating…
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
