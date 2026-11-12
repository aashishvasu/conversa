// Run: node src/selfchecks/research-lifecycle.selfcheck.js.
import assert from 'node:assert'
import { acceptEvent, applyCancel, applyFailure, applyPrepared, applyStart, buildResearchStartBody, prepareReplacement, replayPosition, resumeWithCurrentModels } from '../research/lifecycle.js'
import { activeRunOf, finishRun, migrateRun, researchProvenanceHeader, validRun } from '../state/runs.js'
import { setLoaded, state } from '../state/persistence.js'
import { streamResearch } from '../api/client.js'
import { beginPreparation, cancelPreparation, getPreparationSignal, isPreparationCurrent, isPreparing, retryPreparation, startRun, syncActiveRuns, tailRun } from '../research/coordinator.js'
import { useStreamOrchestration } from '../research/orchestration.js'

const run = {
  id: 'client-run', serverId: 'client-run', status: 'running', phase: 'gather',
  events: [{ seq: 4 }], spend: { calls: 2 }, payload: { report: 'old' }, spendLedgered: true,
}
assert.equal(prepareReplacement(run, { code: 'no_such_run' }), true, 'a missing backend run enters persisted recovery')
assert.equal(run.status, 'recovering')
assert.equal(run.events.length, 1, 'recovery keeps replay state until the start response identifies a replacement')
assert.equal(applyStart(run, { id: 'client-run', outcome: 'created', status: 'running', phase: 'plan' }), true)
assert.deepEqual(run.events, [], 'a replacement backend run clears stale events')
assert.equal(run.spend, null)

const checkpointed = { serverId: 'run', checkpoint: 'old', prepared: { brief: { objective: 'objective', deliverable: 'report' } }, answers: {}, settings: { research_depth: 4, research_min_sources: 12, research_max_sources: 40, research_search_model: 's', research_note_model: 'n', research_report_model: 'r' } }
applyStart(checkpointed, { id: 'run', outcome: 'already_running', status: 'running', phase: 'researching', checkpoint: 'new' })
assert.equal(checkpointed.checkpoint, 'new', 'start adopts a returned checkpoint')
applyStart(checkpointed, { id: 'run', outcome: 'already_running', status: 'running', phase: 'researching' })
assert.equal(checkpointed.checkpoint, 'new', 'start preserves a checkpoint when the response omits it')
const startBody = buildResearchStartBody(checkpointed)
assert.equal(Object.hasOwn(startBody, 'settings'), false, 'research start does not send the redundant settings field')
assert.equal(startBody.checkpoint, 'new', 'research start sends the retained checkpoint')
assert.equal(startBody.restart_failed, false, 'ordinary starts do not reopen failed tasks')
assert.equal(startBody.min_sources, 12, 'research start sends min_sources from settings')
assert.equal(startBody.max_sources, 40, 'research start sends max_sources from settings')
assert.equal(startBody.depth, 4, 'research start sends the configured depth')
const withoutDepth = { ...checkpointed, settings: { ...checkpointed.settings } }
delete withoutDepth.settings.research_depth
assert.equal(Object.hasOwn(buildResearchStartBody(withoutDepth), 'depth'), false, 'missing depth lets the backend apply its default')
const invertedSettings = { ...checkpointed, settings: { ...checkpointed.settings, research_min_sources: 50, research_max_sources: 10 } }
const invertedBody = buildResearchStartBody(invertedSettings)
assert.equal(invertedBody.min_sources, 10, 'min_sources is clamped <= max_sources')
assert.equal(invertedBody.max_sources, 50, 'max_sources is clamped >= min_sources')
resumeWithCurrentModels(checkpointed, {})
assert.equal(buildResearchStartBody(checkpointed).restart_failed, true, 'explicit recovery reopens evidence-free failed tasks')

const terminal = { id: 'client-run', serverId: 'client-run', status: 'starting', phase: '', events: [{ seq: 2 }], spend: { calls: 1 } }
assert.equal(applyStart(terminal, { id: 'client-run', outcome: 'already_finished', status: 'done', phase: 'done' }), false)
assert.equal(terminal.status, 'done', 'a retained terminal backend run is collected instead of restarted')
assert.equal(terminal.events.length, 1, 'a retained run keeps its replay position')
assert.equal(prepareReplacement(terminal, new Error('not found')), false, 'only a machine-readable missing-run error restarts work')

const failed = { status: 'running', error: null }
applyFailure(failed, new Error('provider returned 500'))
assert.equal(failed.status, 'error', 'an exhausted stream failure releases the conversation lock')
assert.equal(failed.error, 'provider returned 500')

