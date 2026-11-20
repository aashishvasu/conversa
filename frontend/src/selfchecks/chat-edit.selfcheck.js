// Run: node src/selfchecks/chat-edit.selfcheck.js.
import assert from 'node:assert'
import { applyEdit, regenerate, removeMessage } from '../chat/edit.js'

function convo(messages, mode = 'chat') {
  return { id: 'c', mode, messages }
}

// A tail where the generated half sits below an in-flight user turn, plus a pinned system message that must survive.
const messages = () => [
  { id: 'u0', role: 'user', content: 'first' },
  { id: 'a1', role: 'assistant', content: 'one', turnId: 't1' },
  { id: 'u2', role: 'user', content: 'originating', runId: 'run2' },
  { id: 'a3', role: 'assistant', content: 'three', turnId: 't3', imageIds: ['img3'] },
  { id: 'a4', role: 'assistant', content: 'SENTINEL_TAIL', turnId: 't4', imageIds: ['img4'] },
  { id: 's5', role: 'system', content: 'SENTINEL_SYSTEM' },
]

function hooks(overrides = {}) {
  const cancelled = []
  const cancelledLengths = []
  const released = []
  const removedRuns = []
  const research = []
  const completed = []
  return {
    cancelled,
    cancelledLengths,
    released,
    removedRuns,
    research,
    completed,
    preparing: false,
    runActive: false,
    cancelTurn: async (c, m) => {
      cancelled.push(m.turnId)
      cancelledLengths.push(c.messages.length)
    },
    releaseImages: (ids) => released.push(...(ids || [])),
    removeRun: (id) => removedRuns.push(id),
    routeResearch: (c, u) => research.push([c, u]),
    runCompletion: (c) => completed.push(c),
    ...overrides,
  }
}

{
  // Regenerate waits for every in-flight turn below the cut before trimming, and removes exactly the tail (system survives).
  const c = convo(messages())
  const h = hooks()
  const original = c.messages.length
  await regenerate(c, c.messages[3], h) // regenerate from assistant 'a3'
  assert.deepEqual(h.cancelled, ['t3', 't4'], 'every in-flight turn below the cut is cancelled')
  assert.ok(h.cancelledLengths.every((n) => n === original), 'cancellation runs before any message is removed')
  assert.deepEqual(h.released, ['img3', 'img4'], 'images referenced only by the removed tail are released')
  assert.deepEqual(c.messages.map((m) => m.id), ['u0', 'a1', 'u2', 's5'], 'the origin, the turn above the cut, and pinned system messages survive')
  assert.ok(c.messages.every((m) => m.content !== 'SENTINEL_TAIL'), 'the removed tail (sentinel) is gone')
  assert.ok(c.messages.some((m) => m.content === 'SENTINEL_SYSTEM'), 'a system message below the cut survives regeneration')
  assert.deepEqual(c.messages.map((m) => m.id), ['u0', 'a1', 'u2', 's5'], 'survivors keep their order')
  assert.deepEqual(h.completed, [c], 'a chat regenerate re-runs the turn')
  assert.deepEqual(h.research, [], 'chat mode does not route research')
}

{
  // Research mode re-routes the originating user and removes the run it carried.
  const c = convo([...messages()], 'research')
  const h = hooks()
  await regenerate(c, c.messages[3], h)
  assert.equal(c.messages[2].mode, 'research', 'the originating user re-enters research mode')
  assert.ok(!Object.hasOwn(c.messages[2], 'runId'), 'the re-run user turn sheds its old run')
  assert.deepEqual(h.removedRuns, ['run2'], 'the surplus run is removed')
  assert.deepEqual(h.research.map(([, u]) => u.id), ['u2'], 'the originating user is routed into research')
  assert.deepEqual(h.completed, [], 'research mode does not run a plain completion')
}

// Bailing out leaves the conversation untouched.
for (const flag of ['preparing', 'runActive']) {
  const c = convo(messages())
  const h = hooks({ [flag]: true })
  await regenerate(c, c.messages[3], h)
  assert.deepEqual(c.messages.map((m) => m.id), messages().map((m) => m.id), `${flag} discards the call without mutating`)
  assert.deepEqual([h.cancelled, h.released, h.removedRuns, h.research, h.completed].map((l) => l.length), [0, 0, 0, 0, 0], `${flag} calls no lifecycle hook`)
}
await regenerate(null, null, hooks())
assert.ok(true, 'a missing conversation is a no-op')

// Removing one message: cancel its live turn, drop it, release its images.
{
  const c = convo([{ id: 'u0', role: 'user', content: 'x' }, { id: 'a1', role: 'assistant', content: 'y', turnId: 't1', imageIds: ['img1'] }])
  const h = hooks()
  await removeMessage(c, 'a1', h)
  assert.deepEqual(h.cancelled, ['t1'], 'the removed message cancels its in-flight turn')
  assert.deepEqual(h.released, ['img1'], 'the removed message releases its images')
  assert.deepEqual(c.messages.map((m) => m.id), ['u0'], 'the message is dropped from the tail')
}

// Removing a message with no live turn performs no cancellation.
{
  const c = convo([{ id: 'u0', role: 'user', content: 'x' }, { id: 'a1', role: 'assistant', content: 'y' }])
  const h = hooks()
  await removeMessage(c, 'a1', h)
  assert.deepEqual(h.cancelled, [], 'a settled message is not cancelled')
  assert.deepEqual(h.released, [], 'a message with no images releases nothing')
  assert.deepEqual(c.messages.map((m) => m.id), ['u0'], 'the message is dropped')
}

// A user-edited replacement drops the stale failure status and artifacts; an unchanged edit keeps them.
{
  const m = { id: 'a1', role: 'assistant', content: 'partial', artifacts: [{ tool: 'x' }], generation: { status: 'failed', error: { code: 'internal', message: 'e', retryable: false }, finishReason: null } }
  applyEdit(m, { role: 'assistant', content: 'partial' })
  assert.ok(m.generation && m.artifacts, 'an unchanged edit keeps the recorded status and artifacts')
  m.content = 'user replacement'
  applyEdit(m, { role: 'assistant', content: 'partial' })
  assert.ok(!Object.hasOwn(m, 'generation'), 'an edited replacement clears the stale failure label')
  assert.ok(!Object.hasOwn(m, 'artifacts'), 'an edited replacement drops artifacts that no longer match')
}

