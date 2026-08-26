import { get, set } from 'idb-keyval'
import { computed, reactive, ref, watch } from 'vue'
import { replaceUsage, usageDays } from './usage.js'
import { dismiss, notify } from './utils/notify.js'
import { enterToSend, fontScale } from './utils/prefs.js'
import { isDark } from './utils/theme.js'

// All conversation state lives client-side in IndexedDB (via idb-keyval).

const STORE_KEY = 'conversa_conversations'
const WORKSPACES_KEY = 'conversa_workspaces'
const MODELS_KEY = 'conversa_models'
const RUNS_KEY = 'conversa_runs'
const DOCS_KEY = 'conversa_docs'
const GLOBAL_KEY = 'conversa_global' // user edits to the global defaults, persisted client-side

const state = reactive({ conversations: [], workspaces: [], runs: [], docs: [] })
export const currentId = ref(null)
// A selected run displays the research pane.
export const currentRunId = ref(null)
// Which main pane is showing: 'chat' | 'research'.
// Independent of currentRunId/currentId so a pane can be a Reka Tabs value (the tab strip in Sidebar shares this ref through the TabsRoot App.vue wraps around Sidebar and the panes).
export const activePane = ref('chat')
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
  state.docs = (await get(DOCS_KEY)) || []
  models.value = (await get(MODELS_KEY)) || []
  savedGlobal = (await get(GLOBAL_KEY)) || null
  // Backfill missing message ids in stored conversations.
  for (const c of state.conversations) {
    for (const m of c.messages) if (!m.id) m.id = crypto.randomUUID()
  }
  hoistInlineDocs(state.workspaces, state.docs)
  loaded = true
  // Persist on any change, debounced so token-by-token streaming doesn't thrash IDB.
  watch(() => state.conversations, save, { deep: true })
  watch(() => state.workspaces, save, { deep: true })
  watch(() => state.runs, save, { deep: true })
  watch(() => state.docs, save, { deep: true })
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
    set(DOCS_KEY, JSON.parse(JSON.stringify(state.docs))),
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

// Whether a model id currently reports prompt-cache support.
// Defaults to true when the id is missing from the cached list (a stale pre-capability-flag cache, or not loaded yet): a control should never hide itself over a data gap, only over a model that actively says it can't cache.
export function modelSupportsCache(modelId) {
  return models.value.find((m) => m.id === modelId)?.supports_cache ?? true
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
    docIds: [], // standing document attachments, resolved through docsOf at send time
    settings: {}, // empty = inherit every key from globalSettings
    cards: [],
    cardOverrides: {}, // workspace card id -> 'include' | 'skip', this convo only
    memory: '', // rolling summary of compressed-away history
    memoryCount: 0, // how many leading non-system messages are folded into memory
    usage: null, // running {calls, input, output, cacheRead, cacheWrite, usd} total for this conversation
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
  const gone = state.conversations.find((c) => c.id === id)
  state.conversations = state.conversations.filter((c) => c.id !== id)
  if (currentId.value === id) currentId.value = state.conversations[0]?.id || null
  gcDocs(gone?.docIds)
}

export function selectConversation(id) {
  currentId.value = id
  currentRunId.value = null
  activePane.value = 'chat'
}

// --- Runs ---------------------------------------------------------------------
// Research runs and conversations are sibling sidebar records.
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
    spendLedgered: false, // set once its finished spend is folded into the usage ledger, so a reopen doesn't refold
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
  if (currentRunId.value === id) {
    currentRunId.value = state.runs[0]?.id || null
    // Only the zero-runs-left case needs to move the tab: another run staying selected means the research tab still has something to show.
    if (!currentRunId.value) activePane.value = 'chat'
  }
}

export function selectRun(id) {
  currentRunId.value = id
  activePane.value = 'research'
}

// --- Workspaces ---------------------------------------------------------------
// A workspace = { id, name, systemPrompt, cards, docIds } shared by its conversations, which point at it via convo.workspaceId.
// buildPayload merges it at read time; joining, leaving, and deleting touch only that pointer on the conversation.

export const workspaces = computed(() => state.workspaces)

export function createWorkspace(name = 'New workspace') {
  const w = { id: crypto.randomUUID(), name, systemPrompt: '', cards: [], docIds: [] }
  state.workspaces.push(w)
  return w
}

