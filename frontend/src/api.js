import { ref } from 'vue'

// Auth: password is exchanged once at /api/login for a signed token, which is what
// we store and send. On any 401 we drop the token and flip back to the login screen.

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
  return res
}

// Exchange password for a token. Throws on wrong password.
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

// Streams assistant text. Calls onText(chunk) per token; resolves when done.
export async function streamChat(payload, onText, signal) {
  const res = check(
    await fetch('/api/chat', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(payload),
      signal,
    }),
  )

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
      if (!line.startsWith('data: ')) continue
      const data = JSON.parse(line.slice(6))
      if (data.error) throw new Error(data.error)
      if (data.text) onText(data.text)
    }
  }
}
