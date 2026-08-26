// Run: node src/store.selfcheck.js.
import assert from 'node:assert'
import { createFromTemplate, createRun, createWorkspace, deleteWorkspace, exportData, globalSettings, importData, modelSupportsCache, models, restoreData, saveAsTemplate, setGlobalSettings, snapshotInfo, workspaceOf } from './store.js'
// recordUsage/usageDays operate on in-memory state; initUsage() itself needs a real IndexedDB
// and is not called here, the same reason this file never calls initStore() either.
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

createRun()
setGlobalSettings({ temperature: 0.7 })
recordUsage('chat', { model: 'claude-sonnet-5', input: 100, output: 50, cache_read: 0, cache_write: 0, usd: 0.01 })
const snapshot = exportData()
assert.equal(snapshot.version, 2, 'full export is versioned')
assert.ok(snapshot.exportedAt, 'full export is dated')
assert.equal(snapshotInfo(snapshot)?.runs, 2, 'snapshot reports run count')
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

// Assign the ref directly rather than cacheModels(), which persists via idb-keyval's set() and
// needs a real IndexedDB, the same reason this file never calls initStore()/initUsage() either.
models.value = [{ id: 'claude-opus-5', supports_cache: true }, { id: 'openai/gpt-5.6', supports_cache: false }]
assert.equal(modelSupportsCache('claude-opus-5'), true)
assert.equal(modelSupportsCache('openai/gpt-5.6'), false)
assert.equal(modelSupportsCache('unknown/model'), true, 'a model missing from the cached list defaults to supported, not hidden')

console.log('store selfcheck OK')
