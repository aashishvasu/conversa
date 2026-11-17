// Run: node src/selfchecks/usage.selfcheck.js.
import assert from 'node:assert'
import 'fake-indexeddb/auto'
import { nextTick } from 'vue'
import { db } from '../state/db.js'
import { persistNow } from '../state/persistence.js'
import { createConversation, createRun, finishRun, initStore } from '../state/store.js'
import { notifications } from '../utils/notify.js'
import { addConvoUsage, addUsage, foldUsage, recordUsage, replaceUsage, usageDays, usageRows } from '../state/usage.js'

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

const aggregatedDays = {}
addUsage(aggregatedDays, 'chat', 'batched-model', { calls: 3, input: 60, output: 30, usd: 0.003 }, '2026-08-25')
assert.equal(aggregatedDays['2026-08-25']['batched-model'].chat.calls, 3, 'an aggregated frame carries its call count into the daily ledger')

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

const rangeRows = usageRows(days, '2026-08-24', '2026-08-25')
assert.deepEqual(rangeRows.map(({ model, kind, calls }) => [model, kind, calls]), [
  ['claude-haiku-4-5', 'utility', 1],
  ['claude-sonnet-5', 'chat', 2],
  ['claude-sonnet-5', 'research', 1],
], 'range rows combine matching days and sort model then kind')
assert.equal(rangeRows.find((row) => row.kind === 'chat').cacheRead, 500, 'stored camel-case cache fields survive row aggregation')
const allRows = usageRows(days)
assert.equal(allRows.length, 4, 'empty bounds include every day while combining matching model/kind rows')
assert.equal(allRows.find((row) => row.model === 'claude-sonnet-5' && row.kind === 'research').calls, 11, 'all-time rows combine the same model and kind across days')
assert.deepEqual(usageRows({ bad: null, nested: { model: null } }), [], 'malformed restored buckets are ignored')

// addConvoUsage: a flat running total on the object itself, lazily created
const convo = {}
addConvoUsage(convo, { input: 10, output: 5, usd: 0.001 })
addConvoUsage(convo, { input: 20, output: 0, cache_read: 100, usd: 0.0002 })
assert.equal(convo.usage.calls, 2)
assert.equal(convo.usage.input, 30)
assert.equal(convo.usage.cacheRead, 100)
addConvoUsage(convo, { calls: 3, input: 30, output: 15, usd: 0.003 })
assert.equal(convo.usage.calls, 5, 'an aggregated frame carries its call count into the conversation total')
addConvoUsage(convo, null) // a missing/unpriced usage frame is a no-op, not a crash
assert.equal(convo.usage.calls, 5, 'a null usage frame does not count as a call')

// These run over plain state before the store loads, so they never touch IndexedDB.
replaceUsage({ '2026-08-20': { m: { chat: { calls: 1, input: 1, output: 1, cacheRead: 0, cacheWrite: 0, usd: 1, unpriced: 0 } } } })
assert.deepEqual(usageDays(), { '2026-08-20': { m: { chat: { calls: 1, input: 1, output: 1, cacheRead: 0, cacheWrite: 0, usd: 1, unpriced: 0 } } } })
replaceUsage(null) // a malformed or absent ledger resets to empty rather than throwing
assert.deepEqual(usageDays(), {})
replaceUsage([1, 2, 3]) // an array is not a days object either
assert.deepEqual(usageDays(), {})

// --- Rows are the persisted form: the ledger joins the flush, merges into existing rows, and fails loudly ---
// A clean database: the in-memory asserts above already ran over plain state, and initStore rebuilds days from rows.
await initStore()
const day = new Date().toISOString().slice(0, 10)
// A row already committed (another tab's spend) is added to, not clobbered, by the deltas.
await db.usage.put({ day, model: 'row-model', kind: 'chat', calls: 5, input: 500, output: 100, cacheRead: 0, cacheWrite: 0, usd: 0.05, unpriced: 0 })
recordUsage('chat', { model: 'row-model', input: 100, output: 25, cache_read: 7, usd: 0.011 })
recordUsage('chat', { model: 'row-model', input: 1, output: 1, usd: 0.001 })
await nextTick()
assert.equal(await persistNow(), true, 'a flush with pending usage rows succeeds')
let storedRow = await db.usage.get([day, 'row-model', 'chat'])
assert.equal(storedRow.calls, 7, 'two usage writers add up instead of one clobbering the other')
assert.equal(storedRow.input, 601)
assert.equal(storedRow.cacheRead, 7)
assert.equal(Math.round(storedRow.usd * 1e3), 62)

// Run spend and its usage rows are one transaction: a refused flush leaves neither, and the failure surfaces.
const rc = createConversation()
rc.mode = 'research'
const prompt = { id: 'u-rp', role: 'user', content: 'find', mode: 'research' }
const holder = { id: 'u-rh', role: 'assistant', content: '', mode: 'research' }
rc.messages.push(prompt, holder)
const lr = createRun(rc, 'u-rp', 'u-rh', { system: 'S', messages: [] }, { action: 'research', goal: 'G', questions: [] }, { research_depth: 4 })
prompt.runId = holder.runId = lr.id
const frame = { status: 'done', phase: 'done', payload: { name: 'R', summary: 'S', report: { text: 'B' } }, spend: { models: { 'atomic-model': { calls: 1, input: 11, output: 12, cache_read: 0, cache_write: 0, usd: 0.02, unpriced: 0 } } } }
finishRun(lr, frame)
await nextTick()
assert.equal(await persistNow(), true, 'run row and its spend rows commit in one flush')
assert.equal((await db.runs.get(lr.id)).status, 'done', 'the run row lands with the fold')
assert.equal((await db.usage.get([day, 'atomic-model', 'research'])).calls, 1, 'the spend fold lands with the run row')

const rc2 = createConversation()
rc2.mode = 'research'
const prompt2 = { id: 'u-rp2', role: 'user', content: 'find2', mode: 'research' }
const holder2 = { id: 'u-rh2', role: 'assistant', content: '', mode: 'research' }
rc2.messages.push(prompt2, holder2)
const lr2 = createRun(rc2, 'u-rp2', 'u-rh2', { system: 'S', messages: [] }, { action: 'research', goal: 'G', questions: [] }, { research_depth: 4 })
prompt2.runId = holder2.runId = lr2.id
const frame2 = { status: 'done', phase: 'done', payload: { name: 'R2', summary: 'S2', report: { text: 'B2' } }, spend: { models: { 'atomic-model2': { calls: 1, input: 21, output: 22, cache_read: 0, cache_write: 0, usd: 0.03, unpriced: 0 } } } }
finishRun(lr2, frame2)
// An uncloneable function in the run row makes the flush fail loudly, as a poisoned write boundary does.
lr2.__poison = () => {}
await nextTick()
assert.equal(await persistNow(), false, 'a refused flush reports failure')
assert.ok(notifications.value.some((n) => n.key === 'storage'), 'a refused usage write surfaces the storage banner instead of being swallowed')
assert.equal(await db.usage.get([day, 'atomic-model2', 'research']), undefined, 'run spend and its usage rows commit together or not at all')
assert.equal(await db.runs.get(lr2.id), undefined, 'the refused flush left no run row either')
delete lr2.__poison
await nextTick()
assert.equal(await persistNow(), true, 'the retried flush succeeds once the poison is gone')
assert.equal((await db.runs.get(lr2.id)).status, 'done', 'the run row lands after the retry')
assert.equal((await db.usage.get([day, 'atomic-model2', 'research'])).calls, 1, 'the spend fold lands with the retry')

console.log('usage selfcheck OK')
