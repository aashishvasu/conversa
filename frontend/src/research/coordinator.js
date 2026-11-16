import { ackResearch, discardResearch, prepareResearch, startResearch, streamResearch } from '../api/client.js'
import { acceptEvent, applyCancel, applyFailure, applyPrepared, applyStart, buildResearchStartBody, prepareReplacement, replayPosition, resumeWithCurrentModels } from './lifecycle.js'
import { CHECKPOINT_MS } from '../chat/coordinator.js'
import { finishRun } from '../state/runs.js'
import { persistNow, state } from '../state/persistence.js'
import { effectiveSettings } from '../state/settings.js'

const controllers = new Map()
const activeTails = new Set()
const preparations = new Map()
const drains = new Map()
const MAX_STREAM_RETRIES = 5

// Interval drains are throttled in a hidden tab, and the teardown flush can only save what has reached the watched state. drainAll persists on its own, so it does not matter whether the teardown flush's listener runs before or after it.
function drainAll() {
  for (const drain of drains.values()) drain()
  void persistNow()
}

let drainFlushInstalled = false
function installDrainFlush() {
  if (drainFlushInstalled) return
  drainFlushInstalled = true
  globalThis.addEventListener?.('pagehide', drainAll)
  globalThis.document?.addEventListener('visibilitychange', () => {
    if (globalThis.document.visibilityState === 'hidden') drainAll()
  })
}

export function beginPreparation(convoId) {
  const existing = preparations.get(convoId)
  if (existing) existing.controller.abort()
  const generation = (existing?.generation || 0) + 1
  const controller = new AbortController()
  preparations.set(convoId, { controller, generation })
  return generation
}

export function getPreparationSignal(convoId) {
  return preparations.get(convoId)?.controller.signal
}

export function isPreparationCurrent(convoId, generation) {
  const current = preparations.get(convoId)
  return current?.generation === generation && !current.controller.signal.aborted
}

export function endPreparation(convoId, generation) {
  const current = preparations.get(convoId)
  if (current?.generation === generation) preparations.delete(convoId)
}

export function cancelPreparation(convoId) {
  const current = preparations.get(convoId)
  if (!current) return false
  current.controller.abort()
  current.generation++
  preparations.delete(convoId)
  return true
}

export function isPreparing(convoId) {
  return preparations.has(convoId)
}

export async function startRun(run, answers = null) {
  if (!run) return false
  if (answers) {
    run.answers = { ...run.answers, ...answers }
    if (run.prepared) run.prepared.answers = run.answers
  }
  Object.assign(run, { status: 'starting', error: null, isPreparing: false, updatedAt: Date.now() })
  await persistNow()
  try {
    const body = buildResearchStartBody(run)
    const result = await startResearch(body)
    if (['done', 'partial'].includes(result.status)) {
      await finishAndAck(run, result)
      return true
    }
    applyStart(run, result)
    await persistNow()
    void tailRun(run)
    return true
  } catch (error) {
    applyFailure(run, error)
    await persistNow()
    return false
  }
}

// ackPending survives a failed ack so syncActiveRuns() can retry it; a stored run without it needs nothing.
async function finishAndAck(run, frame) {
  finishRun(run, frame)
  run.ackPending = true
  await ackRun(run)
}

async function ackRun(run) {
  if ((await persistNow()) === false) return
  if (!(await ackResearch(run.serverId))) return
  delete run.ackPending
  await persistNow()
}

