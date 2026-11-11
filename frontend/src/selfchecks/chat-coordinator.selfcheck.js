// Run: node src/selfchecks/chat-coordinator.selfcheck.js.
import assert from 'node:assert'
import { startTurn } from '../chat/coordinator.js'
import { state } from '../state/persistence.js'

let token = 'token'
globalThis.localStorage = { getItem: () => token, removeItem: () => { token = '' } }
Object.defineProperty(globalThis, 'navigator', { value: {}, configurable: true })

const frames = (events) => events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')
const first = 'first-'
const last = 'last'
const model = 'test-model'
globalThis.fetch = async (_url, options = {}) => {
  if (options.method === 'POST') return new Response(frames([{ text: first }]))
  return new Response(frames([{ text: first }, { text: last }, { usage: { model, input: 4 } }, { done: true }, { live: true }]))
}

state.conversations.push({ id: 'c', title: 'named', messages: [{ id: 'm', content: '', turnId: 't' }] })
const convo = state.conversations[0]
const message = convo.messages[0]
await startTurn(convo, message, {}, { use_memory: false })
assert.equal(message.content, first + last, 'replay replaces the partial draft rather than duplicating it')
assert.ok(!Object.hasOwn(message, 'turnId'), 'a completed replay settles the message')
assert.equal(convo.usage.calls, 1, 'a completed replay applies usage once')

console.log('chat-coordinator selfcheck ok')
