// Pure client-run transitions. The component owns transport and this module owns durable state changes.
export function isNoSuchRun(error) {
  return error?.code === 'no_such_run'
}

export function applyStart(run, result) {
  const reset = !result.resumed
  Object.assign(run, {
    ...(reset ? { events: [], payload: null, spend: null, spendLedgered: false } : {}),
    ...(result.checkpoint !== undefined ? { checkpoint: result.checkpoint } : {}),
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
  return {
    id: current.serverId,
    brief: current.prepared.brief,
    answers: current.answers || {},
    checkpoint: current.checkpoint,
    restart_failed: current.retryFailed === true,
    goal: current.prepared.brief.objective,
    title: current.prepared.brief.deliverable,
    depth: current.settings.research_depth,
    models: {
      search: current.settings.research_search_model,
      note: current.settings.research_note_model,
      report: current.settings.research_report_model,
    },
  }
}

export function applyFailure(run, error) {
  Object.assign(run, { status: 'error', error: error.message, updatedAt: Date.now() })
}

export function applyCancel(run) {
  Object.assign(run, { status: 'cancelled', updatedAt: Date.now() })
}

export function applyPrepared(run, prepared) {
  const brief = prepared.brief || prepared
  run.prepared = { ...run.prepared, brief }
  run.preparationFailed = false
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
  Object.assign(run, { status: 'starting', error: null, updatedAt: Date.now() })
  return true
}
