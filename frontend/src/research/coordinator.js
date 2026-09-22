import { ackResearch, discardResearch, prepareResearch, startResearch, streamResearch } from '../api/client.js'
import { applyCancel, applyFailure, applyPrepared, applyStart, buildResearchStartBody, prepareReplacement, resumeWithCurrentModels } from './lifecycle.js'
import { finishRun } from '../state/runs.js'
import { persistNow, state } from '../state/persistence.js'
import { effectiveSettings } from '../state/settings.js'

const controllers = new Map()
const activeTails = new Set()
const preparations = new Map()
const MAX_STREAM_RETRIES = 5

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
      finishRun(run, result)
      await persistNow()
      await ackResearch(run.serverId)
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

export async function tailRun(run) {
  if (!run?.serverId || activeTails.has(run.id)) return
  if (!['starting', 'running', 'recovering'].includes(run.status)) return
  activeTails.add(run.id)
  controllers.get(run.id)?.abort()
  const controller = new AbortController()
  controllers.set(run.id, controller)

  let failures = 0
  try {
    while (!controller.signal.aborted && ['starting', 'running', 'recovering'].includes(run.status)) {
      try {
        await streamResearch(run.serverId, run.events.length, async (data) => {
          if (data.spend) run.spend = data.spend
          if (data.kind === 'tick') {
            run.phase = data.phase
            return
          }
          if (data.kind === 'phase') {
            run.phase = data.phase
            return
          }
          if (data.kind === 'checkpoint') {
            run.checkpoint = data.checkpoint
            return
          }
          if (data.kind === 'final') {
            finishRun(run, data)
            await persistNow()
            await ackResearch(run.serverId)
            return
          }
          run.events.push(data)
          if (data.seq) await persistNow()
        }, controller.signal)

        if (run.status !== 'running') break
      } catch (streamError) {
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
    if (run.status === 'starting' && !run.prepared?.brief?.questions?.length) {
      void startRun(run)
    } else if (['running', 'recovering'].includes(run.status)) {
      void tailRun(run)
    }
  }
}
