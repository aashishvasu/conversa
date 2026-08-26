// Run: node src/store.selfcheck.js.
import assert from 'node:assert'
import { activePane, attachedDocs, conversations, createDoc, createFromTemplate, createWorkspace, deleteDoc, deleteWorkspace, docsOf, exportData, globalSettings, importData, modelSupportsCache, models, removeDocRef, restoreData, saveAsTemplate, selectConversation, setGlobalSettings, snapshotInfo, undoDocRevision, updateDocText, workspaceOf } from './store.js'
// recordUsage/usageDays operate on in-memory state; initUsage() itself needs a real IndexedDB and is not called here, the same reason this file never calls initStore() either.
import { recordUsage, usageDays } from './usage.js'

assert.equal(importData([{ id: 'a', title: 'A', messages: [] }]), 1, 'adds new conversation')
assert.equal(importData([{ id: 'a', title: 'A2', messages: [{ id: 'm', role: 'user', content: 'hi' }] }]), 1)
let all = exportData()
assert.equal(all.conversations.length, 2, 'collision added a copy, nothing overwritten')
assert.equal(new Set(all.conversations.map((c) => c.id)).size, 2, 'copy got fresh conversation id')
const copy = all.conversations.find((c) => c.title === 'A2')
assert.notEqual(copy.messages[0].id, 'm', 'copy got fresh message ids')

assert.equal(importData([{ id: 'x' }, { messages: [] }, null]), 0, 'rejects malformed entries')
assert.throws(() => importData({ not: 'a list' }), /Not a conversa export/, 'rejects non-array')
assert.deepEqual(exportData('a').conversations.map((c) => c.id), ['a'], 'single export is versioned')

const w = createWorkspace('W1')
assert.equal(exportData().workspaces.length, 1, 'workspace included in full export')
importData({ conversations: [], workspaces: [{ id: w.id, name: 'clobber?' }, { id: 'w2', name: 'W2' }], runs: [{ id: 'r1' }] })
const wss = exportData().workspaces
assert.equal(wss.length, 2, 'new workspace added')
assert.equal(wss.find((x) => x.id === w.id).name, 'W1', 'existing workspace not overwritten')
assert.equal(exportData().runs.length, 1, 'run merge preserves a new id')

assert.equal(workspaceOf({ workspaceId: 'nope' }), null)
assert.equal(workspaceOf(null), null)
assert.equal(workspaceOf({ workspaceId: w.id })?.name, 'W1')

const t = saveAsTemplate({ id: 'c1', title: 'T', workspaceId: w.id, messages: [], cards: [] })
assert.equal(t.workspaceId, w.id, 'template keeps the workspace link')
const fromT = createFromTemplate(t)
assert.equal(fromT.workspaceId, w.id, 'convo from template joins the workspace')
deleteWorkspace(w.id)
assert.ok(!exportData().workspaces.some((x) => x.id === w.id), 'workspace removed')
assert.equal(fromT.workspaceId, null, 'member convo left the deleted workspace')
assert.equal(t.workspaceId, null, 'member template left the deleted workspace')

setGlobalSettings({ temperature: 0.7 })
recordUsage('chat', { model: 'claude-sonnet-5', input: 100, output: 50, cache_read: 0, cache_write: 0, usd: 0.01 })
const snapshot = exportData()
assert.equal(snapshot.version, 3, 'full export is versioned')
assert.ok(snapshot.exportedAt, 'full export is dated')
assert.equal(snapshotInfo(snapshot)?.runs, 1, 'snapshot reports run count')
assert.ok(Array.isArray(snapshot.docs), 'the doc store joins the full export')
assert.deepEqual(snapshot.usage, usageDays(), 'the usage ledger joins the full export')
assert.ok(!Object.hasOwn(snapshot, 'models'), 'the server-owned models cache is not the user\'s data to back up')

const prefs = await restoreData({
  ...snapshot,
  conversations: [{ id: 'restored', title: 'Restored', messages: [] }],
  workspaces: [{ id: 'restored-w', name: 'Restored' }],
  runs: [{ id: 'restored-r' }],
  settings: { temperature: 0.2 },
  usage: { '2020-01-01': { m: { chat: { calls: 1, input: 1, output: 1, cacheRead: 0, cacheWrite: 0, usd: 1, unpriced: 0 } } } },
  prefs: { theme: 'light', fontScale: 1.1, enterToSend: false },
})
all = exportData()
assert.deepEqual(all.conversations.map((c) => c.id), ['restored'], 'restore replaces conversations')
assert.deepEqual(all.workspaces.map((w) => w.id), ['restored-w'], 'restore replaces workspaces')
assert.deepEqual(all.runs.map((r) => r.id), ['restored-r'], 'restore replaces runs')
assert.equal(globalSettings.value.temperature, 0.2, 'restore merges saved settings')
assert.equal(prefs.theme, 'light', 'restore returns prefs for the browser caller')
assert.deepEqual(usageDays(), { '2020-01-01': { m: { chat: { calls: 1, input: 1, output: 1, cacheRead: 0, cacheWrite: 0, usd: 1, unpriced: 0 } } } }, 'a snapshot with a usage field replaces the ledger')
await assert.rejects(() => restoreData(exportData('restored')), /Not a conversa snapshot/, 'partial export cannot replace a library')

// A v1 snapshot (before usage.md) has no usage field, and restoring one must not wipe the current ledger.
const v1 = { ...exportData(), conversations: [{ id: 'v1', title: 'V1', messages: [] }], workspaces: [], runs: [], settings: {}, prefs: {} }
v1.version = 1
delete v1.usage
const beforeV1Restore = { ...usageDays() }
await restoreData(v1)
assert.deepEqual(usageDays(), beforeV1Restore, 'a v1 snapshot with no usage field leaves the current ledger alone')
assert.equal(snapshotInfo(v1)?.conversations, 1, 'an old-versioned snapshot is still accepted')
assert.equal(snapshotInfo({ ...v1, version: 999 }), null, 'a snapshot from a newer, not-yet-understood format is rejected')