export async function tailRun(run) {
  if (!run?.serverId || activeTails.has(run.id)) return
  if (!['starting', 'running', 'recovering'].includes(run.status)) return
  installDrainFlush()
  activeTails.add(run.id)
  controllers.get(run.id)?.abort()
  const controller = new AbortController()
  controllers.set(run.id, controller)

  // Stream data lands in plain locals; only the checkpoint drain mutates the watched run, so a long tail dirties and serializes the runs collection once per interval, not once per event.
  const buffer = []
  const pending = {}
  const drain = () => {
    if (buffer.length) {
      run.events.push(...buffer)
      buffer.length = 0
    }
    if ('phase' in pending) {
      run.phase = pending.phase
      delete pending.phase
    }
    if ('checkpoint' in pending) {
      run.checkpoint = pending.checkpoint
      delete pending.checkpoint
    }
    if ('spend' in pending) {
      run.spend = pending.spend
      delete pending.spend
    }
  }
  drains.set(run.id, drain)
  const checkpointTimer = setInterval(drain, CHECKPOINT_MS)

  let failures = 0
  try {
    while (!controller.signal.aborted && ['starting', 'running', 'recovering'].includes(run.status)) {
      try {
        await streamResearch(run.serverId, replayPosition(run), async (data) => {
          if (!acceptEvent(run, data)) return
          if (data.spend) pending.spend = data.spend
          if (data.kind === 'tick' || data.kind === 'phase') {
            pending.phase = data.phase
            return
          }
          if (data.kind === 'checkpoint') {
            pending.checkpoint = data.checkpoint
            return
          }
          if (data.kind === 'final') {
            // Terminal frames gate finishRun's rule that the backend run is only forgotten after its report is the app's, so they drain and persist eagerly instead of at cadence.
            drain()
            await finishAndAck(run, data)
            return
          }
          buffer.push(data)
        }, controller.signal)

        if (run.status !== 'running') break
      } catch (streamError) {
        drain()
        if (controller.signal.aborted) break
        if (prepareReplacement(run, streamError)) {
          await persistNow()
          try {
            const body = buildResearchStartBody(run)
            const result = await startResearch(body)
            applyStart(run, result)
            await persistNow()
            failures = 0
            continue
          } catch (recoveryError) {
            applyFailure(run, recoveryError)
            await persistNow()
            break
          }
        }
        failures++
        if (failures >= MAX_STREAM_RETRIES) {
          applyFailure(run, new Error(streamError.message || 'research stream failed'))
          await persistNow()
          break
        }
        await new Promise((resolve) => setTimeout(resolve, Math.min(500 * 2 ** (failures - 1), 5000)))
      }
    }
  } finally {
    clearInterval(checkpointTimer)
    drain()
    drains.delete(run.id)
    activeTails.delete(run.id)
    if (controllers.get(run.id) === controller) controllers.delete(run.id)
  }
}

export async function stopRun(run) {
  if (!run?.serverId) return
  controllers.get(run.id)?.abort()
  controllers.delete(run.id)
  try {
    await discardResearch(run.serverId)
  } catch {}
  // Synchronous drain: the abort path's own drains race this write, and a cancel must store what the throttle held.
  drains.get(run.id)?.()
  applyCancel(run)
  await persistNow()
}

export async function retryRun(run) {
  if (!run) return
  run.retryFailed = true
  await startRun(run)
}

export async function resumeRun(run, settings) {
  if (!run) return
  resumeWithCurrentModels(run, settings)
  await persistNow()
  await startRun(run)
}

export async function retryPreparation(run, convo, onAnswer) {
  if (!run || run.isPreparing) return
  run.isPreparing = true
  run.preparationFailed = false
  run.error = null
  await persistNow()
  try {
    const input = { ...run.input, model: effectiveSettings(convo).model }
    run.input = input
    const prepared = await prepareResearch(input)
    if (prepared.action === 'answer') {
      run.isPreparing = false
      if (onAnswer) await onAnswer(run, prepared)
      return
    }
    applyPrepared(run, prepared)
    await persistNow()
    if (run.status === 'starting') void startRun(run)
  } catch (error) {
    run.isPreparing = false
    run.preparationFailed = true
    run.error = error.message
    await persistNow()
  }
}

export function syncActiveRuns(runs = state.runs) {
  if (!Array.isArray(runs)) return
  for (const run of runs) {
    if (run.ackPending) {
      void ackRun(run)
    } else if (run.status === 'starting' && !run.prepared?.brief?.questions?.length) {
      void startRun(run)
    } else if (['running', 'recovering'].includes(run.status)) {
      void tailRun(run)
    }
  }
}
