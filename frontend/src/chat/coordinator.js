import { reactive } from 'vue'
import { attachChatTurn, discardChatTurn, getToken, startChatTurn } from '../api/client.js'
import { generateTitle } from '../jobs/titles.js'
import { refreshMemory } from '../jobs/memory.js'
import { tr } from '../i18n/index.js'
import { ensureLoaded, persistNow, readPendingTurnMessages, readStoredMessage, state } from '../state/persistence.js'
import { effectiveSettings } from '../state/settings.js'
import { addConvoUsage, recordUsage } from '../state/usage.js'
import { notify } from '../utils/notify.js'
import { applyFrame, newDraft, publicError, settleMessage, turnStillWanted } from './turn.js'

const connections = new Map()
const streams = new Map()
const turns = reactive(new Map())
const MAX_FAILURES = 5

// A live turn copies its draft into the stored message at this cadence, bounding what a crashed tab loses.
// The mutation is itself the save trigger: the conversation's watcher marks it dirty and the ordinary debounce writes one record.
export const CHECKPOINT_MS = 2000

export function turnState(messageId) {
  return turns.get(messageId)
}

function stillWanted(convo, message, turnId) {
  return turnStillWanted(state.conversations, convo, message, turnId)
}

function memory(convo, settings) {
  refreshMemory(convo, settings).catch((error) => notify({ key: 'utility:memory', severity: 'warning', text: tr('chat.memoryFailed', { error: error.message }) }))
}

function nextFrame(fn) {
  return globalThis.requestAnimationFrame ? globalThis.requestAnimationFrame(fn) : setTimeout(fn, 16)
}

function dropFrame(handle) {
  if (globalThis.requestAnimationFrame) globalThis.cancelAnimationFrame(handle)
  else clearTimeout(handle)
}

// rAF does not fire in a hidden tab, so buffered frames would never reach the view state.
globalThis.document?.addEventListener('visibilitychange', () => {
  for (const stream of streams.values()) stream.drain()
})

// Frames pile into a buffer and are applied at most once per animation frame.
// While a turn is live the text renders from the unwatched `turns` view state, so streaming never dirties the stored message and never walks the conversation.
// A replay stays invisible, showing the stored partial, until a live frame or the settle proves the draft current.
function createLiveStream({ convo, message, turnId, draft, view, controller, replay, onContent }) {
  const buffer = []
  let visible = !replay
  let scheduled = 0
  if (visible) view.trace = draft.trace

  const promote = () => {
    visible = true
    view.trace = draft.trace
    view.content = draft.content
    view.artifacts = [...draft.artifacts]
  }
  const applyBuffered = () => {
    let touched = false
    for (const frame of buffer.splice(0)) {
      if (!stillWanted(convo, message, turnId)) {
        controller.abort()
        void discardChatTurn(turnId)
        return
      }
      view.lastFrameAt = Date.now()
      if (!frame.live) onContent()
      applyFrame(draft, frame)
      if (!visible && (frame.live || draft.outcome)) promote()
      else if (visible && !frame.live) touched = true
    }
    if (touched) {
      view.connection = 'live'
      view.content = draft.content
      view.artifacts = [...draft.artifacts]
    }
  }
  return {
    push(frame) {
      buffer.push(frame)
      if (!scheduled) scheduled = nextFrame(() => { scheduled = 0; applyBuffered() })
    },
    // The tail of a stream can still sit in the buffer when the read resolves or the tab hides; apply it before the draft's done/error are consulted, or the settle loses it.
    drain() {
      if (scheduled) {
        dropFrame(scheduled)
        scheduled = 0
      }
      applyBuffered()
    },
    checkpoint() {
      // settleMessage releases the turnId, so a late tick can never undo a settled write.
      if (!visible || message.turnId !== turnId) return
      message.content = draft.content
      if (draft.artifacts.length) message.artifacts = [...draft.artifacts]
    },
  }
}

// A 404 on reattach also happens when another tab finished the turn and discarded it server-side.
// The stored record is the arbiter: its message no longer carrying this turnId means the turn was settled elsewhere, and adopting it preserves the complete reply instead of overwriting it with this tab's partial text.
// A missing or unreadable record leaves the ordinary gone settle in charge.
function adoptStoredMessage(message, stored) {
  for (const key of Object.keys(message)) if (!Object.hasOwn(stored, key)) delete message[key]
  Object.assign(message, stored)
}

async function adoptIfSettled(_convo, message, turnId) {
  if (message.turnId !== turnId) return false
  let storedMessage
  try {
    storedMessage = await readStoredMessage(message.id)
  } catch {
    return false
  }
  if (!storedMessage || storedMessage.turnId === turnId) return false
  adoptStoredMessage(message, storedMessage)
  const view = turns.get(message.id)
  if (view) {
    view.content = null
    view.artifacts = null
  }
  return true
}

async function finish(convo, message, turnId, draft, outcome, settings) {
  if (!stillWanted(convo, message, turnId)) return
  settleMessage(message, draft, outcome)
  if (outcome === 'done') addConvoUsage(convo, draft.usage)
  const saved = await persistNow()
  if (outcome === 'done') recordUsage('chat', draft.usage)
  const view = turns.get(message.id)
  if (view) {
    view.content = null
    view.artifacts = null
  }
  if (saved) void discardChatTurn(turnId)
  if (outcome === 'gone') notify({ key: 'chat:interrupted', severity: 'warning', text: tr('chat.replyInterrupted') })
  if (outcome === 'done' && convo.title === tr('sidebar.newConversation')) {
    try {
      const title = await generateTitle(convo, settings.utility_model)
      if (title) convo.title = title
    } catch (error) {
      notify({ key: 'utility:title', severity: 'warning', text: tr('chat.titleFailed', { error: error.message }) })
    }
  }
  memory(convo, settings)
}