// --- Documents ---
// A legacy export with inline workspace docs hoists them into the doc store as refs.
importData({ conversations: [], workspaces: [{ id: 'lw', name: 'Legacy', docs: [{ id: 'ld', name: 'lore.md', text: 'LORE' }] }] })
const lw = workspaceOf({ workspaceId: 'lw' })
assert.deepEqual(lw.docIds, ['ld'], 'inline docs became refs on import')
assert.ok(!lw.docs, 'the inline list is gone after the hoist')
assert.equal(exportData().docs.find((d) => d.id === 'ld')?.source.kind, 'upload', 'the hoisted doc landed in the store')

// Resolution drops dangling refs; attachment merge puts workspace docs first and dedupes shared ids.
const doc2 = createDoc({ name: 'notes.md', text: 'NOTES', source: { kind: 'chat', convoId: 'v1', messageId: 'm' } })
const looseConvo = { workspaceId: 'lw', docIds: [doc2.id, 'ld', 'missing'] }
assert.deepEqual(docsOf(looseConvo).map((d) => d.id), [doc2.id, 'ld'], 'dangling refs drop out')
assert.deepEqual(attachedDocs(looseConvo).map((d) => d.id), ['ld', doc2.id], 'workspace docs lead, shared ids deduped')

// Removing a ref deletes the doc only once no workspace or conversation references it.
importData({ conversations: [{ id: 'dc', title: 'D', messages: [], workspaceId: 'lw', docIds: ['ld'] }] })
const dc = conversations.value.find((c) => c.id === 'dc')
removeDocRef(dc, 'ld')
assert.ok(exportData().docs.some((d) => d.id === 'ld'), 'doc survives while the workspace still references it')
removeDocRef(lw, 'ld')
assert.ok(!exportData().docs.some((d) => d.id === 'ld'), 'the last ref going deletes the doc')

// deleteDoc strips the id from every owner.
const dd = createDoc({ name: 'x.md', text: 'X', source: { kind: 'upload' } })
lw.docIds.push(dd.id)
deleteDoc(dd.id)
assert.ok(!lw.docIds.includes(dd.id), 'deleteDoc strips owner refs')

// Revisions stack capped, undo pops.
const vd = createDoc({ name: 'v.md', text: 'v0', source: { kind: 'upload' } })
for (let i = 1; i <= 12; i++) updateDocText(vd, `v${i}`)
assert.equal(vd.text, 'v12')
assert.equal(vd.versions.length, 10, 'versions cap at 10')
assert.equal(vd.versions[0].text, 'v2', 'the oldest versions drop first')
undoDocRevision(vd)
assert.equal(vd.text, 'v11', 'undo restores the previous text')
assert.equal(vd.versions.length, 9)

// A single-conversation export carries the docs it references; re-importing keeps local copies on collision.
dc.docIds = [doc2.id]
assert.deepEqual(exportData('dc').docs.map((d) => d.id), [doc2.id], 'single-convo export carries its referenced docs')
importData({ conversations: [{ id: 'dc2', title: 'D2', messages: [] }], docs: [{ id: doc2.id, name: 'clobber.md', text: 'X' }, { id: 'nd', name: 'new.md', text: 'N' }] })
assert.equal(exportData().docs.find((d) => d.id === doc2.id).name, 'notes.md', 'doc collision keeps the local copy')
assert.ok(exportData().docs.some((d) => d.id === 'nd'), 'new docs merge in')

// Deleting an owner releases its refs through the same GC as removeDocRef.
const gw = createWorkspace('G')
const gd = createDoc({ name: 'g.md', text: 'G', source: { kind: 'upload' } })
gw.docIds.push(gd.id, doc2.id)
deleteWorkspace(gw.id)
assert.ok(!exportData().docs.some((d) => d.id === gd.id), 'a doc only the deleted workspace held is gone')
assert.ok(exportData().docs.some((d) => d.id === doc2.id), 'a doc still attached to a conversation survives the workspace delete')

// Restoring a pre-v3 snapshot hoists its inline docs into the replacing doc set.
const v2 = { version: 2, exportedAt: 'x', conversations: [], workspaces: [{ id: 'rw2', name: 'R2', docs: [{ id: 'rd', name: 'r.md', text: 'R' }] }], runs: [], settings: {}, prefs: {} }
assert.equal(snapshotInfo(v2)?.docs, 1, 'pre-v3 snapshots count inline docs')
await restoreData(v2)
assert.deepEqual(exportData().docs.map((d) => d.id), ['rd'], 'restore hoists inline docs into the store')
assert.deepEqual(exportData().workspaces[0].docIds, ['rd'], 'the restored workspace references them')

// Assign the ref directly rather than cacheModels(), which persists via idb-keyval's set() and needs a real IndexedDB, the same reason this file never calls initStore()/initUsage() either.
models.value = [{ id: 'claude-opus-5', supports_cache: true }, { id: 'openai/gpt-5.6', supports_cache: false }]
assert.equal(modelSupportsCache('claude-opus-5'), true)
assert.equal(modelSupportsCache('openai/gpt-5.6'), false)
assert.equal(modelSupportsCache('unknown/model'), true, 'a model missing from the cached list defaults to supported, not hidden')

// activePane: the sidebar tab; selecting a conversation from any tab lands back on Chat.
activePane.value = 'usage'
selectConversation('a')
assert.equal(activePane.value, 'chat', 'selecting a conversation switches to the chat tab')

console.log('store selfcheck OK')