// Land a finished research run in a workspace: the report into the doc store, the per-subquestion notes as qN cards.
// Passing an existing workspace appends, so repeated runs on one topic accumulate in the same place.
// Known ceiling: appended runs share the qN trigger namespace, so q1 pulls q1 from every run in the workspace.
// On one topic that reads as more context, not wrong context.
// If it gets noisy, number a run's subquestions from the workspace's existing count so report and cards agree.
export function applyResearch(payload, workspace = null, runId = null) {
  const w = workspace || createWorkspace(payload.name || 'Research')
  if (!workspace) w.systemPrompt = payload.systemPrompt || ''
  const stamp = new Date().toISOString().slice(0, 10)
  for (const d of payload.docs || []) {
    w.docIds.push(createDoc({ name: `${stamp} ${d.name}`, text: d.text, source: { kind: 'research', runId } }).id)
  }
  for (const c of payload.cards || []) {
    w.cards.push({ id: crypto.randomUUID(), triggers: c.triggers, path: c.path, content: c.content })
  }
  return w
}

export function deleteWorkspace(id) {
  const gone = state.workspaces.find((w) => w.id === id)
  state.workspaces = state.workspaces.filter((w) => w.id !== id)
  for (const c of state.conversations) if (c.workspaceId === id) c.workspaceId = null
  gcDocs(gone?.docIds)
}

// null when the convo has no workspace, or its workspace was deleted or not imported; callers degrade to plain-convo behavior.
export function workspaceOf(convo) {
  return state.workspaces.find((w) => w.id === convo?.workspaceId) || null
}

// --- Documents -----------------------------------------------------------------
// A doc = { id, name, text, createdAt, updatedAt, source, versions } living once in the store.
// Workspaces and conversations reference it through docIds, so one doc can serve several owners without copies.
// source records where it came from: { kind: 'upload' | 'research' | 'chat' | 'revise', runId?, convoId?, messageId? }.

export const docs = computed(() => state.docs)

export function createDoc({ name, text, source }) {
  const d = { id: crypto.randomUUID(), name, text, createdAt: Date.now(), updatedAt: Date.now(), source, versions: [] }
  state.docs.push(d)
  return d
}

// Resolves owner.docIds at read time; a dangling ref (deleted or unimported doc) drops out, like workspaceOf.
export function docsOf(owner) {
  return (owner?.docIds || []).map((id) => state.docs.find((d) => d.id === id)).filter(Boolean)
}

// The docs a conversation sends: workspace docs first, then its own attachments, deduped by id.
// The order is load-bearing: docs sit in the cached stable half of the system prompt, so it must not shift between turns.
export function attachedDocs(convo) {
  const seen = new Set()
  return [...docsOf(workspaceOf(convo)), ...docsOf(convo)].filter((d) => !seen.has(d.id) && seen.add(d.id))
}

// Drop the given docs unless some workspace or conversation still references them.
// Every ref-releasing path (removeDocRef, deleteWorkspace, deleteConversation) funnels through this, so "last ref gone deletes the doc" holds app-wide.
function gcDocs(ids) {
  if (!ids?.length) return
  const referenced = new Set()
  for (const o of [...state.workspaces, ...state.conversations]) for (const id of o.docIds || []) referenced.add(id)
  state.docs = state.docs.filter((d) => !ids.includes(d.id) || referenced.has(d.id))
}

// Drop one owner's reference; the doc itself is deleted once nothing references it.
export function removeDocRef(owner, id) {
  owner.docIds = (owner.docIds || []).filter((x) => x !== id)
  gcDocs([id])
}

// Delete a doc outright, stripping its id from every owner.
export function deleteDoc(id) {
  state.docs = state.docs.filter((d) => d.id !== id)
  for (const o of [...state.workspaces, ...state.conversations]) {
    if (o.docIds?.includes(id)) o.docIds = o.docIds.filter((x) => x !== id)
  }
}

// flush() snapshots the whole archive on every debounced write, so versions are capped: ten reports of ~64KB each per doc stays affordable.
const DOC_VERSION_CAP = 10

export function updateDocText(doc, text) {
  ;(doc.versions ??= []).push({ text: doc.text, savedAt: Date.now() })
  if (doc.versions.length > DOC_VERSION_CAP) doc.versions.shift()
  doc.text = text
  doc.updatedAt = Date.now()
}

export function undoDocRevision(doc) {
  const v = doc.versions?.pop()
  if (!v) return
  doc.text = v.text
  doc.updatedAt = Date.now()
}

