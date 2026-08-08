import { del, get, set } from 'idb-keyval'
import { computed, reactive, ref, watch } from 'vue'

// All conversation state lives client-side in IndexedDB (via idb-keyval).

const STORE_KEY = 'conversa_conversations'
const WORKSPACES_KEY = 'conversa_workspaces'
const MODELS_KEY = 'conversa_models'
const GLOBAL_KEY = 'conversa_global' // user edits to the global defaults, persisted client-side

export const SETTING_KEYS = [
  'model',
  'temperature',
  'num_messages_to_send',
  'send_system_prompt',
  'max_tokens',
  'effort',
  'utility_model',
  'use_memory',
  'summarize_n',
  'use_recall',
]

// The one definition of the thinking-effort lever — the composer toolbar and both
// settings panels render this list. Values go to the API as output_config.effort
// (the backend maps them to token budgets for pre-4.6 models). Adding a level here
// (Anthropic also has 'xhigh' and 'max') surfaces it in all three places.
// Replaced the old numeric thinking_budget lever; stored values under the old key are
// simply ignored, since SETTING_KEYS no longer lists it.
export const EFFORT_LEVELS = [
  { label: 'Off', value: '' },
  { label: 'Low', value: 'low' },
  { label: 'Medium', value: 'medium' },
  { label: 'High', value: 'high' },
]

const state = reactive({ conversations: [], workspaces: [] })
export const currentId = ref(null)
export const globalSettings = ref(null)
export const models = ref([]) // [{id, label}], cached from backend
export const sidebarOpen = ref(false) // mobile drawer toggle; desktop ignores it

let loaded = false
let savedGlobal = null // user's edited global defaults, loaded from IDB

// Loads persisted state. Call once before showing the UI.
export async function initStore() {
  state.conversations = (await get(STORE_KEY)) || []
  state.workspaces = (await get(WORKSPACES_KEY)) || []
  models.value = (await get(MODELS_KEY)) || []
  savedGlobal = (await get(GLOBAL_KEY)) || null
  // Backfill stable message ids for conversations saved before ids existed.
  for (const c of state.conversations) {
    for (const m of c.messages) if (!m.id) m.id = crypto.randomUUID()
  }
  loaded = true
  // Persist on any change, debounced so token-by-token streaming doesn't thrash IDB.
  watch(() => state.conversations, save, { deep: true })
  watch(() => state.workspaces, save, { deep: true })
}

let saveTimer
function save() {
  if (!loaded) return
  clearTimeout(saveTimer)
  // Snapshot inside the timer, not out here: save() runs on every mutation (i.e. every
  // streamed token), and the JSON round-trip — which strips the Vue reactive proxy so
  // structured-clone can store it — costs the whole archive each time it runs.
  saveTimer = setTimeout(() => {
    set(STORE_KEY, JSON.parse(JSON.stringify(state.conversations)))
    set(WORKSPACES_KEY, JSON.parse(JSON.stringify(state.workspaces)))
  }, 400)
}

// Write immediately, bypassing the debounce — call when a stream finishes so a quick
// page reload can't lose the final assistant message.
export function persistNow() {
  if (!loaded) return
  clearTimeout(saveTimer)
  set(WORKSPACES_KEY, JSON.parse(JSON.stringify(state.workspaces)))
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
    workspaceId: null, // workspace membership is only this pointer
    settings: {}, // empty = inherit every key from globalSettings
    cards: [],
    cardOverrides: {}, // workspace card id -> 'include' | 'skip', this convo only
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

// --- Workspaces ---------------------------------------------------------------
// A workspace = { id, name, systemPrompt, cards, docs } shared by its conversations
// (convo.workspaceId points here). buildPayload merges it at read time; joining,
// leaving, and deleting touch only that pointer on the conversation.

export const workspaces = computed(() => state.workspaces)

export function createWorkspace(name = 'New workspace') {
  const w = { id: crypto.randomUUID(), name, systemPrompt: '', cards: [], docs: [] }
  state.workspaces.push(w)
  return w
}

export function deleteWorkspace(id) {
  state.workspaces = state.workspaces.filter((w) => w.id !== id)
  for (const c of state.conversations) if (c.workspaceId === id) c.workspaceId = null
}

// null when the convo has no workspace, or its workspace was deleted or not
// imported; callers degrade to plain-convo behavior.
export function workspaceOf(convo) {
  return state.workspaces.find((w) => w.id === convo?.workspaceId) || null
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

// Backup. Full export = { conversations, workspaces }; single-conversation export
// stays a bare array (a workspaceId the importing browser can't resolve degrades
// to a plain convo).
export function exportData(id) {
  if (id) return JSON.parse(JSON.stringify(state.conversations.filter((c) => c.id === id)))
  return JSON.parse(JSON.stringify({ conversations: state.conversations, workspaces: state.workspaces }))
}

// Download an export file: everything, or one conversation when id is given.
export function downloadExport(id) {
  const data = exportData(id)
  const name = (id ? data[0]?.title || 'conversation' : 'export').replace(/[^\w-]+/g, '_').slice(0, 40)
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
  a.download = `conversa-${name}-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

// Import: accepts the object shape or a legacy/single-convo array. Convos: new ids
// come in as-is; a colliding id becomes a copy with fresh ids (same clone path as
// template copies), so nothing local is ever overwritten. Workspaces: colliding ids
// are skipped instead, keeping the local one so convo-to-workspace links stay
// resolvable (a clone would get a fresh id the convos don't point at). Returns the
// convo count.
// Note: re-importing the same file duplicates collided convos; diff-aware skip if it annoys.
export function importData(data) {
  const list = Array.isArray(data) ? data : data?.conversations
  if (!Array.isArray(list)) throw new Error('Not a conversa export')
  const haveWs = new Set(state.workspaces.map((w) => w.id))
  for (const w of (Array.isArray(data) ? [] : data.workspaces) || []) {
    if (w?.id && !haveWs.has(w.id)) {
      state.workspaces.push(w)
      haveWs.add(w.id)
    }
  }
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