function delay(ms, signal) {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve()
    const timer = setTimeout(done, ms)
    function done() {
      clearTimeout(timer)
      signal.removeEventListener('abort', done)
      resolve()
    }
    signal.addEventListener('abort', done, { once: true })
  })
}

async function run(convo, message, turnId, payload, settings, controller, view) {
  let first = Boolean(payload)
  let failures = 0
  let originalError = null
  let received = Boolean(message.content || message.artifacts?.length)
  while (!controller.signal.aborted && getToken() && stillWanted(convo, message, turnId)) {
    const replay = !first
    const draft = reactive(newDraft())
    view.connection = replay ? 'reconnecting' : 'live'
    const stream = createLiveStream({ convo, message, turnId, draft, view, controller, replay, onContent: () => { received = true } })
    streams.set(message.id, stream)
    const checkpointTimer = setInterval(stream.checkpoint, CHECKPOINT_MS)
    try {
      if (first) await startChatTurn(turnId, payload, stream.push, controller.signal)
      else await attachChatTurn(turnId, stream.push, controller.signal)
      stream.drain()
      if (controller.signal.aborted) break
      if (draft.outcome) {
        await finish(convo, message, turnId, draft, draft.outcome === 'failed' ? 'error' : 'done', settings)
        return
      }
      failures++
    } catch (error) {
      stream.drain()
      if (controller.signal.aborted || !getToken()) break
      if (!first && error.status === 404) {
        if (await adoptIfSettled(convo, message, turnId)) return
        const partial = reactive(newDraft())
        partial.content = view.content ?? message.content ?? ''
        partial.artifacts = [...(view.artifacts ?? message.artifacts ?? [])]
        partial.error = publicError({ error: originalError?.message || error.message, code: 'unavailable', retryable: true })
        await finish(convo, message, turnId, partial, received ? 'gone' : 'error', settings)
        return
      }
      if (first && error.status) {
        draft.error = publicError({ error: error.message, code: error.code ?? 'http', retryable: false })
        draft.outcome = 'failed'
        await finish(convo, message, turnId, draft, 'error', settings)
        return
      }
      originalError ||= error
      failures++
    } finally {
      clearInterval(checkpointTimer)
      streams.delete(message.id)
    }
    first = false
    if (failures >= MAX_FAILURES) break
    view.connection = 'reconnecting'
    await delay(Math.min(500 * 2 ** (failures - 1), 5000), controller.signal)
  }
}

async function connect(convo, message, payload, settings) {
  const turnId = message.turnId
  if (!turnId || !getToken()) return
  while (connections.has(turnId)) {
    const previous = connections.get(turnId)
    previous.controller.abort()
    await previous.promise
    if (!stillWanted(convo, message, turnId)) return
  }
  const controller = new AbortController()
  const view = turns.get(message.id) || reactive({ trace: [], connection: 'idle', lastFrameAt: 0, content: null, artifacts: null })
  turns.set(message.id, view)
  const entry = { controller, promise: null }
  connections.set(turnId, entry)
  const work = async () => {
    if (controller.signal.aborted) return
    if (navigator.locks?.request) {
      await navigator.locks.request(`chat-turn:${turnId}`, { ifAvailable: true }, async (lock) => {
        if (lock) await run(convo, message, turnId, payload, settings, controller, view)
      })
    } else await run(convo, message, turnId, payload, settings, controller, view)
  }
  entry.promise = work().finally(() => {
    if (connections.get(turnId) === entry) {
      connections.delete(turnId)
      view.connection = 'idle'
    }
  })
  return entry.promise
}

export function startTurn(convo, message, payload, settings) {
  for (const old of convo.messages) turns.delete(old.id)
  return connect(convo, message, payload, settings)
}

export function attachTurn(convo, message) {
  return connect(convo, message, null, effectiveSettings(convo))
}

export async function cancelTurn(convo, message) {
  const turnId = message?.turnId
  if (!turnId) return
  const connection = connections.get(turnId)
  connection?.controller.abort()
  if (connection) await connection.promise
  const view = turns.get(message.id)
  const draft = newDraft()
  draft.content = view?.content ?? message.content ?? ''
  draft.artifacts = [...(view?.artifacts ?? message.artifacts ?? [])]
  await finish(convo, message, turnId, draft, 'stopped', effectiveSettings(convo))
}

// Reattach live turns without loading every conversation: the turnId index lists the rows still awaiting a turn, each conversation loads on demand so the in-memory message the turn attaches to is the real one. A failure here is best-effort (the online and visibilitychange listeners retry).
export async function syncPendingTurns() {
  if (!getToken()) return
  try {
    const rows = await readPendingTurnMessages()
    await Promise.all(rows.map(async (message) => {
      const turnId = message.turnId
      if (!turnId || connections.has(turnId)) return
      const convo = state.conversations.find((c) => c.id === message.convoId)
      if (!convo) return
      await ensureLoaded(convo)
      const live = convo.messages.find((m) => m.id === message.id)
      if (live?.turnId && !connections.has(turnId)) await attachTurn(convo, live)
    }))
  } catch {
    // A background reattach may fail on a stale stored turn or a storage read error; the listeners retry it later.
  }
}
