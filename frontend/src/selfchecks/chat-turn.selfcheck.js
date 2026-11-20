// Run: node src/selfchecks/chat-turn.selfcheck.js.
import 'fake-indexeddb/auto'
import assert from 'node:assert'
import { applyFrame, newDraft, settleMessage, turnStillWanted } from '../chat/turn.js'
import { cloneWithNewIds } from '../state/conversations.js'
import { conversations, exportData, importData } from '../state/store.js'

const frames = [
  { think: 'a' }, { think: 'b' }, { text: 'Hel' }, { search: 'q' }, { think: 'c' },
  { results: [{ url: 'u' }] }, { tool: { id: 't1', name: 'calc', status: 'ok', trace: { x: 1 } } },
  { artifact: { id: 'art' } }, { text: 'lo' }, { usage: { input: 1, output: 2 } }, { done: true },
]
const play = (list, draft = newDraft()) => list.reduce(applyFrame, draft)

const whole = play(frames)
const partial = play(frames.slice(0, 4))
assert.deepEqual(play([...frames.slice(0, 4), { live: true }, ...frames.slice(4)]), whole, 'replay with a live marker equals one uninterrupted pass')
assert.deepEqual(play(frames), whole, 'a fresh draft replaying the whole sequence equals the first pass')
assert.equal(whole.content, 'Hello', 'text frames append in order')
assert.equal(whole.outcome, 'completed', 'done frame settles the draft completed')
assert.deepEqual(whole.usage, frames.find((f) => f.usage).usage, 'usage frame sets usage')
assert.deepEqual(whole.artifacts, [frames.find((f) => f.artifact).artifact], 'artifact frame appends')
assert.equal(play([{ error: 'E' }]).error.message, 'E', 'error frame sets the public error message')

const thinking = whole.trace.filter((e) => e.type === 'thinking')
assert.equal(thinking.length, 2, 'adjacent think frames join; a think after another type starts a new entry')
assert.ok(thinking[0].text.includes('a') && thinking[0].text.includes('b'), 'joined entry carries both chunks')
assert.ok(!thinking[0].text.includes('c'), 'think after search starts its own entry')
const links = whole.trace.find((e) => e.type === 'results')?.links
assert.deepEqual(links, frames.find((f) => f.results).results, 'results entry carries the links')
const tool = whole.trace.find((e) => e.type === 'tool')
assert.equal(tool.id, 't1', 'tool entry keeps its id')
assert.ok(tool.text.includes('calc') && tool.text.includes('ok') && tool.text.includes('"x"'), 'tool entry renders name, status, and trace')

const done = { id: 'm', content: '', turnId: 'T' }
settleMessage(done, whole, 'done')
assert.equal(done.content, whole.content, 'done writes the draft content')
assert.deepEqual(done.artifacts, whole.artifacts, 'done writes the draft artifacts')
assert.ok(!Object.hasOwn(done, 'turnId'), 'done releases the turn')

for (const outcome of ['stopped', 'gone']) {
  const m = { id: 'm', content: '', turnId: 'T' }
  settleMessage(m, partial, outcome)
  assert.equal(m.content, partial.content, `${outcome} keeps partial content`)
  assert.ok(!Object.hasOwn(m, 'turnId'), `${outcome} releases the turn`)
}

const SENTINEL = 'sentinel-error-7f3'
const failed = play([{ text: 'partial-text' }, { error: SENTINEL }])
const em = { id: 'm', content: '', turnId: 'T' }
settleMessage(em, failed, 'error')
assert.equal(em.content, 'partial-text', 'the failure never enters the assistant body')
assert.equal(em.generation.status, 'failed', 'the failure is recorded as generation status')
assert.equal(em.generation.error.message, SENTINEL, 'the public error message is retained off-body')
assert.ok(!Object.hasOwn(em, 'turnId'), 'error releases the turn')

// The decoder accepts the legacy string and the additive object/sibling shapes without throwing.
const objDraft = play([{ error: { code: 'rate_limited', message: 'SENTINEL-OBJ', retryable: true } }])
assert.equal(objDraft.outcome, 'failed', 'an object error settles the draft as failed')
assert.equal(objDraft.error.code, 'rate_limited', 'object error keeps its code')
assert.equal(objDraft.error.retryable, true, 'object error keeps retryable')
const sibDraft = play([{ error: 'SENTINEL-SIB', code: 'overloaded', retryable: true }])
assert.equal(sibDraft.error.code, 'overloaded', 'additive sibling code is read')
assert.equal(sibDraft.error.message, 'SENTINEL-SIB', 'the string error remains the message')
assert.equal(sibDraft.error.retryable, true, 'additive sibling retryable is read')

