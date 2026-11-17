// Run: node src/selfchecks/research-persistence.selfcheck.js.
// Run events are append-only rows in db.runEvents, so every assertion here counts or reads those rows per run instead of assuming the run row carries its events.
import 'fake-indexeddb/auto'
import assert from 'node:assert'
import { CHECKPOINT_MS } from '../chat/coordinator.js'
import { stopRun, syncActiveRuns, tailRun } from '../research/coordinator.js'
import { applyStart } from '../research/lifecycle.js'
import { persistNow, state } from '../state/persistence.js'
import { removeRun } from '../state/runs.js'
import { db } from '../state/db.js'
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

async function eventRows(runId) {
  return db.runEvents.where('runId').equals(runId).sortBy('key')
}

function tailFixture(id) {
  state.runs.push({ id, serverId: `${id}-server`, convoId: `${id}-convo`, status: 'running', phase: '', events: [], spend: null, checkpoint: null, spendLedgered: true, input: {}, settings: {} })
  return state.runs.find((r) => r.id === id)
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

// --- A stored run row carries no events array, and a drain appends only the rows that are new ---
const runA = tailFixture('seq-run')
await persistNow()
const storedRow = await db.runs.get('seq-run')
assert.ok(!Object.hasOwn(storedRow, 'events'), 'a stored run row carries no events array')

const SENTINEL_ORDER = ['ARRIVAL-A', 'ARRIVAL-B', 'ARRIVAL-C']
const SENTINEL_SEQS = [1, 2, 3]
runA.events.push(...SENTINEL_SEQS.map((seq, i) => ({ seq, kind: 'note', text: SENTINEL_ORDER[i] })))
await persistNow()
assert.equal((await eventRows('seq-run')).length, 3, 'a drain appends one runEvents row per event')
const rowsBefore = (await eventRows('seq-run')).length
runA.events.push({ seq: 4, kind: 'note', text: 'ARRIVAL-D' })
await persistNow()
const rowsAfter = (await eventRows('seq-run')).length
assert.equal(rowsAfter - rowsBefore, 1, 'a flush with one new event writes exactly one new row')
await persistNow()
assert.equal((await eventRows('seq-run')).length, rowsAfter, 'a flush with no new events appends nothing')

const back = await eventRows('seq-run')
assert.deepEqual(back.map((e) => e.seq), [...SENTINEL_SEQS, 4], 'events keep their server-assigned seq, not an array index')
assert.deepEqual(back.map((e) => e.text), [...SENTINEL_ORDER, 'ARRIVAL-D'], 'events come back in arrival order')

// --- A retry reset clears the run's old rows, then re-appends the new incarnation ---
applyStart(runA, { outcome: 'created', status: 'starting', phase: '', id: runA.serverId })
await persistNow()
assert.equal((await eventRows('seq-run')).length, 0, 'a retry reset clears the run\'s stale event rows')
runA.events.push({ seq: 1, kind: 'note', text: 'RESET-SENTINEL' })
await persistNow()
const resetBack = await eventRows('seq-run')
assert.equal(resetBack.length, 1, 'the reset re-appends the new incarnation\'s events')
assert.equal(resetBack[0].text, 'RESET-SENTINEL', 'only the new incarnation\'s events survive the reset')
assert.equal(resetBack[0].seq, 1, 'the re-appended event keeps its own seq')

// --- Removing a run deletes its event rows too ---
removeRun('seq-run')
await persistNow()
assert.equal(await db.runs.get('seq-run'), undefined, 'the deleted run\'s row is gone')
assert.equal((await eventRows('seq-run')).length, 0, 'deleting a run deletes its event rows')

// --- A drain rewrites only the drained run's row, not every run ---
const untouchedRun = tailFixture('untouched-run')
const drainedRun = tailFixture('drained-run')
await persistNow()
let runPuts = []
const runsBulkPut = db.runs.bulkPut
db.runs.bulkPut = async (rows) => { runPuts.push(...rows.map((r) => r.id)); return runsBulkPut.call(db.runs, rows) }
try {
  drainedRun.phase = 'gather'
  drainedRun.events.push({ seq: 1, kind: 'note', text: 'DRAINED-ONLY' })
  await persistNow()
} finally {
  db.runs.bulkPut = runsBulkPut
}
assert.equal(runPuts.filter((id) => id === 'drained-run').length, 1, 'a research drain writes exactly the drained run row')
assert.ok(!runPuts.includes('untouched-run'), 'a research drain leaves every other run row unwritten')
assert.deepEqual((await eventRows('drained-run')).map((e) => e.text), ['DRAINED-ONLY'], 'the drain appends only the new event row')
assert.equal((await eventRows('untouched-run')).length, 0, 'the untouched run gains no event rows')
// A run dropped from the array without removeRun still leaves the table.
state.runs = state.runs.filter((r) => r.id !== 'untouched-run')
await persistNow()
assert.equal(await db.runs.get('untouched-run'), undefined, 'a run dropped from the array without removeRun still leaves the table')
// --- A burst of events persists as rows at checkpoint cadence, not per event ---
const EVENT_COUNT = 60
const THROTTLE_SENTINEL = 'sentinel-throttle-42'
const live = tailFixture('throttle-run')
assert.equal(await persistNow(), true, 'a dirty run saves against working storage')
assert.ok(await db.runs.get('throttle-run'), 'the successful save reached storage')

const stream = liveStream()
const tail = tailRun(live)
await flush()
stream.send(Array.from({ length: EVENT_COUNT }, (_, i) => ({ seq: i + 1, kind: 'note', text: i === EVENT_COUNT - 1 ? THROTTLE_SENTINEL : `note-${i}` })))
await flush()
assert.equal(live.events.length, 0, 'events applied between checkpoints stay out of the watched record')
assert.equal((await eventRows('throttle-run')).length, 0, 'events applied between checkpoints trigger no row')
await new Promise((resolve) => setTimeout(resolve, CHECKPOINT_MS + 900))
assert.ok(live.events.some((event) => event.text === THROTTLE_SENTINEL), 'the checkpoint drain copies the buffered events into the run')
assert.equal((await eventRows('throttle-run')).length, EVENT_COUNT, 'the checkpoint drain stores one row per event, not per flush')

// --- A terminal write drains eagerly what the throttle still held ---
const LATE_SENTINEL = 'sentinel-late-43'
const lateBefore = (await eventRows('throttle-run')).length
stream.send([{ seq: EVENT_COUNT + 1, kind: 'note', text: LATE_SENTINEL }])
await flush()
await stopRun(live)
const storedLate = await eventRows('throttle-run')
assert.ok(storedLate.some((row) => row.text === LATE_SENTINEL), 'the cancelled run stores the events the throttle had not yet written')
assert.equal(storedLate.length, lateBefore + 1, 'the terminal drain appends only the single held event')
await tail
assert.equal(live.status, 'cancelled', 'stopping still lands the terminal state')
assert.ok(live.events.some((event) => event.text === LATE_SENTINEL), 'the terminal write drains events that never reached a checkpoint')

await initStore()
const reloaded = state.runs.find((r) => r.id === 'throttle-run')
assert.ok(reloaded?.events.some((event) => event.text === THROTTLE_SENTINEL), 'throttled events reach storage as rows and survive a reload')
assert.ok(reloaded?.events.some((event) => event.text === LATE_SENTINEL), 'the terminally drained event survives a reload')
assert.equal(reloaded?.status, 'cancelled', 'the terminal status survives a reload')
assert.ok(reloaded?.events.every((event) => !('runId' in event) && !('key' in event)), 'stored-only fields stay off the in-memory events')

// --- A final frame persists eagerly and the backend run is only forgotten after the save ---
const FINAL_SENTINEL = 'sentinel-final-44'
const ackUrls = []
let savedEventsAtAck = 0
let savedDocAtAck = false
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
      savedEventsAtAck = (await eventRows('final-run')).length
      savedDocAtAck = (await db.docs.toArray()).some((doc) => doc.text.includes('sentinel report body'))
    }
  }
  return new Response('{}', { status: 200 })
}

