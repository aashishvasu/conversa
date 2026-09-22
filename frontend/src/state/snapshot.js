import { delMany, keys, setMany } from 'idb-keyval'
import { IMAGE_KEY_PREFIX, isLoaded, persistNow, state } from './persistence.js'
import { activePane, cloneWithNewIds, conversations, currentId } from './conversations.js'
import { docsOf, hoistInlineDocs, validImage } from './docs.js'
import { migrateRun, validRun } from './runs.js'
import { replaceUsage, usageDays } from './usage.js'
import { isDark } from '../utils/theme.js'
import { enterToSend, fontScale, locale, showThinkingAndSearch } from '../utils/prefs.js'
import { tr } from '../i18n/index.js'

export const SNAPSHOT_VERSION = 4

function wire(value) {
  return JSON.parse(JSON.stringify(value))
}

function snapshotPrefs() {
  return { theme: isDark.value ? 'dark' : 'light', fontScale: fontScale.value, enterToSend: enterToSend.value, showThinkingAndSearch: showThinkingAndSearch.value, locale: locale.value }
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

// Everything IndexedDB holds that is the user's, not the deployment's: conversations, workspaces, docs, runs, edited settings, and the usage ledger.
// The models cache is excluded on purpose (server-owned, refetched after login); the auth token never enters a snapshot at all.
// A single-conversation export carries just that conversation plus the docs it references.
export function exportData(id, settings = null) {
  const convos = state.conversations.filter((c) => !id || c.id === id)
  return wire({
    version: SNAPSHOT_VERSION,
    exportedAt: new Date().toISOString(),
    conversations: convos,
    ...(id ? { docs: docsOf(convos[0]), images: state.images.filter((image) => convos[0]?.messages.some((m) => m.imageIds?.includes(image.id))) } : {
      workspaces: state.workspaces,
      docs: state.docs,
      images: state.images,
      runs: state.runs,
      settings,
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
    images: Array.isArray(data.images) ? data.images.length : 0,
  }
}

// Merge import accepts legacy arrays and ignores snapshot-only settings and prefs.
export async function importData(data) {
  const list = Array.isArray(data) ? data : data?.conversations
  if (!Array.isArray(list)) throw new Error(tr('errors.notExport'))
  const extras = Array.isArray(data) ? {} : data
  const incomingDocs = Array.isArray(extras.docs) ? [...extras.docs] : []
  hoistInlineDocs(Array.isArray(extras.workspaces) ? extras.workspaces : [], incomingDocs)
  const incomingImages = Array.isArray(extras.images) ? extras.images.filter(validImage) : []
  const newImages = incomingImages.filter((image) => !state.images.some((local) => local.id === image.id))
  if (newImages.length) await setMany(newImages.map((image) => [`${IMAGE_KEY_PREFIX}${image.id}`, image]))
  state.images.push(...newImages)
  let changed = addMissing(state.docs, incomingDocs)
  changed += addMissing(state.workspaces, extras.workspaces)
  changed += addMissing(state.runs, Array.isArray(extras.runs) ? extras.runs.map(migrateRun).filter(validRun) : [])
  const have = new Set(state.conversations.map((c) => c.id))
  let added = 0
  for (const c of list) {
    if (!validConversation(c)) continue
    state.conversations.unshift(have.has(c.id) ? cloneWithNewIds(c) : c)
    have.add(c.id)
    added++
  }
  if (changed || added || newImages.length) persistNow()
  return added
}

// Restore accepts only full versioned snapshots. Merge import remains the path for a partial export.
// applySettings is provided by store.js and handles savedGlobal + globalSettings + GLOBAL_KEY IDB write.
export async function restoreData(data, applySettings) {
  if (!snapshotInfo(data)) throw new Error(tr('errors.notSnapshot'))
  const restored = structuredClone(data)
  state.conversations = restored.conversations.filter(validConversation)
  state.workspaces = restored.workspaces.filter((w) => w?.id)
  state.runs = (Array.isArray(restored.runs) ? restored.runs : []).map(migrateRun).filter(validRun)
  // A pre-v3 snapshot carries its docs inline on workspaces; the hoist turns them into the replacing doc set.
  state.docs = (Array.isArray(restored.docs) ? restored.docs : []).filter((d) => d?.id)
  const restoredImages = (Array.isArray(restored.images) ? restored.images : state.images).filter(validImage)
  if (isLoaded()) {
    await setMany(restoredImages.map((image) => [`${IMAGE_KEY_PREFIX}${image.id}`, image]))
    const staleImageKeys = (await keys()).filter((key) => typeof key === 'string' && key.startsWith(IMAGE_KEY_PREFIX) && !restoredImages.some((image) => `${IMAGE_KEY_PREFIX}${image.id}` === key))
    if (staleImageKeys.length) await delMany(staleImageKeys)
  }
  state.images = restoredImages
  hoistInlineDocs(state.workspaces, state.docs)
  const restoredSettings = restored.settings && typeof restored.settings === 'object' ? restored.settings : null
  const settingsDone = typeof applySettings === 'function' ? applySettings(restoredSettings) : Promise.resolve()
  currentId.value = conversations.value[0]?.id || null
  activePane.value = 'chat'
  // A v1 snapshot (before usage.md) has no usage field at all; leave the current ledger alone rather than wipe it, since replace-all only applies to what the snapshot actually says it is replacing.
  if (Object.hasOwn(restored, 'usage')) replaceUsage(restored.usage)
  if (isLoaded()) await Promise.all([persistNow(), settingsDone])
  else await settingsDone
  return restored.prefs && typeof restored.prefs === 'object' ? restored.prefs : {}
}
