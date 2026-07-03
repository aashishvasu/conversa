// Run: node src/confirm.selfcheck.js — fails loudly if the confirm contract breaks.
import assert from 'node:assert'
import { answerConfirm, confirmDelete, confirmState } from './confirm.js'

const p = confirmDelete('delete?')
assert.ok(confirmState.value, 'opens (state set while pending)')
assert.equal(confirmState.value.label, 'Delete', 'default label')
answerConfirm(true)
assert.equal(confirmState.value, null, 'closes (state cleared after answer)')
assert.equal(await p, true, 'resolves with the answer')

const p2 = confirmDelete('clear?', 'Clear')
assert.equal(confirmState.value.label, 'Clear', 'custom label')
answerConfirm(false)
assert.equal(await p2, false, 'cancel resolves false')

console.log('confirm selfcheck OK')