const finalLive = tailFixture('final-run')
await persistNow()
await tailRun(finalLive)
assert.equal(finalLive.ackPending, undefined, 'a final frame whose save succeeded clears the pending marker')
assert.ok(savedEventsAtAck > 0, 'the run\'s drained events are stored before the backend run is acknowledged')
assert.ok(savedDocAtAck, 'the report document is stored before the backend run is acknowledged')

const refusedLive = tailFixture('refused-run')
await persistNow()
ackUrls.length = 0
// An uncloneable function in the run row makes the flush fail loudly, as a poisoned write boundary does.
refusedLive.__poison = () => {}
await tailRun(refusedLive)
assert.equal(refusedLive.ackPending, true, 'a refused terminal save keeps the run recoverable')
assert.equal(ackUrls.length, 0, 'the backend run is not forgotten before its report is saved')

delete refusedLive.__poison
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
fakeDocument.visibilityState = 'hidden'
fakeDocument.dispatchEvent(new Event('visibilitychange'))
await flush()
assert.ok(hiddenLive.events.some((event) => event.text === HIDDEN_SENTINEL), 'hiding the tab drains the buffer instead of waiting for the interval')
assert.ok((await eventRows('hidden-run')).some((row) => row.text === HIDDEN_SENTINEL), 'the hidden drain stores the buffered event as a row')

hiddenStream.send([{ seq: 2, kind: 'note', text: PAGEHIDE_SENTINEL }])
fakeDocument.visibilityState = 'visible'
await flush()
globalThis.dispatchEvent(new Event('pagehide'))
await flush()
assert.ok((await eventRows('hidden-run')).some((row) => row.text === PAGEHIDE_SENTINEL), 'pagehide flushes the buffered research state')

await stopRun(hiddenLive)
await hiddenTail

console.log('research persistence selfcheck OK')