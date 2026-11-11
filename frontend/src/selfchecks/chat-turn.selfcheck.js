// Run: node src/selfchecks/chat-turn.selfcheck.js.
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
assert.ok(whole.done, 'done frame marks the draft done')
assert.deepEqual(whole.usage, frames.find((f) => f.usage).usage, 'usage frame sets usage')
assert.deepEqual(whole.artifacts, [frames.find((f) => f.artifact).artifact], 'artifact frame appends')
assert.equal(play([{ error: 'E' }]).error, 'E', 'error frame sets error')

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
assert.ok(em.content.startsWith('partial-text'), 'error keeps the partial content first')
assert.ok(em.content.indexOf(SENTINEL) > 'partial-text'.length, 'error lands after the partial content')
assert.ok(!Object.hasOwn(em, 'turnId'), 'error releases the turn')

const pending = { id: 'pc', title: 'P', messages: [{ id: 'pm', role: 'assistant', content: 'x', turnId: 'T' }] }
const copy = cloneWithNewIds(pending)
assert.ok(copy.messages.length && copy.messages.every((m) => !Object.hasOwn(m, 'turnId')), 'a conversation copy carries no turnId')
assert.equal(pending.messages[0].turnId, 'T', 'copying leaves the original turn in place')

await importData([pending])
const exported = exportData().conversations
assert.ok(exported.every((c) => c.messages.every((m) => !Object.hasOwn(m, 'turnId'))), 'export carries no turnId')
assert.equal(conversations.value.find((c) => c.id === 'pc').messages[0].turnId, 'T', 'exporting leaves the stored turn in place')

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

console.log('chat-turn selfcheck ok')
