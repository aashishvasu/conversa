import { reactive, toRaw, watch } from 'vue'
import { dismiss, notify } from '../utils/notify.js'
import { tr } from '../i18n/index.js'
import { db } from './db.js'
import { commitUsage, restoreUsagePending, takeUsagePending } from './usage.js'

export const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])
const DB_TABLES = ['workspaces', 'docs', 'runs', 'conversations', 'messages', 'runEvents', 'images', 'usage', 'meta']
export const state = reactive({ conversations: [], workspaces: [], runs: [], docs: [], images: [] })
let loaded = false
export function setLoaded(v) { loaded = v }
export function isLoaded() { return loaded }
let _downloadExportFn = null
export function setDownloadExport(fn) { _downloadExportFn = fn }
// An IndexedDB DOMException on some browsers keeps the name and message out of .stack, so put them first and keep the stack as the tail.
export function storageFailure(e) {
  const head = [e?.name, e?.message].filter(Boolean).join(': ')
  notify({
    key: 'storage',
    sticky: true,
    text: tr('notification.storage'),
    detail: e?.stack ? `${head}\n${e.stack}` : head || String(e),
    action: { label: tr('notification.downloadBackup'), fn: () => _downloadExportFn?.() },
  })
}
const SAVE_DEBOUNCE = 400
let saveTimer
let chain = Promise.resolve()
function save() {
  if (!loaded) return
  clearTimeout(saveTimer)
  saveTimer = setTimeout(enqueueFlush, SAVE_DEBOUNCE)
}
export function scheduleFlush() { save() }
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
// Reads one message row by id, bypassing every path that would schedule a write.
export function readStoredMessage(id) {
  return db.messages.get(id)
}
// Rows still carrying a turnId are live turns that a reload or reconnection must reattach. The turnId index holds only rows with a defined key, so this finds them across every conversation without loading any.
export async function readPendingTurnMessages() {
  return (await db.messages.orderBy('turnId').toArray()).filter((m) => m.turnId)
}
function isPlainObject(v) {
  const p = Object.getPrototypeOf(v)
  return p === Object.prototype || p === null
}
// WHY: IndexedDB structured clone throws DataCloneError on Vue reactive proxies, and a JSON round-trip silently mangles Date, NaN and Map; rebuilding plain objects by hand keeps every value intact while still unwrapping nested proxies.
export function plainCopy(value) {
  const raw = toRaw(value)
  if (Array.isArray(raw)) return raw.map(plainCopy)
  if (raw && typeof raw === 'object' && isPlainObject(raw)) {
    const out = {}
    for (const key of Object.keys(raw)) out[key] = plainCopy(raw[key])
    return out
  }
  return raw
}
// A conversation is a summary (row only) or loaded (row plus messages and their images, with watchers attached).
// An absent `messages` field makes a missed load fail loudly; an empty array would let a walker see nothing.
export async function ensureLoaded(convo) {
  if (!convo || convo.messages) return
  const rows = await db.messages.where('convoId').equals(convo.id).toArray()
  const images = (await db.images.bulkGet([...new Set(rows.flatMap((m) => m.imageIds || []))])).filter(Boolean)
  const byId = new Map(rows.map((m) => [m.id, m]))
  const listed = new Set(convo.messageIds || [])
  const ordered = [...(convo.messageIds || [])].map((id) => byId.get(id)).filter(Boolean)
  const strays = rows.filter((m) => !listed.has(m.id)).sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0))
  convo.messages = [...ordered, ...strays]
  for (const image of images) if (!state.images.some((i) => i.id === image.id)) state.images.push(image)
  syncMessageWatchers(convo, false)
}
const convoWatchers = new Map()
const messageWatchers = new Map()
const knownMessageIds = new Map()
let dirtyConvos = new Set()
let removedConvos = new Set()
let dirtyMessages = new Set()
let removedMessages = new Set()
const workspaceWatchers = new Map()
const docWatchers = new Map()
const runWatchers = new Map()
let dirtyDocs = new Set()
let removedDocs = new Set()
let dirtyRuns = new Set()
let removedRuns = new Set()
let dirtyWorkspaces = new Set()
let removedWorkspaces = new Set()
let dirtyRunEvents = false
let removedImages = new Set()
const dirtyMeta = new Map()
export function markImagesRemoved(ids) {
  for (const id of ids) removedImages.add(id)
}
// Image removals are consumed by the flush; a snapshot restore winnows the DB itself, so its marks would wipe freshly restored rows.
export function resetRemovedImages() { removedImages.clear() }
export function markMetaWrite(key, value) { dirtyMeta.set(key, value) }
let writtenEventCounts = new Map()
let watching = false
function sameSet(a, b) {
  if (a.size !== b.size) return false
  for (const v of a) if (!b.has(v)) return false
  return true
}
// The conversation's own fields and its message list; message content is deliberately excluded so a checkpoint dirties only the message row.
// updatedAt is maintained in the watchers themselves, so it stays out of the watched fields or the bump would re-trigger the watcher.
function convoFields(convo) {
  const { messages, updatedAt, ...rest } = convo
  return { ...rest, messageIds: [...(convo.messageIds || [])], messageList: (convo.messages || []).map((m) => m.id).join(',') }
}
function syncMessageWatchers(convo, markNewDirty) {
  // A summary has no messages in memory, so messageIds is the stored record and must not be derived from an empty list.
  if (!convo.messages) return
  const messages = convo.messages
  const present = new Set(messages.map((m) => m.id))
  const known = knownMessageIds.get(convo.id) || new Set()
  for (const m of messages) {
    if (!known.has(m.id) && markNewDirty) dirtyMessages.add(m.id)
    if (!messageWatchers.has(m.id)) {
      let hadTurn = Boolean(m.turnId)
      // A released turnId is the settle: the message stops being a live turn, and the row bump outlives the reload.
      // The previous turnId is boxed in a closure rather than read off the watcher's oldValue, which is the live proxy, not a pre-change clone.
      messageWatchers.set(m.id, {
        stop: watch(() => m, () => {
          const hasTurn = Boolean(m.turnId)
          if (hadTurn && !hasTurn) {
            convo.updatedAt = Date.now()
            dirtyConvos.add(convo.id)
          }
          hadTurn = hasTurn
          dirtyMessages.add(m.id)
          save()
        }, { deep: true }),
      })
    }
  }
  for (const id of known) {
    if (!present.has(id)) {
      messageWatchers.get(id)?.stop()
      messageWatchers.delete(id)
      removedMessages.add(id)
    }
  }
  knownMessageIds.set(convo.id, present)
  // messageIds is the persisted record of what messages exist; it follows the in-memory list rather than living on callers.
  // A membership change is an add or a delete, which is what the sidebar's last-activity stamp means; loading is the same ids, so it never bumps.
  if (!sameSet(present, new Set(convo.messageIds || []))) {
    convo.messageIds = [...present]
    convo.updatedAt = Date.now()
  }
}
function syncConvoWatchers(markReplaced) {
  const present = new Set()
  for (const item of state.conversations) {
    present.add(item.id)
    const known = convoWatchers.get(item.id)
    if (known?.item === item) continue
    known?.stop()
    // A replaced conversation (reload, import, restore) carries fresh message objects; drop the watchers that watched the old ones.
    for (const mid of knownMessageIds.get(item.id) || []) {
      messageWatchers.get(mid)?.stop()
      messageWatchers.delete(mid)
    }
    knownMessageIds.delete(item.id)
    convoWatchers.set(item.id, {
      item,
      stop: watch(() => convoFields(item), () => { dirtyConvos.add(item.id); syncMessageWatchers(item, true); save() }),
    })
    if (markReplaced) dirtyConvos.add(item.id)
    syncMessageWatchers(item, markReplaced)
  }
  for (const [id, known] of convoWatchers) {
    if (present.has(id)) continue
    known.stop()
    convoWatchers.delete(id)
    dirtyConvos.delete(id)
    removedConvos.add(id)
    for (const mid of knownMessageIds.get(id) || []) {
      messageWatchers.get(mid)?.stop()
      messageWatchers.delete(mid)
    }
    knownMessageIds.delete(id)
  }
}
function runFields(run) {
  const { events, ...rest } = run
  return rest
}
// Events are append-only rows of their own, so the run watcher excludes them and a length watcher drives the append; including events here would rewrite the payload-heavy run row on every drain tick.
function syncDocWatchers(markReplaced) {
  const present = new Set()
  for (const item of state.docs) {
    present.add(item.id)
    const known = docWatchers.get(item.id)
    if (known?.item === item) continue
    known?.stop()
    docWatchers.set(item.id, {
      item,
      stop: watch(() => item, () => { dirtyDocs.add(item.id); save() }, { deep: true }),
    })
    if (markReplaced) dirtyDocs.add(item.id)
  }
  for (const [id, known] of docWatchers) {
    if (present.has(id)) continue
    known.stop()
    docWatchers.delete(id)
    dirtyDocs.delete(id)
    removedDocs.add(id)
  }
}
function syncRunWatchers(markReplaced) {
  const present = new Set()
  for (const item of state.runs) {
    present.add(item.id)
    const known = runWatchers.get(item.id)
    if (known?.item === item) continue
    known?.stop()
    runWatchers.set(item.id, {
      item,
      stop: watch(() => runFields(item), () => { dirtyRuns.add(item.id); save() }, { deep: true }),
    })
    if (markReplaced) dirtyRuns.add(item.id)
  }
  for (const [id, known] of runWatchers) {
    if (present.has(id)) continue
    known.stop()
    runWatchers.delete(id)
    dirtyRuns.delete(id)
    removedRuns.add(id)
  }
}
function syncWorkspaceWatchers(markReplaced) {
  const present = new Set()
  for (const item of state.workspaces) {
    present.add(item.id)
    const known = workspaceWatchers.get(item.id)
    if (known?.item === item) continue
    known?.stop()
    workspaceWatchers.set(item.id, {
      item,
      stop: watch(() => item, () => { dirtyWorkspaces.add(item.id); save() }, { deep: true }),
    })
    if (markReplaced) dirtyWorkspaces.add(item.id)
  }
  for (const [id, known] of workspaceWatchers) {
    if (present.has(id)) continue
    known.stop()
    workspaceWatchers.delete(id)
    dirtyWorkspaces.delete(id)
    removedWorkspaces.add(id)
  }
}
export function startWatching() {
  if (!watching) {
    watching = true
    watch(() => state.conversations.map((c) => c.id), () => { syncConvoWatchers(true); save() })
    watch(() => state.docs.map((d) => d.id), () => { syncDocWatchers(true); save() })
    watch(() => state.runs.map((r) => r.id), () => { syncRunWatchers(true); save() })
    watch(() => state.runs.map((r) => r.events?.length || 0), () => { dirtyRunEvents = true; save() })
    watch(() => state.workspaces.map((w) => w.id), () => { syncWorkspaceWatchers(true); save() })
  }
  syncConvoWatchers(false)
  syncDocWatchers(false)
  syncRunWatchers(false)
  syncWorkspaceWatchers(false)
  dirtyConvos.clear()
  removedConvos.clear()
  dirtyMessages.clear()
  removedMessages.clear()
  dirtyDocs.clear()
  removedDocs.clear()
  dirtyRuns.clear()
  removedRuns.clear()
  dirtyWorkspaces.clear()
  removedWorkspaces.clear()
  dirtyRunEvents = false
}
function convoRow(convo) {
  if (!convo) return null
  const { messages, ...row } = convo
  return row
}
function messageRows(messageIds) {
  const byId = new Map()
  for (const c of state.conversations) for (const m of c.messages || []) if (!byId.has(m.id)) byId.set(m.id, { convo: c, message: m })
  const rows = []
  for (const id of messageIds) {
    const hit = byId.get(id)
    if (hit) rows.push({ ...plainCopy(hit.message), convoId: hit.convo.id })
  }
  return rows
}
function runRow(run) {
  const { events, ...row } = run
  return plainCopy(row)
}
async function appendNewRunEvents(runs) {
  for (const run of runs) {
    const events = run.events || []
    const written = writtenEventCounts.get(run.id) ?? 0
    if (events.length < written) {
      await db.runEvents.where('runId').equals(run.id).delete()
      const insert = events.slice()
      if (insert.length) await db.runEvents.bulkAdd(insert.map((event) => ({ ...plainCopy(event), runId: run.id })))
      writtenEventCounts.set(run.id, insert.length)
    } else if (events.length > written) {
      const insert = events.slice(written)
      if (insert.length) await db.runEvents.bulkAdd(insert.map((event) => ({ ...plainCopy(event), runId: run.id })))
      writtenEventCounts.set(run.id, events.length)
    }
  }
}
// A reload rebuilds the in-memory event arrays from the runEvents table, so the written baseline must match what is now loaded or the next flush would re-append every event.
export function seedRunEventCounts() {
  writtenEventCounts.clear()
  for (const run of state.runs) writtenEventCounts.set(run.id, run.events?.length ?? 0)
}
function clearPending() {
  dirtyConvos.clear()
  removedConvos.clear()
  dirtyMessages.clear()
  removedMessages.clear()
  dirtyDocs.clear()
  removedDocs.clear()
  dirtyRuns.clear()
  removedRuns.clear()
  dirtyWorkspaces.clear()
  removedWorkspaces.clear()
  dirtyRunEvents = false
  removedImages.clear()
  dirtyMeta.clear()
}