// Terminal categories stay distinct: output limit is a completed partial, stop is not a failure.
const capDraft = play([{ text: 'cut' }, { done: true, finishReason: 'output_limit' }])
assert.equal(capDraft.outcome, 'output_limit', 'output limit is its own terminal')
const capMsg = { id: 'm4', role: 'assistant', content: '', turnId: 't4' }
settleMessage(capMsg, capDraft, 'done')
assert.equal(capMsg.generation.status, 'output_limit', 'output limit is not a generic failure')
assert.equal(capMsg.generation.error, null, 'output limit carries no error')
const stopMsg = { id: 'm5', role: 'assistant', content: 'kept', turnId: 't5' }
settleMessage(stopMsg, play([{ text: 'kept' }]), 'stopped')
assert.equal(stopMsg.generation.status, 'stopped', 'user stop is not a provider failure')
assert.equal(stopMsg.generation.error, null, 'user stop carries no error')
assert.equal(stopMsg.content, 'kept', 'stop keeps the partial text')

const pending = { id: 'pc', title: 'P', messages: [{ id: 'pm', role: 'assistant', content: 'x', turnId: 'T', generation: { status: 'failed', error: { code: 'x', message: 'SENTINEL-GEN', retryable: false }, finishReason: null } }] }
const copy = cloneWithNewIds(pending)
assert.ok(copy.messages.length && copy.messages.every((m) => !Object.hasOwn(m, 'turnId')), 'a conversation copy carries no pending turn identity')
assert.equal(pending.messages[0].turnId, 'T', 'copying leaves the original turn in place')

await (await import('../state/store.js')).initStore()
await importData([pending])
const exportSlot = conversations.value.find((c) => c.id === 'pc').messages[0]
Object.assign(exportSlot, {
  generation: { status: 'failed', error: null, finishReason: null },
})
await (await import('vue')).nextTick()
await (await import('../state/store.js')).persistNow()
const { db: exportDb } = await import('../state/db.js')
const { plainCopy } = await import('../state/persistence.js')
const { messages: _messages, ...exportRow } = conversations.value.find((c) => c.id === 'pc')
await exportDb.conversations.put(plainCopy(exportRow))
await exportDb.messages.put({ ...plainCopy(exportSlot), convoId: 'pc' })
const exported = (await exportData()).conversations
assert.ok(exported.some((c) => c.messages.some((m) => m.id === 'pm')) && exported.every((c) => c.messages.every((m) => !Object.hasOwn(m, 'turnId'))), 'export carries the persisted message without its turnId')
assert.equal(conversations.value.find((c) => c.id === 'pc').messages[0].turnId, 'T', 'exporting leaves the stored turn in place')
assert.ok(exported.some((c) => c.messages.some((m) => m.id === 'pm')) && exported.every((c) => c.messages.every((m) => !Object.hasOwn(m, 'generation'))), 'export carries no local generation state')
assert.ok(copy.messages.every((m) => !Object.hasOwn(m, 'generation')), 'a conversation copy carries no local generation state')
const foreign = { id: 'pf', title: 'F', messages: [{ id: 'fm', role: 'assistant', content: 'y', generation: { status: 'failed', error: null, finishReason: null } }] }
await importData([foreign])
assert.ok(!Object.hasOwn(conversations.value.find((c) => c.id === 'pf').messages[0], 'generation'), 'import strips local generation state')

const convo = { id: 'c', messages: [{ id: 'm', turnId: 'T' }] }
const msg = convo.messages[0]
const store = [convo]
assert.ok(turnStillWanted(store, convo, msg, 'T'), 'a live turn is wanted')
assert.ok(!turnStillWanted([], convo, msg, 'T'), 'rejected when the conversation is gone')
assert.ok(!turnStillWanted([{ ...convo, messages: [] }], convo, msg, 'T'), 'rejected when the conversation is a different object')
const emptied = { id: 'c', messages: [] }
assert.ok(!turnStillWanted([emptied], emptied, msg, 'T'), 'rejected when the message is gone')
assert.ok(!turnStillWanted(store, convo, { ...msg }, 'T'), 'rejected when the message is a different object')
assert.ok(!turnStillWanted(store, convo, msg, 'U'), 'rejected when the message carries a different turnId')

;(await import('../state/persistence.js')).setLoaded(false)
console.log('chat-turn selfcheck ok')
