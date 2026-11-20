import { persistNow, resetRemovedImages, seedRunEventCounts, startWatching, state } from './persistence.js'
import { db } from './db.js'
import { createTransfer } from '../api/client.js'
import { activePane, cloneWithNewIds, conversations, currentId } from './conversations.js'
import { validImage } from './docs.js'
import { replaceUsage, usageDaysFromTable, usageRowsFromDays } from './usage.js'
import { isDark, restoreTheme } from '../utils/theme.js'
import { enterToSend, fontScale, locale, restorePrefs, showThinkingAndSearch } from '../utils/prefs.js'
import { tr } from '../i18n/index.js'

export const SNAPSHOT_VERSION = 5

// Every table a restore replaces; meta is included only to write the settings row, never to clear the schema or models cache.
const RESTORE_TABLES = ['conversations', 'messages', 'workspaces', 'docs', 'images', 'runs', 'runEvents', 'usage', 'meta']

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

// messageIds drives the message array, recovered strays join by createdAt, mirroring ensureLoaded so an export agrees with a loaded conversation.
function orderedMessages(rows, messageIds) {
  const byId = new Map(rows.map((m) => [m.id, m]))
  const listed = new Set(messageIds || [])
  const ordered = [...(messageIds || [])].map((id) => byId.get(id)).filter(Boolean)
  const strays = rows.filter((m) => !listed.has(m.id)).sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0))
  return [...ordered, ...strays]
}

// A full export reads the tables, not memory: a summary conversation (no messages in memory) still contributes its rows.
async function orderedConversationRows() {
  return db.conversations.orderBy('createdAt').reverse().toArray()
}

// runEvents are append-only rows whose auto-key is the arrival order; a server's seq can repeat across a restart, so it stays data and never drives the read order.
function runsWithEvents(runRows, eventRows) {
  const byRun = new Map()
  for (const row of eventRows) {
    const { key, runId, ...event } = row
    if (byRun.has(runId)) byRun.get(runId).push(event)
    else byRun.set(runId, [event])
  }
  return runRows.map((r) => ({ ...r, events: byRun.get(r.id) || [] }))
}

// Everything IndexedDB holds that is the user's, not the deployment's: conversations, workspaces, docs, runs, edited settings, and the usage ledger.
// The models cache is excluded on purpose (server-owned, refetched after login); the auth token never enters a snapshot at all.
// A single-conversation export carries just that conversation plus the docs and images its messages reference.
async function buildExport(id, settings) {
  const data = { version: SNAPSHOT_VERSION, exportedAt: new Date().toISOString() }
  if (id) {
    const row = await db.conversations.get(id)
    if (!row) return wire(data)
    const messageRows = await db.messages.where('convoId').equals(id).toArray()
    const messages = orderedMessages(messageRows, row.messageIds)
    const imageIds = [...new Set(messages.flatMap((m) => m.imageIds || []))]
    data.conversations = [{ ...row, messages }]
    data.docs = (row.docIds?.length ? await db.docs.bulkGet(row.docIds) : []).filter(Boolean)
    data.images = (imageIds.length ? await db.images.bulkGet(imageIds) : []).filter(Boolean)
  } else {
    const rows = await orderedConversationRows()
    const messagesByConvo = new Map()
    for (const row of rows) messagesByConvo.set(row.id, await db.messages.where('convoId').equals(row.id).toArray())
    data.conversations = rows.map((row) => ({ ...row, messages: orderedMessages(messagesByConvo.get(row.id) || [], row.messageIds) }))
    data.workspaces = await db.workspaces.toArray()
    data.docs = await db.docs.toArray()
    data.images = await db.images.toArray()
    data.runs = runsWithEvents(await db.runs.toArray(), await db.runEvents.toArray())
    data.settings = settings
    data.usage = await usageDaysFromTable()
    data.prefs = snapshotPrefs()
  }
  // A pending turn belongs to this browser; the copy is detached from it, so the store is untouched.
  for (const c of data.conversations) for (const m of c.messages) { delete m.turnId; delete m.generation }
  return wire(data)
}

// A normal export promises the current state, so a failed flush refuses it rather than silently omitting unsaved edits.
export async function exportData(id, settings = null) {
  const saved = await persistNow()
  // undefined means nothing was loaded and there is nothing to flush; only an explicit false is a failed flush.
  if (saved === false) throw new Error(tr('errors.exportUnsaved'))
  return buildExport(id, settings)
}

// The recovery escape hatch: committed rows only, explicitly excluding unsaved edits, and never requiring a successful flush.
export async function exportLastSaved(id, settings = null) {
  return buildExport(id, settings)
}

// The reader is version-exact: one user, always on the latest build, so any other version is mis-imported rather than quietly degraded.
export function snapshotInfo(data) {
  if (!data || Array.isArray(data) || data.version !== SNAPSHOT_VERSION) return null
  if (!Array.isArray(data.conversations) || !Array.isArray(data.workspaces) || !Object.hasOwn(data, 'settings')) return null
  return {
    exportedAt: data.exportedAt || '',
    conversations: data.conversations.length,
    workspaces: data.workspaces.length,
    runs: Array.isArray(data.runs) ? data.runs.length : 0,
    docs: Array.isArray(data.docs) ? data.docs.length : 0,
    images: Array.isArray(data.images) ? data.images.length : 0,
  }
}