const stopped = { id: 'client-run', serverId: 'client-run', status: 'running', events: [], payload: null }
applyCancel(stopped)
assert.equal(stopped.status, 'cancelled', 'stopping releases the conversation lock before the final frame lands')
assert.equal(prepareReplacement(stopped, { code: 'no_such_run' }), false, 'a stopped run is never restarted by stream recovery')

const waiting = { status: 'starting', prepared: { brief: {} } }
assert.equal(applyPrepared(waiting, { brief: { objective: 'x', questions: [{ question: 'audience', default: 'all' }] } }), 'waiting_for_clarification', 'questions create a real waiting state')
assert.equal(waiting.status, 'waiting_for_clarification')
assert.equal(applyPrepared(waiting, { action: 'answer' }), 'answer', 'direct answers are not treated as research briefs')
assert.equal(activeRunOf('clarify-convo'), null, 'unrelated conversations remain unblocked')
const blocked = { id: 'waiting-run', convoId: 'clarify-convo', status: 'waiting_for_clarification' }
state.runs.push(blocked)
assert.equal(activeRunOf('clarify-convo')?.id, blocked.id, 'waiting clarification blocks a second turn')
state.runs.pop()

const old = { id: 'old', convoId: 'c', input: {}, prepared: { goal: 'legacy', questions: [] }, settings: {} }
const migrated = migrateRun(old)
assert.ok(migrated.prepared.brief && migrated.prepared.brief.objective === 'legacy', 'old runs migrate to a brief')
assert.equal(validRun(old), true, 'old runs remain valid after migration')
assert.equal(old.prepared.brief, undefined, 'run migration does not mutate the source object')

const completedAt = new Date('2025-01-02T03:04:05.000Z')
const provenanceRun = { events: [{ kind: 'wave' }, { kind: 'wave' }] }
const provenanceFrame = {
  checkpoint: {
    breakers: [{ branch: 'fetch', url: 'https://failed.example' }, { branch: 'global', message: 'source cap reached' }],
    gaps: ['checkpoint gap'],
    decisions: [{ action: 'continue' }],
  },
  payload: { sources: [{ id: 'S1' }, { id: 'S2' }], summary: 'Coverage summary', gaps: ['report gap'], decisions: [{ action: 'finish' }], report: { text: 'report' } },
  spend: { calls: 4 },
}
const provenance = researchProvenanceHeader(provenanceRun, provenanceFrame, completedAt)
assert.match(provenance, /Completed: 2025-01-02T03:04:05\.000Z/)
assert.match(provenance, /Sources gathered: 2; failed: 1/)
assert.match(provenance, /Model calls: 4; cost: \$0\.0000/)
assert.match(provenance, /Waves run: 2/)
assert.match(provenance, /global: source cap reached/)
assert.match(provenance, /Coverage summary/)
assert.match(provenance, /report gap; checkpoint gap/)

const partialConvo = { id: 'partial-convo', messages: [{ id: 'result' }], docIds: [] }
state.conversations.push(partialConvo)
const partial = { id: 'partial-run', convoId: partialConvo.id, resultMessageId: 'result', status: 'running', spendLedgered: false, spend: null, events: [] }
finishRun(partial, { status: 'partial', phase: 'verifying', checkpoint: provenanceFrame.checkpoint, payload: { ...provenanceFrame.payload, name: 'partial' }, spend: { models: {} } })
assert.equal(partial.status, 'partial', 'partial results finalize')
assert.ok(partial.reportDocId, 'partial reports are persisted as documents')
const partialDoc = state.docs.find((doc) => doc.id === partial.reportDocId)
assert.ok(partialDoc.text.startsWith('## Research provenance'), 'report documents start with provenance')
assert.ok(partialDoc.text.endsWith('report'), 'provenance preserves the report body')
state.conversations.pop()
state.docs = state.docs.filter((doc) => doc.id !== partial.reportDocId)

// coordinator.js and orchestration.js reach the network through global fetch and the token through localStorage, so planting both drives the real functions.
const wireCalls = []
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
function sentBody(init) {
  try {
    return init?.body ? JSON.parse(init.body) : null
  } catch {
    return null
  }
}
globalThis.fetch = async (url, init) => {
  wireCalls.push({ url: String(url), body: sentBody(init) })
  throw new Error('sentinel: wire refused')
}

