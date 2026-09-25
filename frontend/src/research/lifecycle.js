// Pure client-run transitions. The coordinator owns transport and this module owns durable state changes.
export function isNoSuchRun(error) {
  return error?.code === 'no_such_run'
}

export function applyStart(run, result) {
  const reset = !result.resumed
  Object.assign(run, {
    ...(reset ? { events: [], payload: null, spend: null, spendLedgered: false } : {}),
    ...(result.checkpoint !== undefined ? { checkpoint: result.checkpoint } : {}),
    ...(result.payload !== undefined && result.payload !== null ? { payload: result.payload } : {}),
    retryFailed: false,
    serverId: result.id,
    status: result.status,
    phase: result.phase,
    error: null,
    updatedAt: Date.now(),
  })
  return reset
}

export function buildResearchStartBody(current) {
  const rawBrief = current.prepared?.brief || {}
  const rawScope = Array.isArray(rawBrief.scope) ? rawBrief.scope : typeof rawBrief.scope === 'string' ? [rawBrief.scope] : []
  const rawConstraints = Array.isArray(rawBrief.constraints) ? rawBrief.constraints : typeof rawBrief.constraints === 'string' ? [rawBrief.constraints] : []
  const scope = rawScope.filter((s) => typeof s === 'string' && s.trim()).map((s) => s.trim())
  const constraints = rawConstraints.filter((c) => typeof c === 'string' && c.trim()).map((c) => c.trim())
  const objective = (rawBrief.objective || current.prepared?.goal || 'Research').trim() || 'Research'
  const deliverable = (rawBrief.deliverable || rawBrief.objective || 'A sourced research brief').trim() || 'A sourced research brief'

  const questions = (Array.isArray(rawBrief.questions) ? rawBrief.questions : [])
    .filter((q) => q && typeof q === 'object' && typeof q.question === 'string' && q.question.trim())
    .slice(0, 3)
    .map((q) => ({
      question: q.question.trim(),
      reason: (q.reason || 'Clarification for research scope').trim(),
      default: (q.default || 'Standard').trim(),
    }))

  const brief = {
    objective,
    deliverable,
    scope: scope.length ? scope : ['The requested subject'],
    constraints: constraints.length ? constraints : ['Use current public sources'],
    questions,
  }

  const answers = {}
  for (const [k, v] of Object.entries(current.answers || {})) {
    if (typeof k === 'string' && k.trim() && typeof v === 'string' && v.trim()) {
      answers[k.trim()] = v.trim()
    }
  }
  for (const q of questions) {
    if (!answers[q.question]) {
      answers[q.question] = q.default
    }
  }

  const s = current.settings || {}
  const searchModel = (s.research_search_model || s.model || 'default').trim()
  const noteModel = (s.research_note_model || searchModel).trim()
  const reportModel = (s.research_report_model || searchModel).trim()

  return {
    id: current.serverId || current.id,
    brief,
    answers,
    checkpoint: current.checkpoint || null,
    restart_failed: current.retryFailed === true,
    goal: objective,
    title: deliverable,
    depth: s.research_depth ? Math.max(1, Math.min(Number(s.research_depth), 12)) : 5,
    models: {
      search: searchModel,
      note: noteModel,
      report: reportModel,
    },
  }
}

export function applyFailure(run, error) {
  Object.assign(run, { status: 'error', isPreparing: false, error: error.message, updatedAt: Date.now() })
}

export function applyCancel(run) {
  Object.assign(run, { status: 'cancelled', isPreparing: false, updatedAt: Date.now() })
}

export function applyPrepared(run, prepared) {
  if (prepared.action === 'answer') return 'answer'
  const brief = prepared.brief || prepared
  run.prepared = { ...run.prepared, brief }
  run.preparationFailed = false
  run.isPreparing = false
  run.error = null
  run.status = brief.questions?.length ? 'waiting_for_clarification' : 'starting'
  run.updatedAt = Date.now()
  return run.status
}

export function resumeWithCurrentModels(run, settings) {
  run.settings = { ...run.settings, ...settings }
  run.status = 'starting'
  run.retryFailed = true
  run.error = null
  run.updatedAt = Date.now()
  return run
}

// Do not erase replay state until the start response confirms this is a replacement backend run.
export function prepareReplacement(run, error) {
  if (!isNoSuchRun(error) || run.status === 'cancelled') return false
  Object.assign(run, { status: 'recovering', phase: 'recovering', error: null, updatedAt: Date.now() })
  return true
}
