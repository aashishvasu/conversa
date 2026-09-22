import { state } from './persistence.js'
import { createDoc } from './docs.js'
import { foldRunUsage } from './usage.js'

export function migrateRun(r) {
  if (!r || typeof r !== 'object') return null
  const next = { ...r, events: Array.isArray(r.events) ? r.events : [], checkpoint: r.checkpoint ?? null, retryFailed: r.retryFailed ?? false, spendLedgered: r.spendLedgered ?? false }
  next.prepared = r.prepared?.brief
    ? { ...r.prepared, brief: { ...r.prepared.brief, questions: Array.isArray(r.prepared.brief.questions) ? r.prepared.brief.questions : [] } }
    : { brief: { objective: r.prepared?.goal || '', deliverable: r.prepared?.goal || '', scope: [], constraints: [], questions: r.prepared?.questions || [] }, answers: {} }
  next.answers = r.answers || next.prepared.answers || {}
  return next
}

export function validRun(r) {
  const run = migrateRun(r)
  return Boolean(run?.id && run.convoId && run.input && run.prepared?.brief && run.settings)
}

export function createRun(convo, promptMessageId, resultMessageId, input, prepared, settings) {
  const id = crypto.randomUUID()
  const r = {
    id,
    convoId: convo.id,
    promptMessageId,
    resultMessageId,
    reportDocId: null,
    sourceWorkspaceId: convo.workspaceId,
    // Snapshot these before the POST. A later settings edit cannot change an in-flight turn.
    input: structuredClone(input),
    prepared: structuredClone({ brief: prepared.brief || prepared, answers: prepared.answers || {} }),
    answers: {},
    checkpoint: null,
    retryFailed: false,
    settings: structuredClone(settings),
    // The backend accepts this browser-generated id idempotently, so it survives a lost start response.
    serverId: id,
    status: prepared.brief?.questions?.length ? 'waiting_for_clarification' : 'starting',
    phase: '',
    events: [],
    spend: null,
    spendLedgered: false,
    payload: null,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  }
  // Return the reactive instance, so mutations through this handle reach the persistence watcher.
  state.runs.unshift(r)
  return state.runs[0]
}

export function runById(id) {
  return state.runs.find((r) => r.id === id) || null
}

export function removeRun(id) {
  state.runs = state.runs.filter((run) => run.id !== id)
}

// The run blocking new sends in this conversation, or null.
export function activeRunOf(convoId) {
  return state.runs.find((r) => r.convoId === convoId && ['starting', 'waiting_for_clarification', 'running'].includes(r.status)) || null
}

// Land a run's final stream frame: status, then the report into the doc store, then the spend fold.
// The doc write precedes the caller's persist-and-forget, so a backend run is only ever forgotten after its report is the app's.
export function finishRun(run, frame) {
  Object.assign(run, {
    status: frame.status,
    phase: frame.phase,
    payload: frame.payload,
    spend: frame.spend ?? run.spend,
    checkpoint: frame.checkpoint ?? run.checkpoint,
    updatedAt: Date.now(),
  })
  const convo = state.conversations.find((c) => c.id === run.convoId)
  if (['done', 'partial'].includes(frame.status) && frame.payload && !run.reportDocId) {
    const doc = createDoc({
      name: `${frame.payload.name} report.md`,
      text: frame.payload.report.text,
      source: { kind: 'research', runId: run.id, convoId: run.convoId, messageId: run.resultMessageId },
    })
    run.reportDocId = doc.id
    if (convo) {
      ;(convo.docIds ??= []).push(doc.id)
      const msg = convo.messages.find((m) => m.id === run.resultMessageId)
      if (msg) {
        msg.docId = doc.id
        const ready = `Your "${frame.payload.name}" research document is ready.`
        msg.content = frame.payload.summary ? `${ready}\n\n${frame.payload.summary}` : ready
      }
    }
  }
  if (!run.spendLedgered) {
    foldRunUsage(frame.spend?.models)
    run.spendLedgered = true
  }
}
