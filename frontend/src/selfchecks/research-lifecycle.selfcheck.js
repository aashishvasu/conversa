// Run: node src/selfchecks/research-lifecycle.selfcheck.js.
import assert from 'node:assert'
import { readFile } from 'node:fs/promises'
import { applyCancel, applyFailure, applyStart, prepareReplacement } from '../research/lifecycle.js'

const run = {
  id: 'client-run', serverId: 'client-run', status: 'running', phase: 'gather',
  events: [{ seq: 4 }], spend: { calls: 2 }, payload: { report: 'old' }, spendLedgered: true,
}
assert.equal(prepareReplacement(run, { code: 'no_such_run' }), true, 'a missing backend run enters persisted recovery')
assert.equal(run.status, 'starting')
assert.equal(run.events.length, 1, 'recovery keeps replay state until the start response identifies a replacement')
assert.equal(applyStart(run, { id: 'client-run', resumed: false, status: 'running', phase: 'plan' }), true)
assert.deepEqual(run.events, [], 'a replacement backend run clears stale events')
assert.equal(run.spend, null)

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

const chatPane = await readFile(new URL('../views/ChatPane.vue', import.meta.url), 'utf8')
const researchBlock = await readFile(new URL('../components/ResearchBlock.vue', import.meta.url), 'utf8')
const orchestration = await readFile(new URL('../research/orchestration.js', import.meta.url), 'utf8')
assert.ok(!/import\s*\{[^}]*\bstartResearch\b/.test(chatPane), 'ChatPane persists the run but never starts it')
assert.ok(/import\s*\{[^}]*\bstartResearch\b/.test(researchBlock), 'ResearchBlock is the sole initial/recovery start owner')
assert.ok(!/streaming\.value \|\| m\.runId/.test(chatPane), 'research-linked turns are regenerable')
assert.ok(/user\.mode === 'research'/.test(chatPane), 'regeneration routes research-enabled turns through preparation again')
assert.ok(/prepareResearch\(\{ \.\.\.input, model: chatSettings\.model \}\)/.test(orchestration), 'the selected chat model makes the routing decision')
assert.ok(/import.*useStreamOrchestration/.test(chatPane), 'ChatPane delegates streaming and routing to the orchestration composable')
assert.ok(/failures >= MAX_STREAM_RETRIES[\s\S]*applyFailure/.test(researchBlock), 'exhausted stream retries land in a terminal client state')
assert.ok(/title: current\.prepared\.goal/.test(researchBlock), 'the prepared goal names the report')

console.log('research lifecycle selfcheck OK')
