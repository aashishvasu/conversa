import { ref } from 'vue'

// Auth: password is exchanged once at /api/login for a signed token, which is what we store and send.
// On any 401 we drop the token and flip back to the login screen.

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

function check(res) {
  if (res.status === 401) {
    logout()
    throw new Error('Session expired')
  }
  if (!res.ok) throw new Error(`Server error ${res.status}`)
  maybeRefresh() // fire-and-forget sliding renewal on any successful call
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
    // Pre-renewal tokens have no iat → NaN comparison is false → refresh them now.
    if (Date.now() / 1000 < (iat + exp) / 2) return
  } catch {
    return
  }
  refreshing = true
  try {
    const res = check(await fetch('/api/refresh', { method: 'POST', headers: authHeaders(false) }))
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
  if (res.status === 401) throw new Error('Wrong password')
  if (!res.ok) throw new Error(`Server error ${res.status}`)
  const { token } = await res.json()
  localStorage.setItem(TOKEN_KEY, token)
}

export async function fetchSettings() {
  return check(await fetch('/api/settings', { headers: authHeaders(false) })).json()
}

export async function fetchModels() {
  return check(await fetch('/api/models', { headers: authHeaders(false) })).json()
}

// Fetch a page as readable markdown.
// The server does it because CORS blocks the browser from nearly every page.
// A 400 carries the reason (blocked target, unreachable host, no readable content), which is the part worth showing.
export async function fetchUrl(url, topic) {
  const res = await fetch('/api/fetch', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ url, topic }),
  })
  if (res.status === 400) throw new Error((await res.json()).detail)
  return check(res).json()
}

// Streams assistant text.
// Calls onText(chunk) per token; onTrace(type, value) for non-visible activity (type 'thinking' | 'search' → string, 'results' → [{title,url}]); resolves when done.
export async function streamChat(payload, onText, signal, onTrace) {
  const res = check(
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

// One round of questions about a brief, before any run starts.
// The answers are folded into the brief, so the planner sees the scope rather than inferring it.
export async function clarifyResearch(brief, model) {
  const res = await fetch('/api/research/clarify', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ brief, model }),
  })
  if (res.status === 400) throw new Error((await res.json()).detail)
  return (await check(res).json()).questions
}

export async function startResearch(body) {
  const res = await fetch('/api/research', { method: 'POST', headers: authHeaders(), body: JSON.stringify(body) })
  if (res.status === 400) throw new Error((await res.json()).detail)
  return check(res).json()
}

// Done with this run.
// A running one is cancelled and kept, so its stream can still deliver the final frame.
// A finished one is forgotten, which is what saving the payload into a workspace triggers.
export async function discardResearch(id) {
  return check(await fetch(`/api/research/${id}`, { method: 'DELETE', headers: authHeaders(false) })).json()
}

// Tails a run until it ends. onEvent gets every event; the last one is kind 'final' and carries the payload.
export async function streamResearch(id, after, onEvent, signal) {
  const res = check(
    await fetch(`/api/research/${id}/stream?after=${after || 0}`, { headers: authHeaders(false), signal }),
  )
  await readSSE(res, onEvent)
}
