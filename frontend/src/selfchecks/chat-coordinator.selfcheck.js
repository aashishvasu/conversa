// Run: node src/selfchecks/chat-coordinator.selfcheck.js.
import 'fake-indexeddb/auto'
import assert from 'node:assert'
import { ref } from 'vue'
import { cancelTurn, CHECKPOINT_MS, startTurn, syncPendingTurns, turnState } from '../chat/coordinator.js'
import { useAutoScroll } from '../composables/useAutoScroll.js'
import { state } from '../state/persistence.js'
import { db } from '../state/db.js'

let token = 'token'
globalThis.localStorage = { getItem: () => token, removeItem: () => { token = '' } }
Object.defineProperty(globalThis, 'navigator', { value: {}, configurable: true })

const frames = (events) => events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')
const tick = (ms = 50) => new Promise((resolve) => setTimeout(resolve, ms))
const model = 'test-model'

// A stream the test drives by hand; a given signal tears the read down the way a real fetch abort does.
function manualStream(signal) {
  let sink
  const encoder = new TextEncoder()
  const body = new ReadableStream({
    start(controller) {
      sink = controller
      signal?.addEventListener('abort', () => controller.error(new Error('aborted')), { once: true })
    },
  })
  return {
    response: new Response(body),
    send: (events) => sink.enqueue(encoder.encode(frames(events))),
    close: () => sink.close(),
  }
}

function servedStream() {
  let stream
  globalThis.fetch = async (_url, options = {}) => {
    stream = manualStream(options.signal)
    return stream.response
  }
  return () => stream
}

function pushConvo(id, messageId) {
  state.conversations.push({ id, title: 'named', messages: [{ id: messageId, role: 'assistant', content: '', turnId: `turn-${id}`, createdAt: Date.now() }] })
  const convo = state.conversations.at(-1)
  return { convo, message: convo.messages.at(-1) }
}

{
  // The whole reply arrives faster than the display-rate drain fires, so it is still buffered when the read resolves.
  const TAIL = 'tail-sentinel-77'
  let calls = 0
  globalThis.fetch = async () => {
    calls++
    return new Response(frames([{ text: 'body ' }, { text: TAIL }, { done: true }]))
  }
  const { convo, message } = pushConvo('c-drain', 'm-drain')
  await startTurn(convo, message, {}, { use_memory: false })
  assert.equal(calls, 1, 'a fully buffered stream settles without a reconnect')
  assert.equal(message.content, `body ${TAIL}`, 'the buffered tail settles instead of stranding in the buffer')
  assert.ok(!Object.hasOwn(message, 'turnId'), 'the drained turn settles')
}

{
  const first = 'first-'
  const last = 'last'
  globalThis.fetch = async (_url, options = {}) => {
    if (options.method === 'POST') return new Response(frames([{ text: first }]))
    return new Response(frames([{ text: first }, { text: last }, { usage: { model, input: 4 } }, { done: true }, { live: true }]))
  }
  const { convo, message } = pushConvo('c', 'm')
  await startTurn(convo, message, {}, { use_memory: false })
  assert.equal(message.content, first + last, 'replay replaces the partial draft rather than duplicating it')
  assert.ok(!Object.hasOwn(message, 'turnId'), 'a completed replay settles the message')
  assert.equal(convo.usage.calls, 1, 'a completed replay applies usage once')
}