// Pre-doc-store workspaces held docs inline; hoist them into the doc store and leave refs behind.
// Runs on every entry path (initStore, restoreData, importData) so a legacy archive upgrades wherever it appears.
// Keeps the original doc ids: refs elsewhere in the same archive stay valid, and re-importing the same legacy export stays keep-local.
function hoistInlineDocs(workspaces, docs) {
  const have = new Set(docs.map((d) => d.id))
  for (const w of workspaces) {
    w.docIds ??= []
    for (const d of w.docs || []) {
      if (!d?.id) continue
      if (!have.has(d.id)) {
        docs.push({ id: d.id, name: d.name, text: d.text, createdAt: Date.now(), updatedAt: Date.now(), source: { kind: 'upload' }, versions: [] })
        have.add(d.id)
      }
      w.docIds.push(d.id)
    }
    delete w.docs
  }
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

const SNAPSHOT_VERSION = 3

function wire(value) {
  return JSON.parse(JSON.stringify(value))
}

function snapshotPrefs() {
  return { theme: isDark.value ? 'dark' : 'light', fontScale: fontScale.value, enterToSend: enterToSend.value }
}

// Everything IndexedDB holds that is the user's, not the deployment's: conversations, workspaces, docs, runs, edited settings, and the usage ledger.
// The models cache is excluded on purpose (server-owned, refetched after login); the auth token never enters a snapshot at all.
// A single-conversation export carries just that conversation plus the docs it references.
export function exportData(id) {
  const conversations = state.conversations.filter((c) => !id || c.id === id)
  return wire({
    version: SNAPSHOT_VERSION,
    exportedAt: new Date().toISOString(),
    conversations,
    ...(id ? { docs: docsOf(conversations[0]) } : {
      workspaces: state.workspaces,
      docs: state.docs,
      runs: state.runs,
      settings: savedGlobal,
      usage: usageDays(),
      prefs: snapshotPrefs(),
    }),
  })
}

// Accepts this version or any older one this build still knows how to restore (see restoreData).
export function snapshotInfo(data) {
  if (!data || Array.isArray(data) || typeof data.version !== 'number' || data.version > SNAPSHOT_VERSION) return null
  if (!Array.isArray(data.conversations) || !Array.isArray(data.workspaces) || !Object.hasOwn(data, 'settings')) return null
  return {
    exportedAt: data.exportedAt || '',
    conversations: data.conversations.length,
    workspaces: data.workspaces.length,
    runs: Array.isArray(data.runs) ? data.runs.length : 0,
    // Pre-v3 snapshots hold docs inline on workspaces, so count both places.
    docs: (Array.isArray(data.docs) ? data.docs.length : 0) + data.workspaces.reduce((n, w) => n + (w.docs?.length || 0), 0),
  }
}

// Save text to a file the browser downloads.
// Export a workspace document from IndexedDB.
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
  const extras = Array.isArray(data) ? {} : data
  const incomingDocs = Array.isArray(extras.docs) ? [...extras.docs] : []
  hoistInlineDocs(Array.isArray(extras.workspaces) ? extras.workspaces : [], incomingDocs)
  let changed = addMissing(state.docs, incomingDocs)
  changed += addMissing(state.workspaces, extras.workspaces)
  changed += addMissing(state.runs, extras.runs)
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
  // A pre-v3 snapshot carries its docs inline on workspaces; the hoist turns them into the replacing doc set.
  state.docs = (Array.isArray(restored.docs) ? restored.docs : []).filter((d) => d?.id)
  hoistInlineDocs(state.workspaces, state.docs)
  savedGlobal = restored.settings && typeof restored.settings === 'object' ? restored.settings : null
  if (globalSettings.value) globalSettings.value = { ...globalSettings.value, ...(savedGlobal || {}) }
  currentId.value = conversations.value[0]?.id || null
  currentRunId.value = null
  activePane.value = 'chat'
  // A v1 snapshot (before usage.md) has no usage field at all; leave the current ledger alone rather than wipe it, since replace-all only applies to what the snapshot actually says it is replacing.
  if (Object.hasOwn(restored, 'usage')) replaceUsage(restored.usage)
  if (loaded) await Promise.all([persistNow(), set(GLOBAL_KEY, savedGlobal)])
  return restored.prefs && typeof restored.prefs === 'object' ? restored.prefs : {}
}
