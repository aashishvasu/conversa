import { reactive } from 'vue'
import { attachChatTurn, discardChatTurn, getToken, startChatTurn } from '../api/client.js'
import { generateTitle } from '../jobs/titles.js'
import { refreshMemory } from '../jobs/memory.js'
import { tr } from '../i18n/index.js'
import { persistNow, state } from '../state/persistence.js'
import { effectiveSettings } from '../state/settings.js'
import { addConvoUsage, recordUsage } from '../state/usage.js'
import { notify } from '../utils/notify.js'
import { applyFrame, newDraft, settleMessage, turnStillWanted } from './turn.js'

const connections = new Map()
const turns = reactive(new Map())
const MAX_FAILURES = 5

export function turnState(messageId) {
  return turns.get(messageId)
}

function stillWanted(convo, message, turnId) {
  return turnStillWanted(state.conversations, convo, message, turnId)
}

function memory(convo, settings) {
  refreshMemory(convo, settings).catch((error) => notify({ key: 'utility:memory', severity: 'warning', text: tr('chat.memoryFailed', { error: error.message }) }))
}

async function finish(convo, message, turnId, draft, outcome, settings) {
  if (!stillWanted(convo, message, turnId)) return
  settleMessage(message, draft, outcome)
  if (outcome === 'done') addConvoUsage(convo, draft.usage)
  const saved = await persistNow()
  if (outcome === 'done') recordUsage('chat', draft.usage)
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
    let visible = !replay
    if (visible) view.trace = draft.trace
    view.connection = replay ? 'reconnecting' : 'live'
    const promote = () => {
      visible = true
      view.trace = draft.trace
      message.content = draft.content
      message.artifacts = [...draft.artifacts]
    }
    const onFrame = (frame) => {
      if (!stillWanted(convo, message, turnId)) {
        controller.abort()
        void discardChatTurn(turnId)
        return
      }
      view.lastFrameAt = Date.now()
      if (!frame.live) received = true
      applyFrame(draft, frame)
      if (!visible && (frame.live || draft.done || draft.error)) promote()
      if (visible && !frame.live) {
        view.connection = 'live'
        message.content = draft.content
        message.artifacts = [...draft.artifacts]
      }
    }
    try {
      if (first) await startChatTurn(turnId, payload, onFrame, controller.signal)
      else await attachChatTurn(turnId, onFrame, controller.signal)
      if (controller.signal.aborted) break
      if (draft.done || draft.error) {
        await finish(convo, message, turnId, draft, draft.error ? 'error' : 'done', settings)
        return
      }
      failures++
    } catch (error) {
      if (controller.signal.aborted || !getToken()) break
      if (!first && error.status === 404) {
        const partial = reactive(newDraft())
        partial.content = message.content || ''
        partial.artifacts = [...(message.artifacts || [])]
        partial.error = originalError?.message || error.message
        await finish(convo, message, turnId, partial, received ? 'gone' : 'error', settings)
        return
      }
      if (first && error.status) {
        draft.error = error.message
        await finish(convo, message, turnId, draft, 'error', settings)
        return
      }
      originalError ||= error
      failures++
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
  const view = turns.get(message.id) || reactive({ trace: [], connection: 'idle', lastFrameAt: 0 })
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
  const draft = newDraft()
  draft.content = message.content || ''
  draft.artifacts = [...(message.artifacts || [])]
  await finish(convo, message, turnId, draft, 'stopped', effectiveSettings(convo))
}

export function syncPendingTurns() {
  if (!getToken()) return
  for (const convo of state.conversations) {
    for (const message of convo.messages) {
      if (message.turnId && !connections.has(message.turnId)) void attachTurn(convo, message)
    }
  }
}
