// Run: node src/selfchecks/store.selfcheck.js.
import 'fake-indexeddb/auto'
import assert from 'node:assert'
import { activePane, activeRunOf, attachedDocs, conversations, createConversation, createDoc, createFromTemplate, createRun, createWorkspace, deleteConversation, deleteDoc, deleteWorkspace, docsOf, downloadExport, exportData, finishRun, globalSettings, images, importData, initStore, modelSupportsCache, models, removeDocRef, resetGlobalSettings, restoreData, runById, saveAsTemplate, selectConversation, setGlobalSettings, snapshotInfo, undoDocRevision, updateDocText, workspaceOf } from '../state/store.js'
import { setCardOverride } from '../prompt/cardMutations.js'
// recordUsage/usageDays operate on in-memory state; only snapshots are read back from the tables.
import { recordUsage, usageDays } from '../state/usage.js'
import { SNAPSHOT_VERSION, exportLastSaved } from '../state/snapshot.js'
import { dismiss, notifications } from '../utils/notify.js'
import { db, SCHEMA_VERSION } from '../state/db.js'

// The whole file runs table-backed: everything mutates through the flush and the async export reads the tables, exactly as the browser does after boot.
await initStore()

const KEYVAL_DB = 'keyval-store'
const KEYVAL_STORE = 'keyval'
const keyvalTxDone = (tx) => new Promise((resolve, reject) => {
  tx.oncomplete = () => resolve()
  tx.onerror = () => reject(tx.error)
  tx.onabort = () => reject(tx.error)
})
const deleteKeyvalDb = () => new Promise((resolve) => {
  const request = indexedDB.deleteDatabase(KEYVAL_DB)
  request.onsuccess = () => resolve()
  request.onerror = () => resolve()
  request.onblocked = () => resolve()
})
async function seedKeyvalArchive(records) {
  await deleteKeyvalDb()
  const connection = await new Promise((resolve, reject) => {
    const request = indexedDB.open(KEYVAL_DB)
    request.onupgradeneeded = (event) => event.target.result.createObjectStore(KEYVAL_STORE)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
  const tx = connection.transaction(KEYVAL_STORE, 'readwrite')
  const store = tx.objectStore(KEYVAL_STORE)
  for (const [key, value] of records) store.put(value, key)
  await keyvalTxDone(tx)
  connection.close()
}
async function clearDexie() {
  await db.transaction('rw', db.tables, async () => {
    for (const table of db.tables) await table.clear()
  })
}

assert.equal(await importData([{ id: 'a', title: 'A', messages: [] }]), 1, 'adds new conversation')
assert.equal(await importData([{ id: 'a', title: 'A2', messages: [{ id: 'm', role: 'user', content: 'hi' }] }]), 1)
let all = await exportData()
assert.equal(all.conversations.length, 2, 'collision added a copy, nothing overwritten')
assert.equal(new Set(all.conversations.map((c) => c.id)).size, 2, 'copy got fresh conversation id')
const copy = all.conversations.find((c) => c.title === 'A2')
assert.notEqual(copy.messages[0].id, 'm', 'copy got fresh message ids')

assert.equal(await importData([{ id: 'x' }, { messages: [] }, null]), 0, 'rejects malformed entries')
await assert.rejects(() => importData({ not: 'a list' }), /Not a conversa export/, 'rejects non-array')
assert.deepEqual((await exportData('a')).conversations.map((c) => c.id), ['a'], 'single export is versioned')

const w = createWorkspace('W1')
assert.equal((await exportData()).workspaces.length, 1, 'workspace included in full export')
await importData({ conversations: [], workspaces: [{ id: w.id, name: 'clobber?' }, { id: 'w2', name: 'W2' }] })
const wss = (await exportData()).workspaces
assert.equal(wss.length, 2, 'new workspace added')
assert.equal(wss.find((x) => x.id === w.id).name, 'W1', 'existing workspace not overwritten')

assert.equal(workspaceOf({ workspaceId: 'nope' }), null)
assert.equal(workspaceOf(null), null)
assert.equal(workspaceOf({ workspaceId: w.id })?.name, 'W1')

const sourceUsage = { calls: 2, input: 100, output: 20, cacheRead: 30, cacheWrite: 40, usd: 0.25, unpriced: 1 }
const t = saveAsTemplate({ id: 'c1', title: 'T', workspaceId: w.id, usage: { ...sourceUsage }, messages: [], cards: [] })
assert.equal(t.workspaceId, w.id, 'template keeps the workspace link')
assert.deepEqual(t.usage, sourceUsage, 'template keeps the usage of the conversation it came from')
const fromT = createFromTemplate(t)
assert.equal(fromT.workspaceId, w.id, 'convo from template joins the workspace')
assert.equal(fromT.usage, null, 'convo from template starts with no usage')
deleteWorkspace(w.id)
assert.ok(!(await exportData()).workspaces.some((x) => x.id === w.id), 'workspace removed')
assert.equal(fromT.workspaceId, null, 'member convo left the deleted workspace')
assert.equal(t.workspaceId, null, 'member template left the deleted workspace')

setGlobalSettings({ temperature: 0.7 })
globalSettings.value.temperature = 0.2
resetGlobalSettings()
assert.equal(globalSettings.value.temperature, 0.7, 'reset restores server defaults')
recordUsage('chat', { model: 'claude-sonnet-5', input: 100, output: 50, cache_read: 0, cache_write: 0, usd: 0.01 })
const snapshot = await exportData()
assert.equal(snapshot.version, SNAPSHOT_VERSION, 'full export is versioned')
assert.equal(snapshot.prefs.showThinkingAndSearch, true, 'thinking and search show by default')
assert.ok(snapshot.exportedAt, 'full export is dated')
assert.equal(snapshotInfo(snapshot)?.runs, 0, 'a v5 snapshot with no runs reports zero runs')
assert.ok(Array.isArray(snapshot.docs), 'the doc store joins the full export')
assert.deepEqual(snapshot.usage, usageDays(), 'the usage ledger joins the full export')
assert.ok(!Object.hasOwn(snapshot, 'models'), 'the server-owned models cache is not the user\'s data to back up')

// The ledger this restore plants. The asserts below read it back instead of retyping it.
const restoredUsage = { '2020-01-01': { m: { chat: { calls: 1, input: 1, output: 1, cacheRead: 0, cacheWrite: 0, usd: 1, unpriced: 0 } } } }
const prefs = await restoreData({
  ...snapshot,
  conversations: [{ id: 'restored', title: 'Restored', messages: [] }],
  workspaces: [{ id: 'restored-w', name: 'Restored' }],
  runs: [{ id: 'restored-r', convoId: 'restored', events: [] }],
  settings: { temperature: 0.2 },
  usage: restoredUsage,
  prefs: { theme: 'light', fontScale: 1.1, enterToSend: false, showThinkingAndSearch: false },
})
all = await exportData()
assert.deepEqual(all.conversations.map((c) => c.id), ['restored'], 'restore replaces conversations')
assert.deepEqual(all.workspaces.map((w) => w.id), ['restored-w'], 'restore replaces workspaces')
assert.deepEqual(all.runs.map((r) => r.id), ['restored-r'], 'restore keeps the snapshot\'s runs')
assert.equal(globalSettings.value.temperature, 0.2, 'restore merges saved settings')
assert.equal(prefs.theme, 'light', 'restore returns prefs for the browser caller')
assert.equal(prefs.showThinkingAndSearch, false, 'restore returns the thinking and search preference')
assert.deepEqual(usageDays(), restoredUsage, 'a snapshot with a usage field replaces the ledger, so the day recorded above is gone and the snapshot day lands intact')
await assert.rejects(async () => restoreData(await exportData('restored')), /Not a conversa snapshot/, 'partial export cannot replace a library')

// The reader is version-exact, so an older archive is refused before it can touch the database.
const v1 = { ...(await exportData()), conversations: [{ id: 'v1', title: 'V1', messages: [] }], workspaces: [], runs: [], settings: {}, prefs: {} }
v1.version = 1
delete v1.usage
const beforeV1Restore = { ...usageDays() }
await assert.rejects(() => restoreData(v1), /Not a conversa snapshot/, 'restoring an old-version snapshot is refused')
assert.deepEqual(usageDays(), beforeV1Restore, 'a refused restore leaves the ledger alone')
assert.equal(snapshotInfo(v1), null, 'an old-versioned snapshot is refused')
assert.equal(snapshotInfo({ ...v1, version: 999 }), null, 'a snapshot from a newer, not-yet-understood format is rejected')

// A merge import adds a run's row once and dedupes a repeat id; events arrive whole on a run and are not re-migrated.
await importData({ conversations: [], runs: [{ id: 'im-run', convoId: 'a' }, { id: 'im-run', convoId: 'a', events: [] }] })
assert.equal((await exportData()).runs.filter((r) => r.id === 'im-run').length, 1, 'a merge import adds a run once, deduping a repeat')

// --- Documents ---
// A merge import brings top-level docs and a workspace's docIds together; nothing is hoisted or rewritten on the way in.
await importData({
  conversations: [],
  workspaces: [{ id: 'lw', name: 'Legacy', docIds: ['ld'] }],
  docs: [{ id: 'ld', name: 'lore.md', text: 'LORE', source: { kind: 'upload' }, versions: [] }],
})
const lw = workspaceOf({ workspaceId: 'lw' })
assert.deepEqual(lw.docIds, ['ld'], 'imported workspace keeps its doc refs')
assert.equal((await exportData()).docs.find((d) => d.id === 'ld')?.source.kind, 'upload', 'the merged doc landed in the store')

// --- Workspaces ---
// A merge import adds a workspace verbatim: message-shaped prompts survive and no legacy migration runs on the way in.
await importData({
  conversations: [],
  workspaces: [
    { id: 'vp', name: 'Keeps prompts', messages: [{ id: 'sp', role: 'system', content: 'KEEP_SENTINEL', createdAt: 1 }] },
    { id: 'np', name: 'No prompt', messages: [] },
  ],
})
const vp = workspaceOf({ workspaceId: 'vp' })
assert.deepEqual(vp.messages.map((m) => [m.role, m.content]), [['system', 'KEEP_SENTINEL']], 'an imported workspace keeps its message-shaped system prompts')
assert.deepEqual(workspaceOf({ workspaceId: 'np' }).messages, [], 'a workspace imported with an empty prompt list keeps it')

// Resolution drops dangling refs; attachment merge puts workspace docs first and dedupes shared ids.
const doc2 = createDoc({ name: 'notes.md', text: 'NOTES', source: { kind: 'chat', convoId: 'v1', messageId: 'm' } })
const looseConvo = { workspaceId: 'lw', docIds: [doc2.id, 'ld', 'missing'] }
assert.deepEqual(docsOf(looseConvo).map((d) => d.id), [doc2.id, 'ld'], 'dangling refs drop out')
assert.deepEqual(attachedDocs(looseConvo).map((d) => d.id), ['ld', doc2.id], 'workspace docs lead, shared ids deduped')

// Removing a ref deletes the doc only once no workspace or conversation references it.
await importData({ conversations: [{ id: 'dc', title: 'D', messages: [], workspaceId: 'lw', docIds: ['ld'] }] })
const dc = conversations.value.find((c) => c.id === 'dc')
removeDocRef(dc, 'ld')
assert.ok((await exportData()).docs.some((d) => d.id === 'ld'), 'doc survives while the workspace still references it')
removeDocRef(lw, 'ld')
assert.ok(!(await exportData()).docs.some((d) => d.id === 'ld'), 'the last ref going deletes the doc')

// deleteDoc strips the id from every owner.
const dd = createDoc({ name: 'x.md', text: 'X', source: { kind: 'upload' } })
lw.docIds.push(dd.id)
deleteDoc(dd.id)
assert.ok(!lw.docIds.includes(dd.id), 'deleteDoc strips owner refs')

// Revisions stack in a capped window, the oldest drop first, undo pops.
const vd = createDoc({ name: 'v.md', text: 'v0', source: { kind: 'upload' } })
const edited = []
for (let i = 1; i <= 12; i++) { edited.push(vd.text); updateDocText(vd, `v${i}`) }
assert.equal(vd.text, 'v12')
const cap = vd.versions.length
assert.ok(cap < 12, 'the version window is capped below the number of edits')
assert.deepEqual(vd.versions.map((v) => v.text), edited.slice(-cap), 'the window keeps the newest edits and drops the oldest')
updateDocText(vd, 'v13')
assert.equal(vd.versions.length, cap, 'a full window sheds one instead of growing')
undoDocRevision(vd)
assert.equal(vd.text, 'v12', 'undo restores the previous text')
assert.equal(vd.versions.length, cap - 1)

// A single-conversation export carries the docs it references; re-importing keeps local copies on collision.
dc.docIds = [doc2.id]
assert.deepEqual((await exportData('dc')).docs.map((d) => d.id), [doc2.id], 'single-convo export carries its referenced docs')
await importData({ conversations: [{ id: 'dc2', title: 'D2', messages: [] }], docs: [{ id: doc2.id, name: 'clobber.md', text: 'X' }, { id: 'nd', name: 'new.md', text: 'N' }] })
assert.equal((await exportData()).docs.find((d) => d.id === doc2.id).name, 'notes.md', 'doc collision keeps the local copy')
assert.ok((await exportData()).docs.some((d) => d.id === 'nd'), 'new docs merge in')

// A merge import dedupes against the table, not memory: an image on disk but in no loaded conversation stays off memory.
const diskImg = { id: 'disk-img', data: 'aGk=', media_type: 'image/png' }
await db.images.put(diskImg)
await importData({ conversations: [], images: [{ id: 'disk-img', data: 'ZZ==', media_type: 'image/png' }] })
assert.ok(!images.value.some((i) => i.id === 'disk-img'), 'a merge import does not load an already-on-disk image of a never-loaded conversation into memory')

// Deleting an owner releases its refs through the same GC as removeDocRef.
const gw = createWorkspace('G')
const gd = createDoc({ name: 'g.md', text: 'G', source: { kind: 'upload' } })
gw.docIds.push(gd.id, doc2.id)
deleteWorkspace(gw.id)
assert.ok(!(await exportData()).docs.some((d) => d.id === gd.id), 'a doc only the deleted workspace held is gone')
assert.ok((await exportData()).docs.some((d) => d.id === doc2.id), 'a doc still attached to a conversation survives the workspace delete')

// A restored workspace is stripped of the conversation-only fields: no workspaceId to surface the override control, and no cardOverrides it could never own.
await restoreData({
  ...(await exportData()),
  conversations: [{ id: 'ws-convo', title: 'WS', messages: [] }],
  workspaces: [{ id: 'ws-w', name: 'W', workspaceId: 'leaked-convo', cardOverrides: { c1: 'on' } }],
  runs: [],
  settings: {},
  prefs: {},
  usage: {},
})
const wsOnly = workspaceOf({ workspaceId: 'ws-w' })
assert.ok(!Object.hasOwn(wsOnly, 'workspaceId'), 'a restored workspace never carries workspaceId')
assert.ok(!Object.hasOwn(wsOnly, 'cardOverrides'), 'a restored workspace never carries the conversation-only cardOverrides')
const storedWs = (await exportData()).workspaces.find((w) => w.id === 'ws-w')
assert.ok(!Object.hasOwn(storedWs, 'workspaceId'), 'the stored restored workspace row carries no workspaceId')
assert.ok(!Object.hasOwn(storedWs, 'cardOverrides'), 'the stored restored workspace row carries no cardOverrides')
setCardOverride(wsOnly, 'c1', 'on')
assert.ok(!Object.hasOwn(wsOnly, 'cardOverrides'), 'the override guard refuses a workspace even when handed one')

// Assign the ref directly rather than cacheModels(), which schedules a meta flush that needs a real IndexedDB beyond the booted one.
models.value = [{ id: 'claude-opus-5', supports_cache: true }, { id: 'openai/gpt-5.6', supports_cache: false }]
assert.equal(modelSupportsCache('claude-opus-5'), true)
assert.equal(modelSupportsCache('openai/gpt-5.6'), false)
assert.equal(modelSupportsCache('unknown/model'), true, 'a model missing from the cached list defaults to supported, not hidden')

// --- Research turns ---
// A research send links conversation, messages, and run; the final frame lands the report as a doc and folds spend once.
const rc = createConversation()
assert.equal(rc.mode, 'chat', 'a new conversation defaults to chat mode')
rc.mode = 'research'
const prompt = { id: 'rp', role: 'user', content: 'find things', mode: 'research' }
const holder = { id: 'rh', role: 'assistant', content: '', mode: 'research' }
rc.messages.push(prompt, holder)
const researchInput = { system: 'PROJECT_ORION', messages: [{ role: 'user', content: 'find things' }] }
const prepared = { action: 'research', goal: 'Compare Project Orion launch options', questions: [] }
const researchSettings = { research_search_model: 'search', research_note_model: 'note', research_report_model: 'report', research_depth: 4 }
const lr = createRun(rc, 'rp', 'rh', researchInput, prepared, researchSettings)
prompt.runId = holder.runId = lr.id
assert.equal(runById(lr.id), lr)
assert.equal(lr.convoId, rc.id, 'a run belongs to the conversation that sent it')
assert.equal(lr.status, 'starting', 'a durable run exists before the backend POST')
assert.deepEqual(lr.input, researchInput, 'the assembled context is snapshotted')
assert.deepEqual(lr.settings, researchSettings, 'effective research settings are snapshotted')
researchInput.system = 'CHANGED'
researchSettings.research_depth = 12
assert.equal(lr.input.system, 'PROJECT_ORION', 'later edits do not mutate run input')
assert.equal(lr.settings.research_depth, 4, 'later edits do not mutate run settings')
assert.equal(lr.serverId, lr.id, 'the browser persists one id for its client and server run')
assert.equal(activeRunOf(rc.id), lr, 'a starting run blocks a duplicate send')
lr.status = 'running'
assert.equal(activeRunOf(rc.id), lr, 'a running run does')

const frame = {
  status: 'done',
  phase: 'done',
  payload: { name: 'Find things', summary: 'A concise model-written summary.', report: { name: 'Research report.md', text: 'REPORT' }, sections: [] },
  spend: { models: { m: { calls: 1, input: 10, output: 5, cache_read: 0, cache_write: 0, usd: 0.01, unpriced: 0 } } },
}
const ledgerBefore = JSON.stringify(usageDays())
finishRun(lr, frame)
const reportOut = docsOf(rc).find((d) => d.id === lr.reportDocId)
assert.ok(reportOut, 'the report doc is attached to the conversation')
assert.deepEqual(reportOut.source, { kind: 'research', runId: lr.id, convoId: rc.id, messageId: 'rh' }, 'the doc carries full lineage')
assert.equal(holder.docId, lr.reportDocId, 'the result message points at the report')
assert.equal(holder.content, frame.payload.summary ?? '', 'the body carries only the model summary; the ready label lives in the research block')
assert.ok(!holder.content.includes(frame.payload.report.text), 'the report body stays in the doc, not the chat turn')
assert.ok(reportOut.text.startsWith('## Research provenance'), 'the attached document starts with its provenance header')
assert.ok(reportOut.text.endsWith('REPORT'), 'the full Q&A report stays in the attached document after the provenance header')
assert.notEqual(JSON.stringify(usageDays()), ledgerBefore, 'finished spend folds into the ledger')
const ledgerAfter = JSON.stringify(usageDays())
finishRun(lr, frame)
assert.equal(JSON.stringify(usageDays()), ledgerAfter, 'a replayed final frame does not refold')
assert.equal(docsOf(rc).filter((d) => d.id === lr.reportDocId).length, 1, 'nor duplicate the doc')

await deleteConversation(rc.id)
assert.equal(runById(lr.id), null, 'deleting a conversation deletes its runs')
assert.ok(!(await exportData()).docs.some((d) => d.id === lr.reportDocId), 'and its unshared report doc goes with it')

// activePane: the sidebar tab; selecting a conversation from any tab lands back on Chat.
activePane.value = 'usage'
selectConversation('a')
assert.equal(activePane.value, 'chat', 'selecting a conversation switches to the chat tab')

// --- Summary export and lossless round-trip ---
// Export reads every conversation's rows even when only the first is loaded, and a full round-trip is lossless.
await clearDexie()
await deleteKeyvalDb()
await seedKeyvalArchive([
  ['conversa_order', ['round-1', 'round-2', 'round-3']],
  ['conversa_workspaces', [{ id: 'round-w', name: 'Round W', messages: [], cards: [], docIds: [] }]],
  ['conversa_docs', [{ id: 'round-d', name: 'report.md', text: 'REPORT_TEXT', source: { kind: 'upload' }, createdAt: 1, updatedAt: 2, versions: [{ text: 'v0', savedAt: 1 }] }]],
  ['conversa_convo:round-1', {
    id: 'round-1', title: 'First', mode: 'chat', isTemplate: false, workspaceId: null, docIds: ['round-d'],
    createdAt: 10, updatedAt: 20, settings: {}, cards: [], cardOverrides: {}, memory: '', usage: null,
    messages: [
      { id: 'r1-m1', role: 'user', content: 'with an image', imageIds: ['round-img'], createdAt: 11 },
      { id: 'r1-m2', role: 'assistant', content: 'tool result', artifacts: [{ tool: 'web_search', query: 'Q_SENTINEL', results: ['a'] }], createdAt: 12 },
    ],
  }],
  ['conversa_convo:round-2', {
    id: 'round-2', title: 'Second', mode: 'chat', isTemplate: false, workspaceId: null, docIds: [],
    createdAt: 30, updatedAt: 40, settings: {}, cards: [], cardOverrides: {}, memory: '', usage: null,
    messages: [{ id: 'r2-m1', role: 'user', content: 'SUMMARIZED_SENTINEL', createdAt: 31 }],
  }],
  ['conversa_convo:round-3', {
    id: 'round-3', title: 'Third', mode: 'chat', isTemplate: false, workspaceId: null, docIds: [],
    createdAt: 50, updatedAt: 60, settings: {}, cards: [], cardOverrides: {}, memory: '', usage: null, messages: [],
  }],
  ['conversa_runs', [{
    id: 'round-run', convoId: 'round-1', input: { system: 'S', messages: [] },
    prepared: { brief: { objective: 'O', deliverable: 'D', scope: [], constraints: [], questions: [] } },
    settings: { model: 'm' }, events: [{ seq: 1, kind: 'phase', phase: 'START_SENTINEL' }, { seq: 1, kind: 'wave', wave: 2 }],
    createdAt: 15, updatedAt: 16,
  }]],
  ['conversa_img:round-img', { id: 'round-img', data: 'aGVsbG8=', media_type: 'image/png' }],
])
await initStore()
assert.ok(!Object.hasOwn(conversations.value.find((c) => c.id === 'round-2'), 'messages'), 'an unselected conversation boots as a summary')
const exported = await exportData()
assert.equal(exported.conversations.length, 3, 'the full export carries every conversation')
assert.equal(exported.conversations.find((c) => c.id === 'round-2').messages.length, 1, 'a summary conversation exports its stored messages')
assert.equal(exported.conversations.find((c) => c.id === 'round-2').messages[0].content, 'SUMMARIZED_SENTINEL', 'the summary message content survives export')
assert.equal(exported.runs.find((r) => r.id === 'round-run').events.length, 2, 'run events are reassembled from the event rows')
// Lose the archive entirely, restore from the export, and the whole thing comes back identical.
exported.exportedAt = 'ROUNDTRIP'
await clearDexie()
await restoreData(exported)
const after = await exportData()
after.exportedAt = 'ROUNDTRIP'
assert.deepEqual(after, exported, 'the archive round-trips losslessly')
assert.equal(after.conversations.find((c) => c.id === 'round-1').messages[1].artifacts[0].tool, 'web_search', 'tool artifacts survive the round trip')
assert.ok(after.images.some((i) => i.id === 'round-img' && i.data === 'aGVsbG8='), 'the image survives the round trip')
assert.deepEqual(after.runs.find((r) => r.id === 'round-run').events.map((e) => e.seq), [1, 1], 'events keep their colliding seqs across a restart-shaped restore, not renumbered or deduped')
assert.equal(after.docs.find((d) => d.id === 'round-d').versions.length, 1, 'doc revisions survive the round trip')

// --- Atomic restore ---
// A restore that fails mid-write rolls the whole database back to its pre-restore state.
const poison = await exportData()
// A message without its primary key is invalid to IndexedDB; the failure lands inside the restore transaction after rows were already being replaced.
poison.conversations[0].messages = [{ role: 'user', content: 'POISON_SENTINEL' }]
const restoreTables = ['conversations', 'messages', 'workspaces', 'docs', 'images', 'runs', 'runEvents', 'usage', 'meta']
const beforeRestore = {}
for (const t of restoreTables) beforeRestore[t] = await db[t].toArray()
await assert.rejects(() => restoreData(poison))
for (const t of restoreTables) {
  assert.deepEqual(await db[t].toArray(), beforeRestore[t], `a failed restore leaves every ${t} row intact`)
}

// --- A failed download surfaces instead of becoming an unhandled rejection ---
// The ordered read is db.conversations.orderBy(...).toArray(), not the table's own toArray, so the failing seam is the orderBy chain.
const readsFail = db.conversations.orderBy
db.conversations.orderBy = () => { throw new Error('export-read-failed') }
let exportRejected = false
try {
  await downloadExport()
} catch {
  exportRejected = true
} finally {
  db.conversations.orderBy = readsFail
}
assert.equal(exportRejected, false, 'a failed export never rejects its caller')

// --- A failed flush refuses a normal export; the last-saved copy still works and excludes the unsaved edit ---
const editTarget = conversations.value.find((c) => c.messages?.length)
const savedContent = editTarget.messages[0].content
editTarget.messages[0].content = 'UNSAVED_SENTINEL_EDIT'
const realBulkPut = db.messages.bulkPut
db.messages.bulkPut = () => { throw new Error('flush-failed') }
try {
  await assert.rejects(() => exportData(), /refused/, 'a normal export refuses when the flush fails')
  const lastSaved = await exportLastSaved()
  const exported = lastSaved.conversations.find((c) => c.id === editTarget.id).messages.find((m) => m.id === editTarget.messages[0].id)
  assert.equal(exported.content, savedContent, 'the last-saved copy excludes the unsaved edit')
} finally {
  db.messages.bulkPut = realBulkPut
  editTarget.messages[0].content = savedContent
}
const exportNotice = notifications.value.find((n) => n.key === 'export-failed')
assert.ok(exportNotice && exportNotice.detail?.includes('export-read-failed'), 'a failed export notifies the user with the underlying error')
await dismiss(exportNotice.id)
// --- Migration runs through the real boot path ---
// A seeded 2.4.x keyval-store migrates on the first initStore, and a second boot must not duplicate it.
await clearDexie()
await seedKeyvalArchive([
  ['conversa_order', ['mig-convo']],
  ['conversa_convo:mig-convo', {
    id: 'mig-convo',
    title: 'sentinel-integr-title',
    mode: 'chat',
    createdAt: 1000,
    updatedAt: 2000,
    docIds: [],
    messages: [
      { id: 'mig-m1', role: 'user', content: 'sentinel-integr-content', imageIds: ['mig-img'], createdAt: 1500 },
    ],
  }],
  ['conversa_runs', [
    { id: 'mig-run', convoId: 'mig-convo', input: 'sentinel-integr-run-input', prepared: { brief: { objective: 'sentinel-integr-run-objective' } }, settings: { model: 'sentinel-model' }, events: [{ seq: 1, kind: 'wave', text: 'sentinel-integr-event-text' }], createdAt: 5 },
  ]],
  ['conversa_img:mig-img', { id: 'mig-img', data: 'aGk=', media_type: 'image/png' }],
])
await initStore()
const mig = conversations.value.find((c) => c.id === 'mig-convo')
assert.equal(mig?.title, 'sentinel-integr-title', 'boot migrated the archive conversation')
assert.equal(mig.messages[0].content, 'sentinel-integr-content', 'the loaded conversation carries its migrated message')
assert.equal(runById('mig-run').input, 'sentinel-integr-run-input', 'boot loaded the migrated run')
assert.ok(runById('mig-run').events.some((e) => e.kind === 'wave' && e.text === 'sentinel-integr-event-text'), 'the migrated run carries its events')
assert.ok(images.value.some((i) => i.id === 'mig-img'), 'boot loaded the migrated image')
assert.equal((await db.meta.get('schema')).value, SCHEMA_VERSION, 'boot wrote the schema marker')

// A second boot must not duplicate or re-migrate.
const bootCounts = {
  messages: await db.messages.count(),
  runs: await db.runs.count(),
  runEvents: await db.runEvents.count(),
  conversations: await db.conversations.count(),
}
await initStore()
assert.equal(await db.messages.count(), bootCounts.messages, 'second boot does not re-migrate message rows')
assert.equal(await db.runs.count(), bootCounts.runs, 'second boot does not re-migrate run rows')
assert.equal(await db.runEvents.count(), bootCounts.runEvents, 'second boot does not re-migrate run event rows')
assert.equal(await db.conversations.count(), bootCounts.conversations, 'second boot does not re-migrate conversation rows')
assert.equal(conversations.value.length, 1, 'second boot keeps the same single conversation')
assert.ok(!(await indexedDB.databases()).some((d) => d.name === KEYVAL_DB), 'the old database stays deleted after the first migration')

// A fresh install with no keyval-store boots to an empty archive instead of throwing.
await clearDexie()
await deleteKeyvalDb()
await initStore()
assert.equal(conversations.value.length, 0, 'a fresh install boots to an empty archive')
assert.equal(runById('mig-run'), null, 'no runs on a fresh install')
assert.equal(images.value.length, 0, 'no images on a fresh install')

// A failing migration surfaces out of initStore instead of being swallowed.
await clearDexie()
await seedKeyvalArchive([
  ['conversa_order', ['bad']],
  ['conversa_convo:bad', {
    id: 'bad', title: 'dupe', messages: [
      { id: 'dup', role: 'user', content: 'a' },
      { id: 'dup', role: 'assistant', content: 'b' },
    ],
  }],
])
await assert.rejects(() => initStore(), /messages/, 'a failed migration propagates as a boot error')
await clearDexie()
await deleteKeyvalDb()
console.log('store selfcheck OK')