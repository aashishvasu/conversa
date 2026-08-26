// Run: node src/store.selfcheck.js.
import assert from 'node:assert'
import { createFromTemplate, createRun, createWorkspace, deleteWorkspace, exportData, globalSettings, importData, restoreData, saveAsTemplate, setGlobalSettings, snapshotInfo, workspaceOf } from './store.js'

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
const snapshot = exportData()
assert.equal(snapshot.version, 1, 'full export is versioned')
assert.ok(snapshot.exportedAt, 'full export is dated')
assert.equal(snapshotInfo(snapshot)?.runs, 2, 'snapshot reports run count')
const prefs = await restoreData({
  ...snapshot,
  conversations: [{ id: 'restored', title: 'Restored', messages: [] }],
  workspaces: [{ id: 'restored-w', name: 'Restored' }],
  runs: [{ id: 'restored-r' }],
  settings: { temperature: 0.2 },
  prefs: { theme: 'light', fontScale: 1.1, enterToSend: false },
})
all = exportData()
assert.deepEqual(all.conversations.map((c) => c.id), ['restored'], 'restore replaces conversations')
assert.deepEqual(all.workspaces.map((w) => w.id), ['restored-w'], 'restore replaces workspaces')
assert.deepEqual(all.runs.map((r) => r.id), ['restored-r'], 'restore replaces runs')
assert.equal(globalSettings.value.temperature, 0.2, 'restore merges saved settings')
assert.equal(prefs.theme, 'light', 'restore returns prefs for the browser caller')
await assert.rejects(() => restoreData(exportData('restored')), /Not a conversa snapshot/, 'partial export cannot replace a library')

console.log('store selfcheck OK')
