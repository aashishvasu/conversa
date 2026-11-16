// Run: node src/selfchecks/research-persistence.selfcheck.js.
import 'fake-indexeddb/auto'
import assert from 'node:assert'
import { CHECKPOINT_MS } from '../chat/coordinator.js'
import { stopRun, syncActiveRuns, tailRun } from '../research/coordinator.js'
import { persistNow, state } from '../state/persistence.js'
import { initStore } from '../state/store.js'

// Stands in for the browser document and window event target before initStore, so the teardown flush and, on the first tail, the coordinator's drain listeners register against something the test can dispatch real events to, in production registration order.
const fakeDocument = new EventTarget()
fakeDocument.visibilityState = 'visible'
fakeDocument.documentElement = {}
globalThis.document = fakeDocument
const globalEvents = new EventTarget()
globalThis.addEventListener = globalEvents.addEventListener.bind(globalEvents)
globalThis.dispatchEvent = globalEvents.dispatchEvent.bind(globalEvents)
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }

await initStore()

let storedWrites = 0
let failWrites = false
let lastRunsPut = null
let lastDocsPut = null
const realPut = globalThis.IDBObjectStore.prototype.put
globalThis.IDBObjectStore.prototype.put = function (...args) {
  if (failWrites) throw new Error('sentinel: write refused')
  storedWrites++
  if (Array.isArray(args[0]) && args[0].some((entry) => entry && typeof entry === 'object' && 'serverId' in entry)) lastRunsPut = args[0]
  if (Array.isArray(args[0]) && args[0].some((entry) => entry && typeof entry === 'object' && typeof entry.text === 'string' && typeof entry.name === 'string')) lastDocsPut = args[0]
  return realPut.apply(this, args)
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 20))

