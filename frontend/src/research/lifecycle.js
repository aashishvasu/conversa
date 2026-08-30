// Pure client-run transitions. The component owns transport and this module owns durable state changes.
export function isNoSuchRun(error) {
  return error?.code === 'no_such_run'
}

export function applyStart(run, result) {
  const reset = !result.resumed
  Object.assign(run, {
    ...(reset ? { events: [], payload: null, spend: null, spendLedgered: false } : {}),
    serverId: result.id,
    status: result.status,
    phase: result.phase,
    error: null,
    updatedAt: Date.now(),
  })
  return reset
}

export function applyFailure(run, error) {
  Object.assign(run, { status: 'error', error: error.message, updatedAt: Date.now() })
}

// Do not erase replay state until the start response confirms this is a replacement backend run.
export function prepareReplacement(run, error) {
  if (!isNoSuchRun(error)) return false
  Object.assign(run, { status: 'starting', error: null, updatedAt: Date.now() })
  return true
}
