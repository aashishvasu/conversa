import { del, get, getMany, keys, set } from 'idb-keyval'
import { ref } from 'vue'
import {
  DOCS_KEY,
  GLOBAL_KEY,
  IMAGE_KEY_PREFIX,
  MODELS_KEY,
  RUNS_KEY,
  STORE_KEY,
  WORKSPACES_KEY,
  isLoaded,
  setDownloadExport,
  setLoaded,
  startWatching,
  state,
} from './persistence.js'
import { conversations, createConversation, currentId } from './conversations.js'
import { gcImages, hoistInlineDocs, downloadText, validImage } from './docs.js'
import { migrateRun, validRun } from './runs.js'
import { exportData as _exportData, restoreData as _restoreData } from './snapshot.js'

export { persistNow } from './persistence.js'
export {
  activePane, attachedDocs, conversations, createConversation, createFromTemplate,
  currentConversation, currentId, deleteConversation, saveAsTemplate, selectConversation,
  sidebarOpen, templates,
} from './conversations.js'
export { activeRunOf, createRun, finishRun, migrateRun, removeRun, runById } from './runs.js'
export { createWorkspace, deleteWorkspace, workspaceOf, workspaces } from './workspaces.js'
export {
  createDoc, createImage, deleteDoc, docs, docsOf, downloadText,
  images, imagesOf, releaseImages, removeDocRef, undoDocRevision, updateDocText,
} from './docs.js'
export { importData, snapshotInfo } from './snapshot.js'

export const globalSettings = ref(null)
export const models = ref([])

let savedGlobal = null
let serverDefaults = null

export function cacheModels(list) {
  models.value = list
  set(MODELS_KEY, list)
}

// Whether a model id currently reports prompt-cache support.
// Defaults to true when the id is missing from the cached list (a stale pre-capability-flag cache, or not loaded yet): a control should never hide itself over a data gap, only over a model that actively says it can't cache.
export function modelSupportsCache(modelId) {
  return models.value.find((m) => m.id === modelId)?.supports_cache ?? true
}

export function persistGlobal() {
  savedGlobal = { ...globalSettings.value }
  set(GLOBAL_KEY, savedGlobal)
}

export function resetGlobalSettings() {
  savedGlobal = null
  globalSettings.value = { ...serverDefaults }
  if (isLoaded()) del(GLOBAL_KEY)
}

export function setGlobalSettings(defaults) {
  serverDefaults = { ...defaults }
  // Server defaults seed any missing keys; the user's saved edits win.
  globalSettings.value = { ...serverDefaults, ...(savedGlobal || {}) }
  if (currentId.value) return
  // Open the first real conversation, never a template; if there are none, start fresh.
  currentId.value = conversations.value[0]?.id
  if (!currentId.value) createConversation()
}

export function exportData(id) {
  return _exportData(id, savedGlobal)
}

export function downloadExport(id) {
  const data = exportData(id)
  const name = (id ? data.conversations[0]?.title || 'conversation' : 'export').replace(/[^\w-]+/g, '_').slice(0, 40)
  const stamp = new Date().toISOString().slice(0, 10)
  downloadText(`conversa-${name}-${stamp}.json`, JSON.stringify(data, null, 2), 'application/json')
}

export function restoreData(data) {
  return _restoreData(data, async (settings) => {
    savedGlobal = settings
    if (globalSettings.value) globalSettings.value = { ...globalSettings.value, ...(savedGlobal || {}) }
    if (isLoaded()) await set(GLOBAL_KEY, savedGlobal)
  })
}

setDownloadExport(downloadExport)

export async function initStore() {
  // IDB is best-effort storage; this asks the browser to exempt the origin from eviction. Denial is fine, export stays the real backup.
  globalThis.navigator?.storage?.persist?.()
  state.conversations = (await get(STORE_KEY)) || []
  state.workspaces = (await get(WORKSPACES_KEY)) || []
  state.runs = ((await get(RUNS_KEY)) || []).map(migrateRun).filter(validRun)
  state.docs = (await get(DOCS_KEY)) || []
  const imageKeys = (await keys()).filter((key) => typeof key === 'string' && key.startsWith(IMAGE_KEY_PREFIX))
  state.images = (await getMany(imageKeys)).filter(validImage)
  models.value = (await get(MODELS_KEY)) || []
  savedGlobal = (await get(GLOBAL_KEY)) || null
  // Backfill missing message ids in stored conversations.
  for (const c of state.conversations) {
    for (const m of c.messages) if (!m.id) m.id = crypto.randomUUID()
  }
  hoistInlineDocs(state.workspaces, state.docs)
  gcImages()
  setLoaded(true)
  startWatching()
}
