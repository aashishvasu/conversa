import { ref } from 'vue'
import { tr } from '../i18n.js'

// /api/login exchanges the password for the stored bearer token. A 401 clears it and returns to login.

const TOKEN_KEY = 'conversa_token'
export const authed = ref(false)

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function logout() {
  localStorage.removeItem(TOKEN_KEY)
  authed.value = false
}

function authHeaders(json = true) {
  const h = { Authorization: `Bearer ${getToken()}` }
  if (json) h['Content-Type'] = 'application/json'
  return h
}

const ERROR_KEYS = { no_such_run: 'errors.noSuchRun', unknown_effort: 'errors.unknownEffort' }

async function responseError(res) {
  try {
    const detail = (await res.json()).detail
    if (detail && typeof detail === 'object') {
      if (ERROR_KEYS[detail.code]) return tr(ERROR_KEYS[detail.code], detail)
      if (typeof detail.message === 'string') return detail.message
    }
    if (typeof detail === 'string') return detail
  } catch { /* use the status fallback */ }
  return tr('errors.server', { status: res.status })
}

async function check(res) {
  if (res.status === 401) {
    logout()
    throw new Error(tr('errors.sessionExpired'))
  }
  if (!res.ok) throw new Error(await responseError(res))
  maybeRefresh()
  return res
}

// Past the token's half-life, trade it for a fresh full-TTL one.
// Best-effort: on any failure the current token keeps working until exp.
// The refresh response runs through check() too, but the new token is young, so this can't loop.
let refreshing = false
async function maybeRefresh() {
  const token = getToken()
  if (!token || refreshing) return
  try {
    // JWT payloads are base64url; atob wants plain base64.
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    const { iat, exp } = JSON.parse(atob(b64))
    // Pre-renewal tokens have no iat, so the NaN comparison is false and they refresh now.
    if (Date.now() / 1000 < (iat + exp) / 2) return
  } catch {
    return
  }
  refreshing = true
  try {
    const res = await check(await fetch('/api/refresh', { method: 'POST', headers: authHeaders(false) }))
    localStorage.setItem(TOKEN_KEY, (await res.json()).token)
  } catch { /* keep the old token */ } finally {
    refreshing = false
  }
}

// Exchange password for a token.
// Throws on wrong password.
export async function login(password) {
  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
  if (res.status === 401) throw new Error(tr('errors.wrongPassword'))
  if (!res.ok) throw new Error(await responseError(res))
  const { token } = await res.json()
  localStorage.setItem(TOKEN_KEY, token)
}

export async function fetchSettings() {
  return (await check(await fetch('/api/settings', { headers: authHeaders(false) }))).json()
}

export async function fetchModels() {
  return (await check(await fetch('/api/models', { headers: authHeaders(false) }))).json()
}

// Streams assistant text.
// Calls onText(chunk) per token; onTrace(type, value) for non-visible activity; onUsage(usage) once per turn.
// Resolves when done.
export async function streamChat(payload, onText, signal, onTrace, onUsage) {
  const res = await check(
    await fetch('/api/chat', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(payload),
      signal,
    }),
  )

  await readSSE(res, (data) => {
    if (data.error) throw new Error(data.error)
    if (data.text) onText(data.text)
    else if (data.think && onTrace) onTrace('thinking', data.think)
    else if (data.search && onTrace) onTrace('search', data.search)
    else if (data.fetch && onTrace) onTrace('fetch', data.fetch)
    else if (data.results && onTrace) onTrace('results', data.results)
    else if (data.tool && onTrace) onTrace('tool', data.tool)
    else if (data.usage && onUsage) onUsage(data.usage)
  })
}

// Read an SSE body, calling onEvent with each decoded frame.
// Both server streams frame the same way.
async function readSSE(res, onEvent) {
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const line = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      if (line.startsWith('data: ')) onEvent(JSON.parse(line.slice(6)))
    }
  }
}

// --- Research runs ---------------------------------------------------------------------
// A run lives in the server process, so closing the tab leaves it running.
// Reconnect with the last seq seen and the events missed in between are replayed.

// Prepare from the ordinary assembled system/messages context before a research placeholder exists.
export async function prepareResearch(body) {
  const res = await fetch('/api/research/prepare', { method: 'POST', headers: authHeaders(), body: JSON.stringify(body) })
  if (res.status === 400 || res.status === 502) throw new Error(await responseError(res))
  return (await check(res)).json()
}

export async function startResearch(body) {
  const res = await fetch('/api/research', { method: 'POST', headers: authHeaders(), body: JSON.stringify(body) })
  if (res.status === 400) throw new Error(await responseError(res))
  return (await check(res)).json()
}

// Done with this run.
// A running one is cancelled and kept, so its stream can still deliver the final frame.
// A finished one is forgotten, which is what saving the payload into a workspace triggers.
export async function discardResearch(id) {
  return (await check(await fetch(`/api/research/${id}`, { method: 'DELETE', headers: authHeaders(false) }))).json()
}

// Tails a run until it ends. onEvent gets every event; the last one is kind 'final' and carries the payload.
export async function streamResearch(id, after, onEvent, signal) {
  const res = await fetch(`/api/research/${id}/stream?after=${after || 0}`, { headers: authHeaders(false), signal })
  if (res.status === 404) {
    try {
      const detail = (await res.clone().json()).detail
      if (detail?.code === 'no_such_run') {
        const error = new Error(detail.message)
        error.code = detail.code
        throw error
      }
    } catch (error) {
      if (error?.code === 'no_such_run') throw error
    }
  }
  await readSSE(await check(res), onEvent)
}
