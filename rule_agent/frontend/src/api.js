/**
 * Centralized API client for Rule Agent.
 *
 * VITE_API_BASE_URL  — backend origin for cross-origin deployments.
 *                      Leave empty when frontend and backend share the same domain
 *                      (served by the same nginx / reverse proxy).
 *
 * VITE_API_TOKEN     — Bearer token for API authentication.
 *
 * ⚠️  SECURITY WARNING: VITE_* variables are embedded in the browser bundle at
 *     build time. VITE_API_TOKEN is acceptable ONLY when the app is deployed
 *     behind internal access controls (VPN, SSO, corporate network, IP allowlist).
 *     Never use it on a publicly accessible deployment.
 *
 * Dev mode: Vite proxies /api/* → http://localhost:8000/* (strips /api prefix),
 *           so bare routes on FastAPI still work. Leave VITE_API_BASE_URL empty.
 * Production: /api/* routes are served by FastAPI directly (or via nginx proxy).
 */

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const API_TOKEN = import.meta.env.VITE_API_TOKEN ?? ''

export const USERNAME_KEY = 'rule_agent_username'

export function getUsername() {
  try {
    return localStorage.getItem(USERNAME_KEY) || ''
  } catch {
    return ''
  }
}

export function setUsername(name) {
  try {
    if (name) localStorage.setItem(USERNAME_KEY, name)
    else localStorage.removeItem(USERNAME_KEY)
  } catch {}
}

function _headers(method) {
  const h = {}
  if (method !== 'GET' && method !== 'HEAD') {
    h['Content-Type'] = 'application/json'
  }
  if (API_TOKEN) {
    h['Authorization'] = `Bearer ${API_TOKEN}`
  }
  // Lightweight identity — the backend get-or-creates the user from this header.
  const user = getUsername()
  if (user) {
    h['X-User'] = user
  }
  return h
}

/**
 * Fetch a path under /api. Path should start with '/'.
 * Example: apiFetch('/chat', { method: 'POST', body: JSON.stringify(data) })
 */
export async function apiFetch(path, options = {}) {
  const method = options.method ?? 'GET'
  return fetch(`${API_BASE}/api${path}`, {
    ...options,
    headers: { ..._headers(method), ...(options.headers ?? {}) },
  })
}

export async function apiGet(path) {
  return apiFetch(path, { method: 'GET' })
}

export async function apiPost(path, body) {
  return apiFetch(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/**
 * POST to /api path and return a ReadableStreamDefaultReader for SSE streaming.
 * Throws if the response is not ok (4xx/5xx).
 */
export async function apiPostStream(path, body) {
  const response = await apiFetch(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`Stream API error ${response.status}`)
  }
  return response.body.getReader()
}

// ── Workspace helpers (users / projects / conversations) ─────────────────────
// These return parsed JSON and throw on error, unlike the raw apiGet/apiPost.

async function _json(path, { method = 'GET', body } = {}) {
  const res = await apiFetch(path, {
    method,
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  if (!res.ok) {
    throw new Error(`API ${method} ${path} → ${res.status}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export const login = (username) => _json('/users/login', { method: 'POST', body: { username } })

export const listProjects = () => _json('/projects')
export const createProject = (name, instructions = null) =>
  _json('/projects', { method: 'POST', body: { name, instructions } })
export const updateProject = (id, patch) =>
  _json(`/projects/${id}`, { method: 'PATCH', body: patch })
export const deleteProject = (id) => _json(`/projects/${id}`, { method: 'DELETE' })

export function listConversations({ projectId, persona } = {}) {
  const params = new URLSearchParams()
  if (projectId != null) params.set('project_id', projectId)
  if (persona) params.set('persona', persona)
  const qs = params.toString()
  return _json(`/conversations${qs ? `?${qs}` : ''}`)
}
export const createConversation = (payload) =>
  _json('/conversations', { method: 'POST', body: payload })
export const getConversation = (id) => _json(`/conversations/${id}`)
export const renameConversation = (id, title) =>
  _json(`/conversations/${id}`, { method: 'PATCH', body: { title } })
export const moveConversation = (id, projectId) =>
  _json(`/conversations/${id}`, { method: 'PATCH', body: { project_id: projectId } })
export const deleteConversation = (id) =>
  _json(`/conversations/${id}`, { method: 'DELETE' })
