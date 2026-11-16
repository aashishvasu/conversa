import { delMany, get, set, setMany } from 'idb-keyval'
import { reactive, toRaw, watch } from 'vue'
import { dismiss, notify } from '../utils/notify.js'
import { tr } from '../i18n/index.js'

export const STORE_KEY = 'conversa_conversations'
export const CONVO_KEY_PREFIX = 'conversa_convo:'
export const ORDER_KEY = 'conversa_order'
export const WORKSPACES_KEY = 'conversa_workspaces'
export const MODELS_KEY = 'conversa_models'
export const RUNS_KEY = 'conversa_runs'
export const DOCS_KEY = 'conversa_docs'
export const IMAGE_KEY_PREFIX = 'conversa_img:'
export const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])
export const GLOBAL_KEY = 'conversa_global'

const COLLECTION_KEYS = { workspaces: WORKSPACES_KEY, runs: RUNS_KEY, docs: DOCS_KEY }

export const state = reactive({ conversations: [], workspaces: [], runs: [], docs: [], images: [] })

let loaded = false
export function setLoaded(v) { loaded = v }
export function isLoaded() { return loaded }

let _downloadExportFn = null
export function setDownloadExport(fn) { _downloadExportFn = fn }

export function storageFailure(e) {
  notify({
    key: 'storage',
    sticky: true,
    text: tr('notification.storage'),
    detail: String(e?.stack || e),
    action: { label: tr('notification.downloadBackup'), fn: () => _downloadExportFn?.() },
  })
}

let saveTimer
let chain = Promise.resolve()

function save() {
  if (!loaded) return
  clearTimeout(saveTimer)
  saveTimer = setTimeout(enqueueFlush, 400)
}

function enqueueFlush() {
  chain = chain.then(runFlush)
  return chain
}

export function persistNow() {
  if (!loaded) return
  clearTimeout(saveTimer)
  return enqueueFlush()
}

// Best effort by nature: IndexedDB is async and the browser may not commit before teardown, but skipping the flush loses every edit made inside the debounce window.
// pagehide covers bfcache-eligible navigations and mobile; `hidden` is the reliable backgrounding signal there.
// A live stream is safe to flush: between checkpoints it lives only in unwatched view state.
let teardownInstalled = false
export function installTeardownFlush() {
  if (teardownInstalled) return
  teardownInstalled = true
  globalThis.addEventListener?.('pagehide', () => { persistNow() })
  globalThis.document?.addEventListener('visibilitychange', () => {
    if (globalThis.document.visibilityState === 'hidden') persistNow()
  })
}

// Reads the record directly by key, bypassing every path that would schedule a write.
export function readStoredConversation(id) {
  return get(convoKey(id))
}

const convoWatchers = new Map()
let dirtyConvos = new Set()
let removedConvos = new Set()
let dirtyCollections = new Set()
let lastOrder = []
let watching = false

function convoKey(id) {
  return `${CONVO_KEY_PREFIX}${id}`
}

function syncConvoWatchers(markReplaced) {
  const present = new Set()
  for (const item of state.conversations) {
    present.add(item.id)
    const known = convoWatchers.get(item.id)
    if (known?.item === item) continue
    known?.stop()
    convoWatchers.set(item.id, {
      item,
      stop: watch(() => item, () => { dirtyConvos.add(item.id); save() }, { deep: true }),
    })
    // A runtime replacement (create, import, restore) is unsaved until written; the boot-time attach passes markReplaced=false so loading and fixups never rewrite the whole archive.
    if (markReplaced) dirtyConvos.add(item.id)
  }
  for (const [id, known] of convoWatchers) {
    if (present.has(id)) continue
    known.stop()
    convoWatchers.delete(id)
    dirtyConvos.delete(id)
    removedConvos.add(id)
  }
}

export function startWatching() {
  if (!watching) {
    watching = true
    watch(() => state.conversations.map((c) => c.id), () => { syncConvoWatchers(true); save() })
    for (const name of Object.keys(COLLECTION_KEYS)) {
      watch(() => state[name], () => { dirtyCollections.add(name); save() }, { deep: true })
    }
  }
  syncConvoWatchers(false)
  dirtyConvos.clear()
  removedConvos.clear()
  dirtyCollections.clear()
  lastOrder = state.conversations.map((c) => c.id)
}

function sameIds(a, b) {
  return a.length === b.length && a.every((id, i) => id === b[i])
}

async function runFlush() {
  const ids = state.conversations.map((c) => c.id)
  const present = new Set(ids)
  const convos = [...dirtyConvos].filter((id) => present.has(id))
  const removed = [...removedConvos].filter((id) => !present.has(id))
  const collections = [...dirtyCollections]
  const orderChanged = !sameIds(ids, lastOrder)
  dirtyConvos.clear()
  removedConvos.clear()
  dirtyCollections.clear()
  if (!convos.length && !removed.length && !collections.length && !orderChanged) return true
  try {
    // toRaw yields the plain target whose nested objects were never proxy-wrapped, so one structuredClone snapshots the item without dropping values JSON cannot represent.
    if (convos.length) await setMany(convos.map((id) => [convoKey(id), structuredClone(toRaw(state.conversations.find((c) => c.id === id)))]))
    if (removed.length) await delMany(removed.map(convoKey))
    for (const name of collections) await set(COLLECTION_KEYS[name], structuredClone(toRaw(state[name])))
    if (orderChanged) {
      await set(ORDER_KEY, ids)
      lastOrder = ids
    }
    dismiss('storage')
    return true
  } catch (error) {
    for (const id of convos) dirtyConvos.add(id)
    for (const id of removed) removedConvos.add(id)
    for (const name of collections) dirtyCollections.add(name)
    storageFailure(error)
    return false
  }
}
