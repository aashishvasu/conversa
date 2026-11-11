import { ref } from 'vue'
import { tr } from '../i18n/index.js'

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

const ERROR_KEYS = { no_such_run: 'errors.noSuchRun', unknown_effort: 'errors.unknownEffort', no_such_transfer: 'errors.noSuchTransfer', transfer_too_large: 'errors.transferTooLarge', transfers_full: 'errors.transfersFull' }

async function responseError(res) {
  try {
    const detail = (await res.json()).detail
    if (Array.isArray(detail)) {
      const msg = detail.map((d) => `${d.loc?.filter((x) => x !== 'body').join('.') || 'field'}: ${d.msg}`).join(', ')
      return new Error(msg || tr('errors.server', { status: res.status }))
    }
    if (detail && typeof detail === 'object') {
      const error = new Error(ERROR_KEYS[detail.code] ? tr(ERROR_KEYS[detail.code], detail) : typeof detail.message === 'string' ? detail.message : tr('errors.server', { status: res.status }))
      if (detail.code) error.code = detail.code
      return error
    }
    if (typeof detail === 'string') return new Error(detail)
  } catch { /* use the status fallback */ }
  return new Error(tr('errors.server', { status: res.status }))
}

// Every HTTP failure carries error.status, so callers can tell it from a network failure, which has none.
async function check(res) {
  if (res.status === 401) {
    logout()
    throw Object.assign(new Error(tr('errors.sessionExpired')), { status: 401 })
  }
  if (!res.ok) throw Object.assign(await responseError(res), { status: res.status })
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
  if (!res.ok) throw await responseError(res)
  const { token } = await res.json()
  localStorage.setItem(TOKEN_KEY, token)
}

export async function fetchSettings() {
  return (await check(await fetch('/api/settings', { headers: authHeaders(false) }))).json()
}

export async function fetchModels() {
  return (await check(await fetch('/api/models', { headers: authHeaders(false) }))).json()
}

// A 404 from attachChatTurn: the server no longer holds the turn.
export function isNoSuchTurn(error) {
  return error?.code === 'no_such_turn'
}

// Start a chat turn the server generates detached from this request, or attach to it if turnId already exists.
// onFrame receives every parsed frame as is, error frames included; resolves when the stream closes.
export async function startChatTurn(turnId, payload, onFrame, signal) {
  const res = await check(
    await fetch('/api/chat', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ ...payload, turn_id: turnId }),
      signal,
    }),
  )
  await readSSE(res, onFrame)
}

// Replay a turn from its first frame, then one { live: true } marker, then live frames.
// An unknown turn rejects with status 404 and code no_such_turn.
export async function attachChatTurn(turnId, onFrame, signal) {
  const res = await check(
    await fetch(`/api/chat/${encodeURIComponent(turnId)}/stream`, { headers: authHeaders(false), signal }),
  )
  await readSSE(res, onFrame)
}

// Cancel and forget a turn. Never throws: the server TTL cleans up a failed discard.
export async function discardChatTurn(turnId) {
  try {
    await check(await fetch(`/api/chat/${encodeURIComponent(turnId)}`, { method: 'DELETE', headers: authHeaders(false) }))
  } catch { /* left to the server TTL */ }
}

// Fetch the server-rendered system prompt for a chat payload without calling a provider.
// Returns a string or a [stable, volatile] list when cache mode is on.
export async function fetchSystemPreview(payload, signal) {
  const res = await check(
    await fetch('/api/chat/system-preview', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(payload),
      signal,
    }),
  )
  return (await res.json()).system
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

// --- Transient transfers ---------------------------------------------------------------
// An export payload is held on the server under a phrase for a short TTL, then retrieved by pasting the phrase on another device.
// Phrases never appear in URLs.

export async function createTransfer(scope, data) {
  const res = await fetch('/api/transfers', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ scope, data }) })
  if (res.status === 413 || res.status === 507) throw await responseError(res)
  return (await check(res)).json()
}

export async function retrieveTransfer(phrase) {
  return (await check(await fetch('/api/transfers/retrieve', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ phrase }) }))).json()
}

// --- Research runs ---------------------------------------------------------------------
// A run lives in the server process, so closing the tab leaves it running.
// Reconnect with the last seq seen and the events missed in between are replayed.

// Prepare from the ordinary assembled system/messages context before a research placeholder exists.
export async function prepareResearch(body, signal) {
  const res = await fetch('/api/research/prepare', { method: 'POST', headers: authHeaders(), body: JSON.stringify(body), signal })
  if (res.status === 400 || res.status === 502) throw await responseError(res)
  return (await check(res)).json()
}

export async function startResearch(body) {
  const res = await fetch('/api/research', { method: 'POST', headers: authHeaders(), body: JSON.stringify(body) })
  if (res.status === 400) throw await responseError(res)
  return (await check(res)).json()
}

export async function fetchResearchState(id, after = 0) {
  const res = await fetch(`/api/research/${id}?after=${after}`, { headers: authHeaders(false) })
  return (await check(res)).json()
}

export async function ackResearch(id) {
  try {
    const res = await fetch(`/api/research/${id}/ack`, { method: 'POST', headers: authHeaders(false) })
    return (await check(res)).json()
  } catch {
    return null
  }
}

// Done with this run.
// A running one is cancelled and kept, so its stream can still deliver the final frame.
// A finished one is forgotten, which is what saving the payload into a workspace triggers.
export async function discardResearch(id) {
  return (await check(await fetch(`/api/research/${id}`, { method: 'DELETE', headers: authHeaders(false) }))).json()
}

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
