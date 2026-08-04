// Shared persona metadata — single source of truth for the three chat personas.
//
// Previously each of ChatBox.jsx, ConversationSidebar.jsx and AdminDashboard.jsx
// hardcoded this list independently, with inconsistent labels between them
// (e.g. ChatBox said "Data Engineer", ConversationSidebar said "Engineer").
// Centralizing here does NOT change any on-screen text — each call site maps
// onto whichever field it used to hardcode (see comments at each field).
export const PERSONAS = [
  // label      — full name, used by ChatBox's mode toggle and AdminDashboard's
  //              MODE_LABELS (both previously spelled these out in full).
  // shortLabel — abbreviated name, used by ConversationSidebar's persona picker
  //              and conversation-row badges (previously that file's own
  //              `PERSONAS[].label` field, which was already abbreviated).
  // badge      — single/double-letter badge, used nowhere visibly today but
  //              kept for parity with ConversationSidebar's old `short` field.
  { id: 'analyst',  label: 'Analyst',         shortLabel: 'Analyst',  badge: 'A'  },
  { id: 'engineer', label: 'Data Engineer',   shortLabel: 'Engineer', badge: 'E'  },
  { id: 'pm',       label: 'Project Manager', shortLabel: 'PM',       badge: 'PM' },
]

export const PERSONA_IDS = PERSONAS.map(p => p.id)

export function personaById(id) {
  return PERSONAS.find(p => p.id === id)
}
