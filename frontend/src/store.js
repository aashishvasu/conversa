import { del, get, set } from 'idb-keyval'
import { computed, reactive, ref, watch } from 'vue'

// All conversation state lives client-side in IndexedDB (via idb-keyval).

const STORE_KEY = 'conversa_conversations'
const MODELS_KEY = 'conversa_models'
const GLOBAL_KEY = 'conversa_global' // user edits to the global defaults, persisted client-side

export const SETTING_KEYS = [
  'model',
  'temperature',
  'num_messages_to_send',
  'send_system_prompt',
  'max_tokens',
  'utility_model',
  'use_memory',
  'compression_threshold',
  'use_recall',
]

const state = reactive({ conversations: [] })
export const currentId = ref(null)
export const globalSettings = ref(null)
export const models = ref([]) // [{id, label}], cached from backend
export const sidebarOpen = ref(false) // mobile drawer toggle; desktop ignores it

let loaded = false
let savedGlobal = null // user's edited global defaults, loaded from IDB

// Loads persisted state. Call once before showing the UI.
export async function initStore() {
  state.conversations = (await get(STORE_KEY)) || []
  models.value = (await get(MODELS_KEY)) || []
  savedGlobal = (await get(GLOBAL_KEY)) || null
  // Backfill stable message ids for conversations saved before ids existed.
  for (const c of state.conversations) {
    for (const m of c.messages) if (!m.id) m.id = crypto.randomUUID()
  }
  loaded = true
  // Persist on any change, debounced so token-by-token streaming doesn't thrash IDB.
  watch(() => state.conversations, save, { deep: true })
}

let saveTimer
function save() {
  if (!loaded) return
  clearTimeout(saveTimer)
  // JSON round-trip strips the Vue reactive proxy so structured-clone can store it.
  const snapshot = JSON.parse(JSON.stringify(state.conversations))
  saveTimer = setTimeout(() => set(STORE_KEY, snapshot), 400)
}

// Write immediately, bypassing the debounce — call when a stream finishes so a quick
// page reload can't lose the final assistant message.
export function persistNow() {
  if (!loaded) return
  clearTimeout(saveTimer)
  return set(STORE_KEY, JSON.parse(JSON.stringify(state.conversations)))
}

export function cacheModels(list) {
  models.value = list
  set(MODELS_KEY, list)
}

export const conversations = computed(() =>
  state.conversations.filter((c) => !c.isTemplate),
)
export const templates = computed(() =>
  state.conversations.filter((c) => c.isTemplate),
)
export const currentConversation = computed(() =>
  state.conversations.find((c) => c.id === currentId.value) || null,
)

function blank(overrides = {}) {
  return {
    id: crypto.randomUUID(),
    title: 'New conversation',
    isTemplate: false,
    scanAssistant: false,
    settings: {}, // empty = inherit every key from globalSettings
    cards: [],
    memory: '', // rolling summary of compressed-away history
    memoryCount: 0, // how many leading non-system messages are folded into memory
    messages: [{ id: crypto.randomUUID(), role: 'system', content: '', createdAt: Date.now() }],
    createdAt: Date.now(),
    updatedAt: Date.now(),
    ...overrides,
  }
}

export function createConversation() {
  const c = blank()
  state.conversations.unshift(c)
  currentId.value = c.id
  return c
}

// Deep copy with fresh ids throughout (conversation, messages, cards).
function cloneWithNewIds(convo) {
  const c = JSON.parse(JSON.stringify(convo))
  c.id = crypto.randomUUID()
  c.messages = c.messages.map((m) => ({ ...m, id: crypto.randomUUID() }))
  c.cards = (c.cards || []).map((cd) => ({ ...cd, id: crypto.randomUUID() }))
  return c
}

export function createFromTemplate(template) {
  const c = cloneWithNewIds(template)
  c.isTemplate = false
  c.createdAt = c.updatedAt = Date.now()
  state.conversations.unshift(c)
  currentId.value = c.id
  return c
}

// Copy the current conversation into a new template (does not move/modify the original).
export function saveAsTemplate(convo) {
  const t = cloneWithNewIds(convo)
  t.isTemplate = true
  t.createdAt = t.updatedAt = Date.now()
  state.conversations.unshift(t)
  return t
}

export function deleteConversation(id) {
  state.conversations = state.conversations.filter((c) => c.id !== id)
  if (currentId.value === id) currentId.value = state.conversations[0]?.id || null
}

export function selectConversation(id) {
  currentId.value = id
}

// Per-conversation override falls back to the global default per key.
// `??` so an explicit false/0 override is respected; only null/undefined inherits.
export function effectiveSettings(convo) {
  const g = globalSettings.value || {}
  const out = {}
  for (const k of SETTING_KEYS) out[k] = convo.settings?.[k] ?? g[k]
  return out
}

export function setGlobalSettings(serverDefaults) {
  // Server defaults seed any missing keys; the user's saved edits win.
  globalSettings.value = { ...serverDefaults, ...(savedGlobal || {}) }
  if (currentId.value) return
  // Open the first real conversation, never a template; if there are none, start fresh.
  currentId.value = conversations.value[0]?.id
  if (!currentId.value) createConversation()
}

// Persist the current global settings as the user's defaults for new conversations.
export function persistGlobal() {
  savedGlobal = { ...globalSettings.value }
  set(GLOBAL_KEY, savedGlobal)
}

// Wipe everything (e.g. on logout if desired).
export async function clearAll() {
  state.conversations = []
  await del(STORE_KEY)
}

// Backup: conversations + templates (global settings are trivial to redo).
// Always an array — a single-conversation export round-trips through the same import.
export function exportData(id) {
  const list = id ? state.conversations.filter((c) => c.id === id) : state.conversations
  return JSON.parse(JSON.stringify(list))
}

// Download an export file: everything, or one conversation when id is given.
export function downloadExport(id) {
  const list = exportData(id)
  const name = (id ? list[0]?.title || 'conversation' : 'export').replace(/[^\w-]+/g, '_').slice(0, 40)
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([JSON.stringify(list, null, 2)], { type: 'application/json' }))
  a.download = `conversa-${name}-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

// Import: new ids come in as-is; a colliding id becomes a copy with fresh ids (same
// clone path as template copies), so nothing local is ever overwritten. Returns count.
// ponytail: re-importing the same file duplicates collided convos; diff-aware skip if it annoys.
export function importData(list) {
  if (!Array.isArray(list)) throw new Error('Not a conversa export')
  const have = new Set(state.conversations.map((c) => c.id))
  let added = 0
  for (const c of list) {
    if (!c?.id || !Array.isArray(c.messages)) continue
    state.conversations.unshift(have.has(c.id) ? cloneWithNewIds(c) : c)
    have.add(c.id)
    added++
  }
  if (added) persistNow()
  return added
}
