// Pure chat-turn logic shared by the first connection, reattach, and utility calls.
// No Vue, network, or store imports, so the selfcheck calls these directly.

export function newDraft() {
  return { content: '', trace: [], artifacts: [], usage: null, error: null, outcome: null, finishReason: null }
}

// Accept the legacy string error and the additive {code,message,retryable} shape.
export function publicError(frame) {
  const raw = frame.error
  if (raw && typeof raw === 'object') {
    return {
      code: raw.code ?? frame.code ?? 'unknown',
      message: typeof raw.message === 'string' ? raw.message : '',
      retryable: raw.retryable ?? frame.retryable ?? false,
    }
  }
  return {
    code: frame.code ?? 'unknown',
    message: typeof raw === 'string' ? raw : '',
    retryable: frame.retryable ?? false,
  }
}

function traceText(value) {
  return typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value)
}

function addTrace(trace, type, value) {
  const last = trace.at(-1)
  if (type === 'thinking' && last?.type === 'thinking') last.text += value
  else if (type === 'results') trace.push({ type, links: value })
  else if (type === 'tool') {
    const { id, name, status, trace: detail } = value
    trace.push({ id, type, text: [name, status, traceText(detail)].filter(Boolean).join('\n') })
  } else trace.push({ type, text: value })
}

// One frame from the server, applied to the draft in place. The live marker carries no content.
// outcome is the single terminal discriminant: completed, output_limit, or failed.
export function applyFrame(draft, frame) {
  if (frame.error != null) {
    draft.error = publicError(frame)
    draft.outcome = 'failed'
  } else if (frame.text) draft.content += frame.text
  else if (frame.think) addTrace(draft.trace, 'thinking', frame.think)
  else if (frame.search) addTrace(draft.trace, 'search', frame.search)
  else if (frame.fetch) addTrace(draft.trace, 'fetch', frame.fetch)
  else if (frame.results) addTrace(draft.trace, 'results', frame.results)
  else if (frame.tool) addTrace(draft.trace, 'tool', frame.tool)
  else if (frame.artifact) draft.artifacts.push(frame.artifact)
  else if (frame.usage) draft.usage = frame.usage
  else if (frame.done) {
    draft.finishReason = frame.finishReason ?? null
    draft.outcome = frame.finishReason === 'output_limit' ? 'output_limit' : 'completed'
  }
  return draft
}

function generationStatus(outcome, draft) {
  if (outcome === 'error') return 'failed'
  if (outcome === 'stopped' || outcome === 'gone') return 'stopped'
  return draft.outcome === 'output_limit' ? 'output_limit' : 'completed'
}

// outcome is done, error, stopped, or gone. Every outcome keeps the draft's text and releases the turn.
// App-authored status lives in message.generation, never in the assistant body.
export function settleMessage(message, draft, outcome) {
  message.content = draft.content
  if (draft.artifacts.length) message.artifacts = [...draft.artifacts]
  message.generation = {
    status: generationStatus(outcome, draft),
    error: outcome === 'error' ? draft.error : null,
    finishReason: draft.finishReason ?? null,
  }
  delete message.turnId
}


// A frame may only write into a message that is still in the store and still owns this turn.
export function turnStillWanted(conversations, convo, message, turnId) {
  return conversations.includes(convo) && convo.messages.includes(message) && message.turnId === turnId
}
