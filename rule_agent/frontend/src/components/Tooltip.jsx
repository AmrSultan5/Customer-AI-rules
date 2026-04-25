import { useState, useRef } from 'react'
import { createPortal } from 'react-dom'

export default function Tooltip({ content, children }) {
  const [state, setState] = useState({ visible: false, top: 0, left: 0, flip: false })
  const anchorRef = useRef(null)

  function show() {
    if (!anchorRef.current) return
    const rect = anchorRef.current.getBoundingClientRect()
    const flip = window.innerHeight - rect.bottom < 90
    setState({ visible: true, top: flip ? rect.top : rect.bottom + 8, left: rect.left + rect.width / 2, flip })
  }

  function hide() {
    setState(s => ({ ...s, visible: false }))
  }

  return (
    <span ref={anchorRef} className="tooltip-anchor" onMouseEnter={show} onMouseLeave={hide}>
      {children}
      {state.visible && createPortal(
        <span
          className={`tooltip-box${state.flip ? ' flip' : ''}`}
          style={{ top: state.top, left: state.left }}
        >
          {content}
        </span>,
        document.body
      )}
    </span>
  )
}