function collectPending() {
  const ids = state.conversations.map((c) => c.id)
  const present = new Set(ids)
  const pending = {
    convos: [...dirtyConvos].filter((id) => present.has(id)),
    removed: [...removedConvos].filter((id) => !present.has(id)),
    messageIds: [...dirtyMessages],
    removedMessageIds: [...removedMessages],
    workspaceIds: [...dirtyWorkspaces].filter((id) => state.workspaces.some((w) => w.id === id)),
    removedWorkspaceIds: [...removedWorkspaces],
    docIds: [...dirtyDocs],
    removedDocIds: [...removedDocs],
    runIds: [...dirtyRuns].filter((id) => state.runs.some((r) => r.id === id)),
    removedRunIds: [...removedRuns],
    eventsDirty: dirtyRunEvents,
    removedImageIds: [...removedImages],
    usage: takeUsagePending(),
    meta: new Map(dirtyMeta),
  }
  clearPending()
  return pending
}

function isPendingEmpty(p) {
  return !p.convos.length && !p.removed.length && !p.messageIds.length && !p.removedMessageIds.length &&
    !p.workspaceIds.length && !p.removedWorkspaceIds.length && !p.docIds.length && !p.removedDocIds.length &&
    !p.runIds.length && !p.removedRunIds.length && !p.eventsDirty && !p.removedImageIds.length &&
    !p.usage.deltas.size && p.usage.replace === null && !p.meta.size
}

