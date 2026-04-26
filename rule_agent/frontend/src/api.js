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

function _headers(method) {
  const h = {}
  if (method !== 'GET' && method !== 'HEAD') {
    h['Content-Type'] = 'application/json'
  }
  if (API_TOKEN) {
    h['Authorization'] = `Bearer ${API_TOKEN}`
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
