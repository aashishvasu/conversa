import { set } from 'idb-keyval'
import { reactive, watch } from 'vue'
import { dismiss, notify } from '../utils/notify.js'
import { tr } from '../i18n/index.js'

export const STORE_KEY = 'conversa_conversations'
export const WORKSPACES_KEY = 'conversa_workspaces'
export const MODELS_KEY = 'conversa_models'
export const RUNS_KEY = 'conversa_runs'
export const DOCS_KEY = 'conversa_docs'
export const IMAGE_KEY_PREFIX = 'conversa_img:'
export const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])
export const GLOBAL_KEY = 'conversa_global'

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
    action: { label: tr('notification.downloadBackup'), fn: _downloadExportFn },
  })
}

let saveTimer

function save() {
  if (!loaded) return
  clearTimeout(saveTimer)
  saveTimer = setTimeout(flush, 400)
}

// Snapshot inside flush, not in save(), because save() runs on every mutation, meaning every streamed token.
// The JSON round-trip strips the Vue reactive proxy so idb-keyval can store it, and it costs the whole archive each time.
function flush() {
  return Promise.all([
    set(STORE_KEY, JSON.parse(JSON.stringify(state.conversations))),
    set(WORKSPACES_KEY, JSON.parse(JSON.stringify(state.workspaces))),
    set(RUNS_KEY, JSON.parse(JSON.stringify(state.runs))),
    set(DOCS_KEY, JSON.parse(JSON.stringify(state.docs))),
  ]).then(() => dismiss('storage'), storageFailure)
}

export function persistNow() {
  if (!loaded) return
  clearTimeout(saveTimer)
  return flush()
}

export function startWatching() {
  watch(() => state.conversations, save, { deep: true })
  watch(() => state.workspaces, save, { deep: true })
  watch(() => state.runs, save, { deep: true })
  watch(() => state.docs, save, { deep: true })
}
