// Run: node src/usage.selfcheck.js.
import assert from 'node:assert'
import { addConvoUsage, addUsage, foldUsage, replaceUsage, usageDays } from './usage.js'

const days = {}
addUsage(days, 'chat', 'claude-sonnet-5', { input: 100, output: 50, cache_read: 0, cache_write: 0, usd: 0.001 }, '2026-08-24')
addUsage(days, 'chat', 'claude-sonnet-5', { input: 200, output: 0, cache_read: 500, cache_write: 0, usd: 0.0006 }, '2026-08-24')
addUsage(days, 'utility', 'claude-haiku-4-5', { input: 10, output: 10, usd: 0.0001 }, '2026-08-24')
addUsage(days, 'research', 'claude-sonnet-5', { input: 1000, output: 500, usd: 0.01 }, '2026-08-25')

const chatRow = days['2026-08-24']['claude-sonnet-5'].chat
assert.equal(chatRow.calls, 2, 'two chat generations folded into one row')
assert.equal(chatRow.input, 300)
assert.equal(chatRow.cacheRead, 500, "the frame's cache_read maps to the ledger's cacheRead")
assert.equal(Math.round(chatRow.usd * 1e6), 1600, 'usd sums across calls')

assert.ok(days['2026-08-24']['claude-haiku-4-5'].utility, 'a different kind gets its own row')
assert.ok(!days['2026-08-24']['claude-haiku-4-5'].chat, 'kinds do not bleed into each other')
assert.equal(days['2026-08-24']['claude-sonnet-5'].research, undefined, 'a different day is a different bucket')
assert.equal(days['2026-08-25']['claude-sonnet-5'].research.calls, 1)

// missing fields on a frame default to 0 rather than throwing (an unpriced or partial frame)
addUsage(days, 'chat', 'x', {}, '2026-08-26')
assert.deepEqual(days['2026-08-26'].x.chat, { calls: 1, input: 0, output: 0, cacheRead: 0, cacheWrite: 0, usd: 0, unpriced: 0 })

// a single generation's unpriced is a boolean; a true frame counts as one unpriced call
addUsage(days, 'chat', 'x', { input: 5, output: 5, usd: 0.5, unpriced: true }, '2026-08-26')
assert.equal(days['2026-08-26'].x.chat.unpriced, 1, 'a boolean unpriced frame counts as one')

// foldUsage carries an already-aggregated row's own call count, unlike addUsage's fixed +1
foldUsage(days, 'research', 'claude-sonnet-5', { calls: 7, input: 5000, output: 2000, cache_read: 0, cache_write: 0, usd: 0.05, unpriced: 2 }, '2026-08-27')
assert.equal(days['2026-08-27']['claude-sonnet-5'].research.calls, 7, 'the fold carries the row\'s own call count')
assert.equal(days['2026-08-27']['claude-sonnet-5'].research.unpriced, 2, 'the fold carries the row\'s own unpriced count, not a boolean')
foldUsage(days, 'research', 'claude-sonnet-5', { calls: 3, input: 100, output: 100, usd: 0.001 }, '2026-08-27')
assert.equal(days['2026-08-27']['claude-sonnet-5'].research.calls, 10, 'a second fold adds to the first')

// addConvoUsage: a flat running total on the object itself, lazily created
const convo = {}
addConvoUsage(convo, { input: 10, output: 5, usd: 0.001 })
addConvoUsage(convo, { input: 20, output: 0, cache_read: 100, usd: 0.0002 })
assert.equal(convo.usage.calls, 2)
assert.equal(convo.usage.input, 30)
assert.equal(convo.usage.cacheRead, 100)
addConvoUsage(convo, null) // a missing/unpriced usage frame is a no-op, not a crash
assert.equal(convo.usage.calls, 2, 'a null usage frame does not count as a call')

// The stateful layer: replaceUsage/usageDays operate on in-memory state directly.
// initUsage() itself is not called here: it awaits idb-keyval's get(), which needs a real
// IndexedDB and would throw in plain Node, the same reason store.js never calls initStore() here.
replaceUsage({ '2026-08-20': { m: { chat: { calls: 1, input: 1, output: 1, cacheRead: 0, cacheWrite: 0, usd: 1, unpriced: 0 } } } })
assert.deepEqual(usageDays(), { '2026-08-20': { m: { chat: { calls: 1, input: 1, output: 1, cacheRead: 0, cacheWrite: 0, usd: 1, unpriced: 0 } } } })
replaceUsage(null) // a malformed or absent ledger resets to empty rather than throwing
assert.deepEqual(usageDays(), {})
replaceUsage([1, 2, 3]) // an array is not a days object either
assert.deepEqual(usageDays(), {})

console.log('usage selfcheck OK')
