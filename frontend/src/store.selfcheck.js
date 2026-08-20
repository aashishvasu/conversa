// Run: node src/store.selfcheck.js.
// Fails loudly if export/import merge breaks.
import assert from 'node:assert'
import { createFromTemplate, createWorkspace, deleteWorkspace, exportData, importData, saveAsTemplate, workspaceOf } from './store.js'

assert.equal(importData([{ id: 'a', title: 'A', messages: [] }]), 1, 'adds new conversation')
// colliding id imports as a copy with fresh ids instead of being skipped/overwritten
assert.equal(importData([{ id: 'a', title: 'A2', messages: [{ id: 'm', role: 'user', content: 'hi' }] }]), 1)
let all = exportData()
assert.equal(all.conversations.length, 2, 'collision added a copy, nothing overwritten')
assert.equal(new Set(all.conversations.map((c) => c.id)).size, 2, 'copy got a fresh conversation id')
const copy = all.conversations.find((c) => c.title === 'A2')
assert.notEqual(copy.messages[0].id, 'm', 'copy got fresh message ids')

assert.equal(importData([{ id: 'x' }, { messages: [] }, null]), 0, 'rejects malformed entries')
assert.throws(() => importData({ not: 'a list' }), /Not a conversa export/, 'rejects non-array')

// single-conversation export: still an array, so it round-trips through import
assert.deepEqual(exportData('a').map((c) => c.id), ['a'])
assert.equal(exportData().conversations.length, 2, 'no-arg export returns everything')

// workspaces: exported with the full backup; import keeps local on id collision (convo-to-workspace links stay resolvable) and adds unknown ids
const w = createWorkspace('W1')
assert.equal(exportData().workspaces.length, 1, 'workspace included in full export')
importData({ conversations: [], workspaces: [{ id: w.id, name: 'clobber?' }, { id: 'w2', name: 'W2' }] })
const wss = exportData().workspaces
assert.equal(wss.length, 2, 'new workspace added')
assert.equal(wss.find((x) => x.id === w.id).name, 'W1', 'existing workspace not overwritten')

// workspaceOf degrades to null for missing/deleted/unimported workspace ids
assert.equal(workspaceOf({ workspaceId: 'nope' }), null)
assert.equal(workspaceOf(null), null)
assert.equal(workspaceOf({ workspaceId: w.id })?.name, 'W1')

// templates keep the workspace link; conversations created from them inherit it
const t = saveAsTemplate({ id: 'c1', title: 'T', workspaceId: w.id, messages: [], cards: [] })
assert.equal(t.workspaceId, w.id, 'template keeps the workspace link')
const fromT = createFromTemplate(t)
assert.equal(fromT.workspaceId, w.id, 'convo from template joins the workspace')

// deleting a workspace clears membership on convos and templates, and only that
deleteWorkspace(w.id)
assert.ok(!exportData().workspaces.some((x) => x.id === w.id), 'workspace removed')
assert.equal(fromT.workspaceId, null, 'member convo left the deleted workspace')
assert.equal(t.workspaceId, null, 'member template left the deleted workspace')
assert.ok(exportData().conversations.some((c) => c.title === 'T'), 'convos themselves survive')

console.log('store selfcheck OK')