// A stream the test drives by hand; an abort tears the read down the way a real fetch abort does.
function liveStream() {
  let sink
  const encoder = new TextEncoder()
  globalThis.fetch = async (url, options = {}) => {
    if (String(url).includes('/stream')) {
      return new Response(new ReadableStream({
        start(controller) {
          sink = controller
          options.signal?.addEventListener('abort', () => controller.error(new Error('aborted')), { once: true })
        },
      }))
    }
    return new Response('{}', { status: 200 })
  }
  return {
    send(events) {
      sink.enqueue(encoder.encode(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')))
    },
  }
}

function sseResponse(frames) {
  return new Response(frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join(''), { status: 200 })
}

function tailFixture(id) {
  state.runs.push({ id, serverId: `${id}-server`, convoId: `${id}-convo`, status: 'running', phase: '', events: [], spend: null, checkpoint: null, spendLedgered: true, input: {}, settings: {} })
  return state.runs.find((r) => r.id === id)
}

// --- A burst of events persists at checkpoint cadence, not per event ---
const EVENT_COUNT = 60
const THROTTLE_SENTINEL = 'sentinel-throttle-42'
const live = tailFixture('throttle-run')
storedWrites = 0
assert.equal(await persistNow(), true, 'a dirty run saves against working storage')
assert.ok(storedWrites > 0, 'the successful save reached storage')
storedWrites = 0

const stream = liveStream()
const tail = tailRun(live)
await flush()
stream.send(Array.from({ length: EVENT_COUNT }, (_, i) => ({ seq: i + 1, kind: 'note', text: i === EVENT_COUNT - 1 ? THROTTLE_SENTINEL : `note-${i}` })))
await flush()
assert.equal(live.events.length, 0, 'events applied between checkpoints stay out of the watched record')
assert.equal(storedWrites, 0, 'events applied between checkpoints trigger no write')
await new Promise((resolve) => setTimeout(resolve, CHECKPOINT_MS + 900))
assert.ok(live.events.some((event) => event.text === THROTTLE_SENTINEL), 'the checkpoint drain copies the buffered events into the run')
assert.ok(storedWrites > 0, 'the checkpoint drain reached storage')
assert.ok(storedWrites * 4 < EVENT_COUNT, 'a burst of events writes far fewer times than there are events')

// --- A terminal write drains eagerly what the throttle still held ---
const LATE_SENTINEL = 'sentinel-late-43'
stream.send([{ seq: EVENT_COUNT + 1, kind: 'note', text: LATE_SENTINEL }])
await flush()
storedWrites = 0
lastRunsPut = null
await stopRun(live)
const storedAtCancel = lastRunsPut?.find((entry) => entry.id === 'throttle-run')
assert.ok(storedAtCancel?.events.some((event) => event.text === LATE_SENTINEL), 'the cancelled run is stored complete, with the events the throttle had not yet written')
await tail
assert.equal(live.status, 'cancelled', 'stopping still lands the terminal state')
assert.ok(live.events.some((event) => event.text === LATE_SENTINEL), 'the terminal write drains events that never reached a checkpoint')
assert.ok(storedWrites > 0, 'the terminal write is eager, not held for the next checkpoint')

await initStore()
const reloaded = state.runs.find((r) => r.id === 'throttle-run')
assert.ok(reloaded?.events.some((event) => event.text === THROTTLE_SENTINEL), 'throttled events reach storage and survive a reload')
assert.ok(reloaded?.events.some((event) => event.text === LATE_SENTINEL), 'the terminally drained event survives a reload')
assert.equal(reloaded?.status, 'cancelled', 'the terminal status survives a reload')

// --- A final frame persists eagerly and the backend run is only forgotten after the save ---
const FINAL_SENTINEL = 'sentinel-final-44'
const ackUrls = []
let savedRunAtAck = null
let savedDocsAtAck = null
globalThis.fetch = async (url) => {
  const href = String(url)
  if (href.includes('/stream')) {
    return sseResponse([
      { seq: 1, kind: 'wave', wave: 1 },
      { seq: 2, kind: 'note', text: FINAL_SENTINEL },
      { kind: 'final', status: 'done', phase: 'done', spend: { calls: 2, models: {} }, payload: { name: 'Sentinel', summary: 'sentinel summary', report: { text: 'sentinel report body' } } },
    ])
  }
  if (href.includes('/ack')) {
    ackUrls.push(href)
    if (href.includes('/final-run-server/ack')) {
      savedRunAtAck = lastRunsPut?.find((entry) => entry.id === 'final-run') ?? null
      savedDocsAtAck = lastDocsPut
    }
  }
  return new Response('{}', { status: 200 })
}

const finalLive = tailFixture('final-run')
await persistNow()
lastRunsPut = null
lastDocsPut = null
await tailRun(finalLive)
assert.equal(finalLive.ackPending, undefined, 'a final frame whose save succeeded clears the pending marker')
assert.ok(savedRunAtAck?.events.some((event) => event.text === FINAL_SENTINEL), 'the run is stored complete before the backend run is acknowledged')
assert.ok(savedDocsAtAck?.some((doc) => doc.text.includes('sentinel report body')), 'the report document is stored before the backend run is acknowledged')

const refusedLive = tailFixture('refused-run')
await persistNow()
ackUrls.length = 0
failWrites = true
await tailRun(refusedLive)
assert.equal(refusedLive.ackPending, true, 'a refused terminal save keeps the run recoverable')
assert.equal(ackUrls.length, 0, 'the backend run is not forgotten before its report is saved')

failWrites = false
syncActiveRuns([refusedLive])
await flush()
assert.equal(refusedLive.ackPending, undefined, 'the next sync retries the ack once the save succeeds')
assert.ok(ackUrls.some((call) => call.includes('/refused-run-server/ack')), 'the retry acknowledges the saved run')

await persistNow()
await initStore()
const reloadedFinal = state.runs.find((r) => r.id === 'final-run')
assert.ok(reloadedFinal?.events.some((event) => event.text === FINAL_SENTINEL), 'a finished run reaches storage with its drained events')
assert.equal(reloadedFinal?.status, 'done', 'the finished status survives a reload')
assert.ok(state.docs.some((doc) => doc.id === reloadedFinal?.reportDocId && doc.text.includes('sentinel report body')), 'the report document is stored alongside the run')

// --- A hidden tab or a closing page captures what the throttle still held ---
const HIDDEN_SENTINEL = 'sentinel-hidden-45'
const PAGEHIDE_SENTINEL = 'sentinel-pagehide-46'
const hiddenLive = tailFixture('hidden-run')
await persistNow()
const hiddenStream = liveStream()
const hiddenTail = tailRun(hiddenLive)
await flush()
hiddenStream.send([{ seq: 1, kind: 'note', text: HIDDEN_SENTINEL }])
await flush()
assert.equal(hiddenLive.events.length, 0, 'the buffered event waits for its checkpoint')
let writesBefore = storedWrites
fakeDocument.visibilityState = 'hidden'
fakeDocument.dispatchEvent(new Event('visibilitychange'))
await flush()
assert.ok(hiddenLive.events.some((event) => event.text === HIDDEN_SENTINEL), 'hiding the tab drains the buffer instead of waiting for the interval')
assert.ok(storedWrites > writesBefore, 'the hidden drain reaches storage')

hiddenStream.send([{ seq: 2, kind: 'note', text: PAGEHIDE_SENTINEL }])
fakeDocument.visibilityState = 'visible'
await flush()
writesBefore = storedWrites
globalThis.dispatchEvent(new Event('pagehide'))
await flush()
assert.ok(storedWrites > writesBefore, 'pagehide flushes the buffered research state')

await stopRun(hiddenLive)
await hiddenTail

console.log('research persistence selfcheck OK')