const started = {
  id: 'start-run', serverId: 'start-run', status: 'starting', phase: '', events: [], spend: null,
  answers: {}, checkpoint: 'sentinel-checkpoint', retryFailed: true,
  prepared: { brief: { objective: 'sentinel objective', deliverable: 'sentinel deliverable', scope: ['sentinel scope'], constraints: ['sentinel constraint'], questions: [{ question: 'sentinel question', default: 'sentinel default' }] } },
  settings: { research_depth: 3, research_min_sources: 40, research_max_sources: 5, research_search_model: 'sentinel-search', research_note_model: 'sentinel-note', research_report_model: 'sentinel-report' },
}
const expectedStartBody = buildResearchStartBody(started)
wireCalls.length = 0
assert.equal(await startRun(started), false, 'a refused start reports failure to its caller')
assert.deepEqual(wireCalls[0].body, expectedStartBody, 'the coordinator posts the body the start helper built')
assert.equal(wireCalls[0].body.checkpoint, 'sentinel-checkpoint', 'the posted start carries the run checkpoint')
assert.equal(wireCalls[0].body.answers['sentinel question'], 'sentinel default', 'the posted start answers an unanswered question with its default')
assert.equal(started.status, 'error', 'a refused start lands in a terminal client state')

const exhausted = { id: 'exhaust-run', serverId: 'exhaust-server', status: 'running', phase: 'gather', events: [], spend: null }
const realSetTimeout = globalThis.setTimeout
//  the backoff waits 500ms to 4s per attempt, and only the attempt count and the terminal state are under test.
globalThis.setTimeout = (fn) => queueMicrotask(fn)
wireCalls.length = 0
try {
  await tailRun(exhausted)
} finally {
  globalThis.setTimeout = realSetTimeout
}
assert.equal(exhausted.status, 'error', 'exhausted stream retries land in a terminal client state')
assert.equal(exhausted.error, 'sentinel: wire refused', 'the terminal state carries the failure that exhausted the retries')
assert.ok(wireCalls.filter((call) => call.url.includes('/stream')).length > 1, 'the tail retried the stream instead of giving up on the first refusal')

const prepConvoId = 'sentinel-prep-convo'
const generation = beginPreparation(prepConvoId)
const prepSignal = getPreparationSignal(prepConvoId)
assert.equal(isPreparing(prepConvoId), true, 'a started preparation holds the conversation')
assert.equal(cancelPreparation(prepConvoId), true, 'cancelling reports the preparation it stopped')
assert.equal(prepSignal.aborted, true, 'cancelling aborts the preparation signal')
assert.equal(isPreparationCurrent(prepConvoId, generation), false, 'a cancelled generation never resumes')
assert.equal(isPreparing(prepConvoId), false, 'cancelling releases the preparation lock')
assert.equal(cancelPreparation(prepConvoId), false, 'a second cancel finds nothing pending')

const retried = { id: 'retry-run', status: 'starting', isPreparing: false, input: { model: 'stale-snapshot-model', system: 'stale system' } }
const retryConvo = { id: 'retry-convo', mode: 'research', settings: { model: 'sentinel-selected-model' } }
wireCalls.length = 0
await retryPreparation(retried, retryConvo)
const retryCall = wireCalls.find((call) => call.url.startsWith('/api/research/prepare'))
assert.equal(retryCall.body.model, 'sentinel-selected-model', 'preparation retry re-reads the currently selected chat model')
assert.equal(retryCall.body.system, 'stale system', 'preparation retry keeps the context the run was created with')
assert.equal(retried.preparationFailed, true, 'a refused preparation is reported on the run')
assert.equal(retried.error, 'sentinel: wire refused', 'the preparation failure carries the wire error')
assert.equal(retried.isPreparing, false, 'a refused preparation releases the lock')

const routed = { id: 'routed-convo', title: 'Sentinel', mode: 'research', workspaceId: null, docIds: [], settings: { model: 'sentinel-routing-model' }, messages: [] }
const routedUser = { id: 'routed-user', role: 'user', content: 'sentinel question', mode: 'research', createdAt: Date.now() }
routed.messages.push(routedUser)
state.conversations.push(routed)
wireCalls.length = 0
//  useStreamOrchestration binds lifecycle hooks and warns outside a component, but routeResearch itself is plain async.
await useStreamOrchestration().routeResearch(routed, routedUser)
const routeCall = wireCalls.find((call) => call.url.startsWith('/api/research/prepare'))
assert.equal(routeCall.body.model, 'sentinel-routing-model', 'the selected chat model makes the routing decision')
assert.ok(routeCall.body.messages.some((message) => message.content === 'sentinel question'), 'preparation sees the ordinary chat context')
state.conversations.pop()
state.runs = state.runs.filter((entry) => entry.convoId !== routed.id)

assert.equal(replayPosition({ id: 'pos-run', events: [{ seq: 2 }, { seq: 7 }, { seq: 5 }] }), 7, 'a stored run reconnects after its highest seq')
assert.equal(replayPosition({ id: 'pos-legacy', events: [{}, {}, {}] }), 3, 'stored events without seq fall back to their count')