{
  const SENTINEL = 'sentinel-live-42'
  const served = servedStream()
  const writes = []
  let stored = ''
  const raw = { id: 'm-live', role: 'assistant', turnId: 'turn-live', createdAt: Date.now() }
  Object.defineProperty(raw, 'content', {
    enumerable: true,
    configurable: true,
    get() { return stored },
    set(value) { stored = value; writes.push(value) },
  })
  state.conversations.push({ id: 'c-live', title: 'named', messages: [raw] })
  const convo = state.conversations.at(-1)
  const message = convo.messages.at(-1)

  const quiet = console.warn // useAutoScroll registers onMounted, which warns outside a component
  console.warn = () => {}
  let scroll
  try {
    scroll = useAutoScroll(ref(convo))
  } finally {
    console.warn = quiet
  }
  scroll.scroller.value = { scrollTop: 0, scrollHeight: 900, clientHeight: 100 }

  const turn = startTurn(convo, message, {}, { use_memory: false })
  await tick()
  served().send([{ text: 'leading ' }, { text: SENTINEL }])
  await tick()
  assert.deepEqual(writes, [], 'streaming frames write nothing to the stored message')
  assert.ok(turnState('m-live').content?.includes(SENTINEL), 'the sentinel lands in the live turn state')
  assert.equal(scroll.scroller.value.scrollTop, 900, 'autoscroll follows the live content')
  served().send([{ usage: { model, input: 2 } }, { done: true }])
  served().close()
  await turn
  assert.equal(writes.length, 1, 'settling is the only stored write of the turn')
  assert.ok(writes[0].includes(SENTINEL), 'the single stored write carries the streamed sentinel')
  assert.equal(message.content, `leading ${SENTINEL}`, 'the settled message holds the full text')
  assert.equal(turnState('m-live').content, null, 'settling hands the bubble back to the stored message')
}

{
  const PARTIAL = 'checkpoint-sentinel-9'
  const served = servedStream()
  const { convo, message } = pushConvo('c-check', 'm-check')
  const turn = startTurn(convo, message, {}, { use_memory: false })
  await tick()
  served().send([{ text: PARTIAL }])
  await tick(CHECKPOINT_MS + 300)
  assert.equal(message.content, PARTIAL, 'the checkpoint copies the in-flight text into the stored message')
  served().send([{ text: ' tail' }, { done: true }])
  served().close()
  await turn
  assert.equal(message.content, `${PARTIAL} tail`, 'settle completes what the checkpoint started')
}

{
  const KEPT = 'kept-sentinel-5'
  globalThis.fetch = async (_url, options = {}) => {
    if (options.method === 'POST') return new Response(frames([{ text: KEPT }]))
    return new Response(JSON.stringify({ detail: { code: 'no_such_turn', message: 'no such turn' } }), { status: 404, headers: { 'Content-Type': 'application/json' } })
  }
  const { convo, message } = pushConvo('c-gone', 'm-gone')
  await startTurn(convo, message, {}, { use_memory: false })
  assert.ok(!Object.hasOwn(message, 'turnId'), 'a 404 reattach settles the turn')
  assert.equal(message.content, KEPT, 'the gone settle keeps text that only ever lived in view state')
}

{
  // A summary conversation has no in-memory messages and its pending turn lives only as a stored row; index discovery must load the conversation before the turn can reattach, and a 404 with the turn still in storage settles as gone.
  const STORED = 'genuine-gone-sentinel-11'
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: { code: 'no_such_turn', message: 'no such turn' } }), { status: 404, headers: { 'Content-Type': 'application/json' } })
  state.conversations.push({ id: 'c-gone2', title: 'named', messageIds: ['m-gone2'], createdAt: Date.now() })
  const convo = state.conversations.at(-1)
  await db.messages.put({ id: 'm-gone2', convoId: 'c-gone2', role: 'assistant', content: STORED, turnId: 'turn-c-gone2', createdAt: Date.now() })
  await syncPendingTurns()
  assert.ok(convo.messages, 'the pending turn loads its summary conversation before reattaching')
  const message = convo.messages.find((m) => m.id === 'm-gone2')
  assert.ok(message, 'the reattached message comes from the stored rows')
  assert.ok(!Object.hasOwn(message, 'turnId'), 'a 404 with the turn still in storage settles as gone')
  assert.equal(message.content, STORED, 'the genuine gone settle keeps the checkpointed partial text')
}

{
  const PARTIAL = 'cancel-sentinel-3'
  const served = servedStream()
  const { convo, message } = pushConvo('c-stop', 'm-stop')
  const turn = startTurn(convo, message, {}, { use_memory: false })
  await tick()
  served().send([{ text: PARTIAL }])
  await tick()
  await cancelTurn(convo, message)
  assert.equal(message.content, PARTIAL, 'cancel keeps text that only ever lived in view state')
  assert.ok(!Object.hasOwn(message, 'turnId'), 'cancel releases the turn')
  await turn
}

console.log('chat-coordinator selfcheck ok')
