import { get, set } from 'idb-keyval'
import { computed, reactive, ref, watch } from 'vue'
import { dismiss, notify } from './utils/notify.js'
import { enterToSend, fontScale } from './utils/prefs.js'
import { isDark } from './utils/theme.js'

// All conversation state lives client-side in IndexedDB (via idb-keyval).

const STORE_KEY = 'conversa_conversations'
const WORKSPACES_KEY = 'conversa_workspaces'
const MODELS_KEY = 'conversa_models'
const RUNS_KEY = 'conversa_runs'
const GLOBAL_KEY = 'conversa_global' // user edits to the global defaults, persisted client-side

const state = reactive({ conversations: [], workspaces: [], runs: [] })
export const currentId = ref(null)
// A run is selected instead of a conversation, so this being set is what puts the research pane on screen.
export const currentRunId = ref(null)
export const globalSettings = ref(null)
export const models = ref([]) // [{id, label}], cached from backend
export const sidebarOpen = ref(false) // mobile drawer toggle; desktop ignores it

let loaded = false
let savedGlobal = null // user's edited global defaults, loaded from IDB

// Loads persisted state.
// Call once before showing the UI.
export async function initStore() {
  // IDB is best-effort storage; this asks the browser to exempt the origin from eviction. Denial is fine, export stays the real backup.
  globalThis.navigator?.storage?.persist?.()
  state.conversations = (await get(STORE_KEY)) || []
  state.workspaces = (await get(WORKSPACES_KEY)) || []
  state.runs = (await get(RUNS_KEY)) || []
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
  watch(() => state.runs, save, { deep: true })
}

let saveTimer
function save() {
  if (!loaded) return
  clearTimeout(saveTimer)
  saveTimer = setTimeout(flush, 400)
}

// Snapshot inside flush, not in save(), because save() runs on every mutation, meaning every streamed token.
// The JSON round-trip strips the Vue reactive proxy so structured-clone can store it, and it costs the whole archive each time.
function flush() {
  return Promise.all([
    set(STORE_KEY, JSON.parse(JSON.stringify(state.conversations))),
    set(WORKSPACES_KEY, JSON.parse(JSON.stringify(state.workspaces))),
    set(RUNS_KEY, JSON.parse(JSON.stringify(state.runs))),
  ]).then(
    () => dismiss('storage'),
    (e) => notify({
      key: 'storage',
      sticky: true,
      text: 'Saving to browser storage is failing. Changes exist only in memory until it recovers, so download a backup now.',
      detail: String(e?.stack || e),
      action: { label: 'Download backup', fn: downloadExport },
    }),
  )
}

// Write immediately, bypassing the debounce.
// Call it when a stream finishes, so a quick page reload still finds the final assistant message.
export function persistNow() {
  if (!loaded) return
  clearTimeout(saveTimer)
  return flush()
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
  currentRunId.value = null
}

// --- Runs ---------------------------------------------------------------------
// A research run is a sibling of a conversation, not a property of one.
// It owns its brief, its clarifying exchange, its settings overrides and its result.
// It reaches conversations only through the workspace its payload lands in.

export const runs = computed(() => state.runs)
export const currentRun = computed(() => state.runs.find((r) => r.id === currentRunId.value) || null)

export function createRun() {
  const r = {
    id: crypto.randomUUID(),
    title: 'New research',
    brief: '',
    questions: [],
    answers: '',
    settings: {},
    serverId: null,
    status: 'draft',
    phase: '',
    events: [],
    spend: null,
    payload: null,
    workspaceId: null,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  }
  state.runs.unshift(r)
  selectRun(r.id)
  return r
}

export function deleteRun(id) {
  state.runs = state.runs.filter((r) => r.id !== id)
  if (currentRunId.value === id) currentRunId.value = state.runs[0]?.id || null
}

export function selectRun(id) {
  currentRunId.value = id
}

// --- Workspaces ---------------------------------------------------------------
// A workspace = { id, name, systemPrompt, cards, docs } shared by its conversations, which point at it via convo.workspaceId.
// buildPayload merges it at read time; joining, leaving, and deleting touch only that pointer on the conversation.

export const workspaces = computed(() => state.workspaces)

export function createWorkspace(name = 'New workspace') {
  const w = { id: crypto.randomUUID(), name, systemPrompt: '', cards: [], docs: [] }
  state.workspaces.push(w)
  return w
}

