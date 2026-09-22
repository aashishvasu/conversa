// Run: node src/selfchecks/research-lifecycle.selfcheck.js.
import assert from 'node:assert'
import { readFile } from 'node:fs/promises'
import { applyCancel, applyFailure, applyPrepared, applyStart, buildResearchStartBody, prepareReplacement, resumeWithCurrentModels } from '../research/lifecycle.js'
import { activeRunOf, finishRun, migrateRun, validRun } from '../state/runs.js'
import { state } from '../state/persistence.js'

const run = {
  id: 'client-run', serverId: 'client-run', status: 'running', phase: 'gather',
  events: [{ seq: 4 }], spend: { calls: 2 }, payload: { report: 'old' }, spendLedgered: true,
}
assert.equal(prepareReplacement(run, { code: 'no_such_run' }), true, 'a missing backend run enters persisted recovery')
assert.equal(run.status, 'recovering')
assert.equal(run.events.length, 1, 'recovery keeps replay state until the start response identifies a replacement')
assert.equal(applyStart(run, { id: 'client-run', resumed: false, status: 'running', phase: 'plan' }), true)
assert.deepEqual(run.events, [], 'a replacement backend run clears stale events')
assert.equal(run.spend, null)

const checkpointed = { serverId: 'run', checkpoint: 'old', prepared: { brief: { objective: 'objective', deliverable: 'report' } }, answers: {}, settings: { research_depth: 4, research_search_model: 's', research_note_model: 'n', research_report_model: 'r' } }
applyStart(checkpointed, { id: 'run', resumed: true, status: 'running', phase: 'researching', checkpoint: 'new' })
assert.equal(checkpointed.checkpoint, 'new', 'start adopts a returned checkpoint')
applyStart(checkpointed, { id: 'run', resumed: true, status: 'running', phase: 'researching' })
assert.equal(checkpointed.checkpoint, 'new', 'start preserves a checkpoint when the response omits it')
const startBody = buildResearchStartBody(checkpointed)
assert.equal(Object.hasOwn(startBody, 'settings'), false, 'research start does not send the redundant settings field')
assert.equal(startBody.checkpoint, 'new', 'research start sends the retained checkpoint')
assert.equal(startBody.restart_failed, false, 'ordinary starts do not reopen failed tasks')
resumeWithCurrentModels(checkpointed, {})
assert.equal(buildResearchStartBody(checkpointed).restart_failed, true, 'explicit recovery reopens evidence-free failed tasks')

const terminal = { id: 'client-run', serverId: 'client-run', status: 'starting', phase: '', events: [{ seq: 2 }], spend: { calls: 1 } }
assert.equal(applyStart(terminal, { id: 'client-run', resumed: true, status: 'done', phase: 'done' }), false)
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

const partialConvo = { id: 'partial-convo', messages: [{ id: 'result' }], docIds: [] }
state.conversations.push(partialConvo)
const partial = { id: 'partial-run', convoId: partialConvo.id, resultMessageId: 'result', status: 'running', spendLedgered: false, spend: null }
finishRun(partial, { status: 'partial', phase: 'verifying', payload: { name: 'partial', report: { text: 'report' }, summary: 'gaps' }, spend: { models: {} } })
assert.equal(partial.status, 'partial', 'partial results finalize')
assert.ok(partial.reportDocId, 'partial reports are persisted as documents')
state.conversations.pop()

const chatPane = await readFile(new URL('../views/ChatPane.vue', import.meta.url), 'utf8')
const researchBlock = await readFile(new URL('../components/ResearchBlock.vue', import.meta.url), 'utf8')
const orchestration = await readFile(new URL('../research/orchestration.js', import.meta.url), 'utf8')
const coordinator = await readFile(new URL('../research/coordinator.js', import.meta.url), 'utf8')
assert.ok(!/import\s*\{[^}]*\bstartResearch\b/.test(chatPane), 'ChatPane persists the run but never starts it')
assert.ok(/import\s*\{[^}]*\bstartResearch\b/.test(coordinator), 'coordinator owns background start and reconnection execution')
assert.ok(!/streaming\.value \|\| m\.runId/.test(chatPane), 'research-linked turns are regenerable')
assert.ok(/cancelPreparation/.test(chatPane), 'switching to chat mode cancels pending preparation')
assert.ok(/prepareResearch\(\{ \.\.\.input, model: chatSettings\.model \}/.test(orchestration), 'the selected chat model makes the routing decision')
assert.ok(/import.*useStreamOrchestration/.test(chatPane), 'ChatPane delegates streaming and routing to the orchestration composable')
assert.ok(/failures >= MAX_STREAM_RETRIES[\s\S]*applyFailure/.test(coordinator), 'exhausted stream retries land in a terminal client state')
assert.ok(/effectiveSettings\(convo\)\.model/.test(coordinator), 'preparation retry uses the currently selected chat model')
assert.ok(/buildResearchStartBody/.test(coordinator), 'coordinator uses the research start request helper')
assert.ok(/checkpoint\?\.frontier/.test(researchBlock), 'the trace rebuilds task state from a recovery checkpoint')
assert.ok(/checkpoint\?\.sources/.test(researchBlock), 'the trace rebuilds source state from a recovery checkpoint')
assert.ok(/checkpoint\?\.breakers/.test(researchBlock), 'the trace preserves breaker history across backend replacement')

console.log('research lifecycle selfcheck OK')