// Merge import accepts legacy arrays and ignores snapshot-only settings and prefs.
export async function importData(data) {
  const list = Array.isArray(data) ? data : data?.conversations
  if (!Array.isArray(list)) throw new Error(tr('errors.notExport'))
  const extras = Array.isArray(data) ? {} : data
  const incomingDocs = Array.isArray(extras.docs) ? [...extras.docs] : []
  const incomingImages = Array.isArray(extras.images) ? extras.images.filter(validImage) : []
  // The table is the full image set; memory holds only loaded conversations, so dedupe against the table.
  const existingImageIds = new Set(incomingImages.length ? (await db.images.bulkGet(incomingImages.map((i) => i.id))).filter(Boolean).map((i) => i.id) : [])
  const newImages = incomingImages.filter((image) => !existingImageIds.has(image.id))
  if (newImages.length) await db.images.bulkPut(newImages)
  state.images.push(...newImages)
  let changed = addMissing(state.docs, incomingDocs)
  changed += addMissing(state.workspaces, Array.isArray(extras.workspaces) ? extras.workspaces : [])
  changed += addMissing(state.runs, Array.isArray(extras.runs) ? extras.runs : [])
  const have = new Set(state.conversations.map((c) => c.id))
  let added = 0
  for (const c of list) {
    if (!validConversation(c)) continue
    // Imports may lack a created time, and the createdAt index omits rows missing it; backfill so an imported conversation still loads.
    c.createdAt ??= Date.now()
    for (const m of c.messages || []) { delete m.generation }
    state.conversations.unshift(have.has(c.id) ? cloneWithNewIds(c) : c)
    have.add(c.id)
    added++
  }
  if (changed || added || newImages.length) persistNow()
  return added
}

// Restore replaces the archive atomically: every user-owned table clears and repopulates in one transaction, so a mid-restore failure rolls back to the untouched database.
// applySettings is provided by store.js and updates the in-memory saved global settings; the meta.global row is written here in the same transaction.
export async function restoreData(data, applySettings) {
  if (!snapshotInfo(data)) throw new Error(tr('errors.notSnapshot'))
  const restored = structuredClone(data)
  const restoredConvos = restored.conversations.filter(validConversation)
  // Restored rows must carry a created time or the createdAt index read omits them on the next reload.
  for (const c of restoredConvos) c.createdAt ??= Date.now()
  // A workspace has no conversation-only fields: workspaceId would surface the override control, and cardOverrides is never legal on an owner that knows no mode.
  const restoredWorkspaces = restored.workspaces.map((w) => {
    const { workspaceId, cardOverrides, ...rest } = w
    return rest
  }).filter((w) => w?.id)
  const restoredRuns = (Array.isArray(restored.runs) ? restored.runs : []).filter((r) => r?.id)
  const restoredDocs = (Array.isArray(restored.docs) ? restored.docs : []).filter((d) => d?.id)
  const restoredImages = (Array.isArray(restored.images) ? restored.images : []).filter(validImage)
  const restoredSettings = restored.settings && typeof restored.settings === 'object' ? restored.settings : null
  const restoredUsage = restored.usage && typeof restored.usage === 'object' && !Array.isArray(restored.usage) ? restored.usage : {}

await db.transaction('rw', RESTORE_TABLES, async () => {
    await db.conversations.clear()
    await db.messages.clear()
    await db.workspaces.clear()
    await db.docs.clear()
    await db.images.clear()
    await db.runs.clear()
    await db.runEvents.clear()
    await db.usage.clear()
    if (restoredConvos.length) await db.conversations.bulkPut(restoredConvos.map(({ messages, ...row }) => row))
    const messageRows = restoredConvos.flatMap((c) => (c.messages || []).map(({ generation, ...m }) => ({ convoId: c.id, ...m })))
    if (messageRows.length) await db.messages.bulkPut(messageRows)
    if (restoredWorkspaces.length) await db.workspaces.bulkPut(restoredWorkspaces)
    if (restoredDocs.length) await db.docs.bulkPut(restoredDocs)
    if (restoredImages.length) await db.images.bulkPut(restoredImages)
    const runRows = restoredRuns.map(({ events, ...row }) => row)
    if (runRows.length) await db.runs.bulkPut(runRows)
    const eventRows = restoredRuns.flatMap((r) => (r.events || []).map((e) => ({ runId: r.id, ...e })))
    if (eventRows.length) await db.runEvents.bulkAdd(eventRows)
    const usageRows = usageRowsFromDays(restoredUsage)
    if (usageRows.length) await db.usage.bulkPut(usageRows)
    await db.meta.put({ key: 'global', value: restoredSettings })
  })

  // Success only reaches here; memory and the dirty bookkeeping are re-derived from what was written so the next flush cannot clobber the restore.
  state.conversations = restoredConvos
  state.workspaces = restoredWorkspaces
  state.docs = restoredDocs
  state.images = restoredImages
  state.runs = restoredRuns
  resetRemovedImages()
  currentId.value = conversations.value[0]?.id || null
  activePane.value = 'chat'
  replaceUsage(restoredUsage)
  if (typeof applySettings === 'function') applySettings(restoredSettings)
  startWatching()
  seedRunEventCounts()
  return restored.prefs && typeof restored.prefs === 'object' ? restored.prefs : {}
}

// The restore flow as one call the components invoke: validate, restore atomically, then apply the snapshot's prefs and theme.
export async function restoreSnapshot(data, applySettings) {
  if (!snapshotInfo(data)) throw new Error(tr('errors.notSnapshot'))
  const prefs = await restoreData(data, applySettings)
  restorePrefs(prefs)
  restoreTheme(prefs.theme)
  return snapshotInfo(data)
}

// The device-transfer create flow: export (flushing first) and hand the payload to the transfer endpoint.
export async function createTransferExport(scope, convoId = null) {
  const settings = convoId ? null : (await db.meta.get('global'))?.value ?? null
  const data = await exportData(convoId, settings)
  return createTransfer(scope, data)
}