// Land a finished research run in a workspace: the report as a doc, the per-subquestion notes as qN cards.
// Passing an existing workspace appends, so repeated runs on one topic accumulate in the same place.
// Known ceiling: appended runs share the qN trigger namespace, so q1 pulls q1 from every run in the workspace.
// On one topic that reads as more context, not wrong context.
// If it gets noisy, number a run's subquestions from the workspace's existing count so report and cards agree.
export function applyResearch(payload, workspace = null) {
  const w = workspace || createWorkspace(payload.name || 'Research')
  if (!workspace) w.systemPrompt = payload.systemPrompt || ''
  const stamp = new Date().toISOString().slice(0, 10)
  for (const d of payload.docs || []) {
    w.docs.push({ id: crypto.randomUUID(), name: `${stamp} ${d.name}`, text: d.text })
  }
  for (const c of payload.cards || []) {
    w.cards.push({ id: crypto.randomUUID(), triggers: c.triggers, path: c.path, content: c.content })
  }
  return w
}

export function deleteWorkspace(id) {
  state.workspaces = state.workspaces.filter((w) => w.id !== id)
  for (const c of state.conversations) if (c.workspaceId === id) c.workspaceId = null
}

// null when the convo has no workspace, or its workspace was deleted or not imported; callers degrade to plain-convo behavior.
export function workspaceOf(convo) {
  return state.workspaces.find((w) => w.id === convo?.workspaceId) || null
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

const SNAPSHOT_VERSION = 1

function wire(value) {
  return JSON.parse(JSON.stringify(value))
}

function snapshotPrefs() {
  return { theme: isDark.value ? 'dark' : 'light', fontScale: fontScale.value, enterToSend: enterToSend.value }
}

export function exportData(id) {
  const conversations = state.conversations.filter((c) => !id || c.id === id)
  return wire({
    version: SNAPSHOT_VERSION,
    exportedAt: new Date().toISOString(),
    conversations,
    ...(id ? {} : { workspaces: state.workspaces, runs: state.runs, settings: savedGlobal, prefs: snapshotPrefs() }),
  })
}

export function snapshotInfo(data) {
  if (!data || Array.isArray(data) || data.version !== SNAPSHOT_VERSION || !Array.isArray(data.conversations) || !Array.isArray(data.workspaces) || !Object.hasOwn(data, 'settings')) return null
  return {
    exportedAt: data.exportedAt || '',
    conversations: data.conversations.length,
    workspaces: data.workspaces.length,
    runs: Array.isArray(data.runs) ? data.runs.length : 0,
  }
}

// Save text to a file the browser downloads.
// A workspace doc is the only copy of a research report, so it needs a way out of IndexedDB.
export function downloadText(name, text, type = 'text/markdown') {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([text], { type }))
  a.download = name
  a.click()
  URL.revokeObjectURL(a.href)
}

// Download an export file: everything, or one conversation when id is given.
export function downloadExport(id) {
  const data = exportData(id)
  const name = (id ? data.conversations[0]?.title || 'conversation' : 'export').replace(/[^\w-]+/g, '_').slice(0, 40)
  const stamp = new Date().toISOString().slice(0, 10)
  downloadText(`conversa-${name}-${stamp}.json`, JSON.stringify(data, null, 2), 'application/json')
}

function validConversation(c) {
  return c?.id && Array.isArray(c.messages)
}

function addMissing(target, values) {
  const ids = new Set(target.map((item) => item.id))
  let added = 0
  for (const value of Array.isArray(values) ? values : []) {
    if (value?.id && !ids.has(value.id)) {
      target.push(value)
      ids.add(value.id)
      added++
    }
  }
  return added
}

// Merge import accepts legacy arrays and ignores snapshot-only settings and prefs.
export function importData(data) {
  const list = Array.isArray(data) ? data : data?.conversations
  if (!Array.isArray(list)) throw new Error('Not a conversa export')
  let changed = addMissing(state.workspaces, Array.isArray(data) ? [] : data.workspaces)
  changed += addMissing(state.runs, Array.isArray(data) ? [] : data.runs)
  const have = new Set(state.conversations.map((c) => c.id))
  let added = 0
  for (const c of list) {
    if (!validConversation(c)) continue
    state.conversations.unshift(have.has(c.id) ? cloneWithNewIds(c) : c)
    have.add(c.id)
    added++
  }
  if (changed || added) persistNow()
  return added
}

// Restore accepts only full versioned snapshots. Merge import remains the path for a partial export.
export async function restoreData(data) {
  if (!snapshotInfo(data)) throw new Error('Not a conversa snapshot')
  const restored = structuredClone(data)
  state.conversations = restored.conversations.filter(validConversation)
  state.workspaces = restored.workspaces.filter((w) => w?.id)
  state.runs = (Array.isArray(restored.runs) ? restored.runs : []).filter((r) => r?.id)
  savedGlobal = restored.settings && typeof restored.settings === 'object' ? restored.settings : null
  if (globalSettings.value) globalSettings.value = { ...globalSettings.value, ...(savedGlobal || {}) }
  currentId.value = conversations.value[0]?.id || null
  currentRunId.value = null
  if (loaded) await Promise.all([persistNow(), set(GLOBAL_KEY, savedGlobal)])
  return restored.prefs && typeof restored.prefs === 'object' ? restored.prefs : {}
}