const recreated = { id: 'recreated-run', serverId: 'recreated-run', status: 'recovering', events: [{ seq: 9 }], checkpoint: 'cp', spend: { calls: 3 }, spendLedgered: true }
acceptEvent(recreated, { seq: 12, kind: 'phase' })
applyStart(recreated, { id: 'recreated-run', outcome: 'resumed_from_checkpoint', resumed: true, status: 'running', phase: 'plan' })
assert.deepEqual(recreated.events, [], 'a checkpoint resume on a new server log drops the old events')
assert.equal(replayPosition(recreated), 0, 'a checkpoint resume restarts the replay position')
const reattached = { id: 'reattached-run', serverId: 'reattached-run', status: 'running', events: [{ seq: 9 }] }
applyStart(reattached, { id: 'reattached-run', outcome: 'already_running', resumed: true, status: 'running', phase: 'plan' })
assert.equal(replayPosition(reattached), 9, 'reattaching to a running server log keeps the replay position')

function sseResponse(frames) {
  return new Response(frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join(''), { status: 200 })
}
const serverLog = [{ seq: 1, kind: 'phase', phase: 'gather' }, { seq: 2, kind: 'wave', wave: 1 }, { seq: 3, kind: 'checkpoint', checkpoint: 'cp-sentinel' }, { seq: 4, kind: 'phase', phase: 'verify' }]
const streamAfters = []
globalThis.fetch = async (url) => {
  const href = String(url)
  if (href.includes('/stream')) {
    streamAfters.push(Number(new URL(href, 'http://local').searchParams.get('after')))
    // The second connection ignores the cursor and replays everything, so only client-side dedup keeps events single.
    return sseResponse(streamAfters.length === 1 ? serverLog : [...serverLog, { kind: 'final', status: 'cancelled', phase: 'verify', payload: null }])
  }
  return new Response('{}', { status: 200 })
}
const replayed = { id: 'replay-run', serverId: 'replay-run', status: 'running', phase: '', events: [], spend: null, spendLedgered: true }
await tailRun(replayed)
assert.equal(replayed.events.filter((event) => event.kind === 'wave').length, 1, 'a reconnect after phase and checkpoint events applies no event twice')
assert.equal(streamAfters[1], 4, 'a reconnect within the session resumes after the last phase or checkpoint seq')
assert.equal(replayed.checkpoint, 'cp-sentinel')

globalThis.fetch = async () => sseResponse([{ seq: 1, kind: 'a' }, { seq: 2, kind: 'b' }])
const handled = []
await streamResearch('await-run', 0, async (frame) => {
  await new Promise((resolve) => realSetTimeout(resolve, 5))
  handled.push(frame.kind)
})
assert.deepEqual(handled, ['a', 'b'], 'the stream awaits each async event callback in order before it resolves')
await assert.rejects(streamResearch('await-run', 0, async () => { throw new Error('sentinel callback failure') }), /sentinel callback failure/, 'an async callback failure fails the stream')

const ackCalls = []
let ackStatus = 500
globalThis.fetch = async (url) => {
  ackCalls.push(String(url))
  return new Response('{}', { status: ackStatus })
}
const pendingAck = { id: 'ack-run', serverId: 'ack-server', status: 'done', events: [], ackPending: true }
const settled = { id: 'settled-run', serverId: 'settled-server', status: 'done', events: [] }
const flush = () => new Promise((resolve) => realSetTimeout(resolve, 20))
syncActiveRuns([pendingAck, settled])
await flush()
assert.equal(pendingAck.ackPending, true, 'a failed ack keeps the pending marker for the next sync')
ackStatus = 404
ackCalls.length = 0
syncActiveRuns([pendingAck, settled])
await flush()
assert.equal(pendingAck.ackPending, undefined, 'an ack the server answers, even with 404, clears the pending marker')
assert.ok(ackCalls.some((call) => call.includes('/ack-server/ack')), 'sync retries a pending ack')
assert.ok(!ackCalls.some((call) => call.includes('settled-server')), 'a finished run without a pending ack triggers no ack call')

const unsaved = { id: 'unsaved-run', serverId: 'unsaved-server', status: 'done', events: [], ackPending: true }
ackCalls.length = 0
setLoaded(true)
try {
  syncActiveRuns([unsaved])
  await flush()
} finally {
  setLoaded(false)
}
assert.equal(unsaved.ackPending, true, 'a run whose result was not saved keeps its pending ack')
assert.ok(!ackCalls.some((call) => call.includes('unsaved-server')), 'a run is never acknowledged before its result is saved')

console.log('research lifecycle selfcheck OK')
