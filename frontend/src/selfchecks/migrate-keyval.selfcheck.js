// Run: node src/selfchecks/migrate-keyval.selfcheck.js.

import 'fake-indexeddb/auto'
import assert from 'node:assert'
import { db, SCHEMA_VERSION } from '../state/db.js'
import { migrateFromKeyval } from '../state/migrate-keyval.js'

const KEYVAL_DB = 'keyval-store'
const KEYVAL_STORE = 'keyval'
const transactionDone = (tx) => new Promise((resolve, reject) => {
  tx.oncomplete = () => resolve()
  tx.onerror = () => reject(tx.error)
  tx.onabort = () => reject(tx.error)
})

const deleteDatabase = (name) => new Promise((resolve) => {
  const request = indexedDB.deleteDatabase(name)
  request.onsuccess = () => resolve()
  request.onerror = () => resolve()
  request.onblocked = () => resolve()
})

async function seedKeyval(records) {
  await deleteDatabase(KEYVAL_DB)
  const connection = await new Promise((resolve, reject) => {
    const request = indexedDB.open(KEYVAL_DB)
    request.onupgradeneeded = (event) => event.target.result.createObjectStore(KEYVAL_STORE)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
  const tx = connection.transaction(KEYVAL_STORE, 'readwrite')
  const store = tx.objectStore(KEYVAL_STORE)
  for (const [key, value] of records) store.put(value, key)
  await transactionDone(tx)
  connection.close()
}

const keyvalExists = async () => (await indexedDB.databases()).some((entry) => entry.name === KEYVAL_DB)

async function reset() {
  await db.open()
  await Promise.all(db.tables.map((table) => table.clear()))
  await deleteDatabase(KEYVAL_DB)
}

const fullArchive = () => [
  ['conversa_order', ['convo-a']],
  ['conversa_convo:convo-a', {
    id: 'convo-a',
    title: 'sentinel-title-harbor',
    mode: 'chat',
    createdAt: 1000,
    updatedAt: 2000,
    workspaceId: 'w-1',
    settings: { temperature: 0.4 },
    docIds: ['doc-base'],
    messages: [
      { id: 'm-seeded', role: 'user', content: 'sentinel-content-lantern', imageIds: ['img-ok'], turnId: 't1' },
      { role: 'assistant', content: 'sentinel-content-beacon', turnId: 't1', createdAt: 3000 },
    ],
  }],
  ['conversa_workspaces', [
    { id: 'w-1', name: 'sentinel-workspace-quay', systemPrompt: 'sentinel-system-prompt-rune', docs: [{ id: 'doc-inline', name: 'sentinel-doc-inline-name', text: 'inline text' }] },
  ]],
  ['conversa_docs', [{ id: 'doc-base', name: 'sentinel-doc-base-name', text: 'base text', createdAt: 1, updatedAt: 2, versions: [] }]],
  ['conversa_img:img-ok', { id: 'img-ok', data: 'aGk=', media_type: 'image/png' }],
  ['conversa_img:img-bad', { id: 'img-bad', data: 'aGk=', media_type: 'image/svg+xml' }],
  ['conversa_runs', [
    { id: 'run-1', convoId: 'convo-a', input: 'sentinel-run-input', prepared: { brief: { objective: 'sentinel-objective' } }, settings: { model: 'sentinel-run-model' }, events: [{ seq: 1, kind: 'wave' }, { seq: 2, kind: 'note', text: 'sentinel-event-text' }], createdAt: 5 },
    { id: 'run-bad', input: 'x', prepared: { brief: {} }, settings: {}, events: [] },
  ]],
  ['conversa_global', { model: 'sentinel-global-model', promptCache: true }],
  ['conversa_usage', {
    '2024-06-01': {
      'model-x': {
        chat: { calls: 2, input: 10, output: 5, cacheRead: 1, cacheWrite: 0, usd: 0.01, unpriced: 0 },
        research: { calls: 1, input: 7, output: 3, cacheRead: 0, cacheWrite: 0, usd: 0.02, unpriced: 0 },
      },
    },
    '2024-06-02': {
      'model-y': { chat: { calls: 4, input: 20, output: 9, cacheRead: 2, cacheWrite: 1, usd: 0.04, unpriced: 1 } },
    },
  }],
  ['conversa_models', [{ id: 'cached-model' }]],
  ['conversa_conversations', [{ id: 'legacy-only', title: 'legacy', messages: [] }]],
]

// Happy path: one full migration from a seeded old database.
await reset()
await seedKeyval(fullArchive())
const first = await migrateFromKeyval()
assert.equal(first.migrated, true, 'first migration reports migrated')
assert.deepEqual(first.counts, { conversations: 1, messages: 2, workspaces: 1, docs: 2, images: 1, runs: 1, runEvents: 2, usage: 3 }, 'counts reflect the migrated rows')

const convoRow = await db.conversations.get('convo-a')
assert.equal(convoRow.title, 'sentinel-title-harbor', 'conversation title reaches its row')
assert.equal(convoRow.updatedAt, 3000, 'conversation updatedAt is computed from its last message')
assert.equal('messages' in convoRow, false, 'conversation row no longer carries messages')
assert.equal(convoRow.settings.temperature, 0.4, 'conversation settings ride along on the row')

const messageRows = await db.messages.toArray()
assert.equal(messageRows.length, 2, 'messages table holds one row per seeded message')
assert.ok(messageRows.every((m) => m.convoId === 'convo-a'), 'every message row names its conversation')
assert.equal(convoRow.messageIds.length, messageRows.length, 'messageIds length equals message rows')
assert.ok(messageRows.every((m) => convoRow.messageIds.includes(m.id)), 'every message id appears in its conversation messageIds')
const seededMessage = messageRows.find((m) => m.id === 'm-seeded')
assert.equal(seededMessage.content, 'sentinel-content-lantern', 'seeded message content reaches its row')
const backfilled = messageRows.find((m) => m.id !== 'm-seeded')
assert.ok(backfilled.id, 'message seeded without an id gains one')
assert.equal(backfilled.content, 'sentinel-content-beacon', 'backfilled message keeps its content')

const workspaceRow = await db.workspaces.get('w-1')
assert.equal(workspaceRow.messages[0].content, 'sentinel-system-prompt-rune', 'legacy systemPrompt string becomes a workspace prompt message')
assert.equal('systemPrompt' in workspaceRow, false, 'workspace systemPrompt key is removed')
assert.ok(workspaceRow.docIds.includes('doc-inline'), 'inline workspace doc is referenced from the workspace')
assert.equal((await db.docs.get('doc-inline')).name, 'sentinel-doc-inline-name', 'inline workspace doc is hoisted into the docs table')
assert.equal((await db.docs.get('doc-base')).name, 'sentinel-doc-base-name', 'stored doc reaches the docs table')

assert.ok(await db.images.get('img-ok'), 'valid image is migrated')
assert.equal(await db.images.get('img-bad'), undefined, 'image with an unsupported media type is dropped')

const runRow = await db.runs.get('run-1')
assert.equal(runRow.input, 'sentinel-run-input', 'run input reaches its row')
assert.equal(runRow.prepared.brief.objective, 'sentinel-objective', 'run brief objective reaches its row')
assert.ok(typeof runRow.prepared.brief.deliverable === 'string' && runRow.prepared.brief.deliverable, 'run brief gains its missing deliverable')
assert.equal('events' in runRow, false, 'run row no longer carries events')
assert.equal(await db.runs.get('run-bad'), undefined, 'run without a convoId is dropped')
const eventRows = await db.runEvents.toArray()
assert.equal(eventRows.length, 2, 'run events split into one row each')
assert.deepEqual(await db.runs.get('run-1'), runRow, 'the run its events name exists in the runs table')
assert.ok(eventRows.every((e) => e.runId === 'run-1'), 'every run event names that run')
assert.deepEqual(eventRows.map((e) => e.seq), [1, 2], 'run events keep the sequence numbers the server gave them')
assert.equal(eventRows.find((e) => e.seq === 2).text, 'sentinel-event-text', 'run event payload rides along on its row')

const usageRows = await db.usage.toArray()
assert.equal(usageRows.length, 3, 'usage ledger flattens to one row per day/model/kind')
assert.ok(usageRows.every((row) => row.day && row.model && row.kind), 'each usage row carries day, model and kind')
const chatRow = usageRows.find((row) => row.day === '2024-06-01' && row.model === 'model-x' && row.kind === 'chat')
assert.equal(chatRow.calls, 2, 'usage row keeps its call count')
const totalUsd = usageRows.reduce((sum, row) => sum + row.usd, 0)
assert.equal(Math.abs(totalUsd - 0.07) < 1e-9, true, 'flattened usage rows total the same usd as the nested ledger')
const totalUnpriced = usageRows.reduce((sum, row) => sum + row.unpriced, 0)
assert.equal(totalUnpriced, 1, 'flattened usage rows total the same unpriced count as the nested ledger')

assert.equal(await db.meta.get('order'), undefined, 'the stored order row is no longer written')
assert.equal((await db.meta.get('global')).value.model, 'sentinel-global-model', 'global settings land in meta')
assert.equal((await db.meta.get('schema')).value, SCHEMA_VERSION, 'meta.schema carries the schema version')
assert.equal(await db.meta.get('models'), undefined, 'the server-owned models cache is not migrated')
assert.equal(await db.conversations.get('legacy-only'), undefined, 'the legacy single-array layout is not migrated')
assert.equal(await keyvalExists(), false, 'old database is deleted after a successful migration')

// Idempotence: with meta.schema present, a reappearing old database is left alone.
await seedKeyval(fullArchive())
const second = await migrateFromKeyval()
assert.equal(second.migrated, false, 'already-migrated call skips')
assert.ok(await keyvalExists(), 'already-migrated call leaves the old database in place')
assert.equal((await db.messages.toArray()).length, 2, 'skip does not duplicate message rows')
await deleteDatabase(KEYVAL_DB)

// Fresh install: no old database, none created, nothing thrown.
await reset()
const fresh = await migrateFromKeyval()
assert.equal(fresh.migrated, false, 'fresh install reports no migration')
assert.deepEqual(fresh.counts, { conversations: 0, messages: 0, workspaces: 0, docs: 0, images: 0, runs: 0, runEvents: 0, usage: 0 }, 'fresh install reports empty counts')
assert.equal(await keyvalExists(), false, 'fresh install does not create keyval-store')

// The legacy single-array layout alone migrates nothing, without throwing.
await reset()
await seedKeyval([['conversa_conversations', [{ id: 'legacy-only', title: 'legacy', messages: [] }]]])
const legacy = await migrateFromKeyval()
assert.equal(await db.conversations.get('legacy-only'), undefined, 'legacy array conversation is not migrated')
assert.equal(legacy.counts.conversations, 0, 'legacy-array-only migration moves zero conversations')
assert.equal(await keyvalExists(), false, 'legacy-array-only migration still completes and clears the old database')

// Count mismatch: a duplicate message id collapses into one row, so the write aborts and the old database stays.
await reset()
await seedKeyval([
  ['conversa_order', ['convo-b']],
  ['conversa_convo:convo-b', {
    id: 'convo-b',
    title: 'duplicate-ids',
    messages: [
      { id: 'dup-m', role: 'user', content: 'first' },
      { id: 'dup-m', role: 'assistant', content: 'second' },
    ],
  }],
])
await assert.rejects(migrateFromKeyval(), /messages/, 'count mismatch aborts the migration')
assert.equal(await keyvalExists(), true, 'failed migration leaves the old database in place')
assert.equal((await db.messages.toArray()).length, 0, 'failed migration leaves no message rows behind')
assert.equal(await db.meta.get('schema'), undefined, 'failed migration writes no schema marker')

console.log('migrate-keyval.selfcheck: ok')