async function writePending(p) {
  await db.transaction('rw', DB_TABLES, async () => {
    if (p.convos.length) await db.conversations.bulkPut(p.convos.map((id) => plainCopy(convoRow(state.conversations.find((c) => c.id === id)))))
    if (p.removed.length) {
      await db.conversations.bulkDelete(p.removed)
      for (const id of p.removed) {
        await db.messages.where('convoId').equals(id).delete()
        const cascadeRunIds = await db.runs.where('convoId').equals(id).primaryKeys()
        if (cascadeRunIds.length) {
          await db.runEvents.where('runId').anyOf(cascadeRunIds).delete()
          await db.runs.bulkDelete(cascadeRunIds)
          for (const rid of cascadeRunIds) writtenEventCounts.delete(rid)
        }
      }
    }
    if (p.messageIds.length) await db.messages.bulkPut(messageRows(p.messageIds))
    if (p.removedMessageIds.length) await db.messages.bulkDelete(p.removedMessageIds)
    if (p.workspaceIds.length) await db.workspaces.bulkPut(p.workspaceIds.map((id) => plainCopy(state.workspaces.find((w) => w.id === id))))
    if (p.removedWorkspaceIds.length) await db.workspaces.bulkDelete(p.removedWorkspaceIds)
    if (p.docIds.length) await db.docs.bulkPut(p.docIds.map((id) => plainCopy(state.docs.find((d) => d.id === id))))
    if (p.removedDocIds.length) await db.docs.bulkDelete(p.removedDocIds)
    if (p.runIds.length) await db.runs.bulkPut(p.runIds.map((id) => runRow(state.runs.find((r) => r.id === id))))
    if (p.removedRunIds.length) {
      await db.runEvents.where('runId').anyOf(p.removedRunIds).delete()
      for (const id of p.removedRunIds) writtenEventCounts.delete(id)
      await db.runs.bulkDelete(p.removedRunIds)
    }
    if (p.eventsDirty) await appendNewRunEvents(state.runs)
    if (p.removedImageIds.length) await db.images.bulkDelete(p.removedImageIds)
    if (p.usage.deltas.size || p.usage.replace !== null) await commitUsage(p.usage)
    if (p.meta.size) await db.meta.bulkPut([...p.meta].map(([key, value]) => ({ key, value: plainCopy(value) })))
  })
}

function restorePending(p) {
  for (const id of p.convos) dirtyConvos.add(id)
  for (const id of p.removed) removedConvos.add(id)
  for (const id of p.messageIds) dirtyMessages.add(id)
  for (const id of p.removedMessageIds) removedMessages.add(id)
  for (const id of p.docIds) dirtyDocs.add(id)
  for (const id of p.removedDocIds) removedDocs.add(id)
  for (const id of p.runIds) dirtyRuns.add(id)
  for (const id of p.workspaceIds) dirtyWorkspaces.add(id)
  for (const id of p.removedWorkspaceIds) removedWorkspaces.add(id)
  if (p.eventsDirty) dirtyRunEvents = true
  for (const id of p.removedImageIds) removedImages.add(id)
  restoreUsagePending(p.usage)
  for (const [key, value] of p.meta) dirtyMeta.set(key, value)
}

async function runFlush() {
  const pending = collectPending()
  if (isPendingEmpty(pending)) return true
  try {
    await writePending(pending)
    dismiss('storage')
    return true
  } catch (error) {
    restorePending(pending)
    storageFailure(error)
    return false
  }
}
