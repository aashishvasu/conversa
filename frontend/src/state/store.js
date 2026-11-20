import { ref } from 'vue'
import {
  ensureLoaded,
  installTeardownFlush,
  isLoaded,
  markMetaWrite,
  scheduleFlush,
  setDownloadExport,
  setLoaded,
  seedRunEventCounts,
  startWatching,
  state,
} from './persistence.js'
import { db } from './db.js'
import { conversations, createConversation, currentId } from './conversations.js'
import { gcImages, downloadText } from './docs.js'
import { migrateFromKeyval } from './migrate-keyval.js'
import { initUsage } from './usage.js'
import { tr } from '../i18n/index.js'
import { notify } from '../utils/notify.js'
import { exportData as _exportData, exportLastSaved as _exportLastSaved, restoreData as _restoreData, restoreSnapshot as _restoreSnapshot } from './snapshot.js'
export { persistNow, ensureLoaded } from './persistence.js'
export {
  activePane, attachedDocs, conversations, createConversation, createFromTemplate,
  currentConversation, currentId, deleteConversation, saveAsTemplate, selectConversation,
  sidebarOpen, templates,
} from './conversations.js'
export { activeRunOf, createRun, finishRun, removeRun, runById } from './runs.js'
export { createWorkspace, deleteWorkspace, workspaceOf, workspaces } from './workspaces.js'
export {
  createDoc, createImage, deleteDoc, docs, docsOf, downloadText,
  images, imagesOf, releaseImages, removeDocRef, undoDocRevision, updateDocText,
} from './docs.js'
export { createTransferExport, importData, snapshotInfo } from './snapshot.js'
export const globalSettings = ref(null)
export const models = ref([])
let savedGlobal = null
let serverDefaults = null
export function cacheModels(list) {
  models.value = list
  markMetaWrite('models', list)
  scheduleFlush()
}
// Whether a model id currently reports prompt-cache support.
// Defaults to true when the id is missing from the cached list (a stale pre-capability-flag cache, or not loaded yet): a control should never hide itself over a data gap, only over a model that actively says it can't cache.
export function modelSupportsCache(modelId) {
  return models.value.find((m) => m.id === modelId)?.supports_cache ?? true
}
export function persistGlobal() {
  savedGlobal = { ...globalSettings.value }
  markMetaWrite('global', savedGlobal)
  scheduleFlush()
}
export function resetGlobalSettings() {
  savedGlobal = null
  globalSettings.value = { ...serverDefaults }
  if (isLoaded()) {
    markMetaWrite('global', null)
    scheduleFlush()
  }
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
function saveExportFile(data, id) {
  const name = (id ? data.conversations[0]?.title || 'conversation' : 'export').replace(/[^\w-]+/g, '_').slice(0, 40)
  const stamp = new Date().toISOString().slice(0, 10)
  downloadText(`conversa-${name}-${stamp}.json`, JSON.stringify(data, null, 2), 'application/json')
}
export async function downloadExport(id) {
  try {
    saveExportFile(await exportData(id), id)
  } catch (error) {
    notify({ key: 'export-failed', text: tr('notification.error'), detail: error?.message || String(error) })
  }
}
// The storage banner's escape hatch: committed rows only, so it still works when the flush is what is failing.
export async function downloadLastSavedCopy(id) {
  try {
    saveExportFile(await _exportLastSaved(id, savedGlobal), id)
  } catch (error) {
    notify({ key: 'export-failed', text: tr('notification.error'), detail: error?.message || String(error) })
  }
}
// restoreData writes the meta.global row inside its own transaction, so this callback only updates the in-memory saved settings.
function applyRestoredSettings(settings) {
  savedGlobal = settings
  if (globalSettings.value) globalSettings.value = { ...globalSettings.value, ...(savedGlobal || {}) }
}
export function restoreData(data) {
  return _restoreData(data, applyRestoredSettings)
}
export function restoreSnapshot(data) {
  return _restoreSnapshot(data, applyRestoredSettings)
}
setDownloadExport(downloadLastSavedCopy)
// Everything the sidebar renders loads in one read: conversations newest-created first (a createdAt index, not a stored order), then the collections.
export async function initStore() {
  // IDB is best-effort storage; this asks the browser to exempt the origin from eviction. Denial is fine, export stays the real backup.
  globalThis.navigator?.storage?.persist?.()
  await migrateFromKeyval()
  state.conversations = await db.conversations.orderBy('createdAt').reverse().toArray()
  state.workspaces = await db.workspaces.toArray()
  const runRows = await db.runs.toArray()
  const runEventsById = new Map()
  const eventRows = await db.runEvents.toArray()
  for (const row of eventRows) {
    const { key, runId, ...event } = row
    if (runEventsById.has(runId)) runEventsById.get(runId).push(event)
    else runEventsById.set(runId, [event])
  }
  state.runs = runRows.map((run) => ({ ...run, events: runEventsById.get(run.id) || [] }))
  seedRunEventCounts()
  state.docs = await db.docs.toArray()
  // Images enter memory per-conversation through ensureLoaded, never by reading the whole table.
  state.images = []
  models.value = (await db.meta.get('models'))?.value || []
  savedGlobal = (await db.meta.get('global'))?.value ?? null
  await initUsage()
  setLoaded(true)
  installTeardownFlush()
  // An image attached but never sent is written at attach time and swept here every boot.
  await gcImages()
  // The first real conversation renders from messages, and every template stays loaded so a launch can clone it synchronously.
  let firstActiveLoaded = false
  for (const c of state.conversations) {
    const isFirstActive = !c.isTemplate && !firstActiveLoaded
    firstActiveLoaded = firstActiveLoaded || isFirstActive
    if (c.isTemplate || isFirstActive) await ensureLoaded(c)
  }
  startWatching()
}
