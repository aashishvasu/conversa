// Run: node src/store.selfcheck.js — fails loudly if export/import merge breaks.
import assert from 'node:assert'
import { exportData, importData } from './store.js'

assert.equal(importData([{ id: 'a', title: 'A', messages: [] }]), 1, 'adds new conversation')
// colliding id imports as a copy with fresh ids instead of being skipped/overwritten
assert.equal(importData([{ id: 'a', title: 'A2', messages: [{ id: 'm', role: 'user', content: 'hi' }] }]), 1)
let all = exportData()
assert.equal(all.length, 2, 'collision added a copy, nothing overwritten')
assert.equal(new Set(all.map((c) => c.id)).size, 2, 'copy got a fresh conversation id')
const copy = all.find((c) => c.title === 'A2')
assert.notEqual(copy.messages[0].id, 'm', 'copy got fresh message ids')

assert.equal(importData([{ id: 'x' }, { messages: [] }, null]), 0, 'rejects malformed entries')
assert.throws(() => importData({ not: 'a list' }), /Not a conversa export/, 'rejects non-array')

// single-conversation export: still an array, so it round-trips through import
assert.deepEqual(exportData('a').map((c) => c.id), ['a'])
assert.equal(exportData().length, 2, 'no-arg export returns everything')

console.log('store selfcheck OK')
