// Pure chat-turn logic shared by the first connection, reattach, and utility calls.
// No Vue, network, or store imports, so the selfcheck calls these directly.

export function newDraft() {
  return { content: '', trace: [], artifacts: [], usage: null, error: null, done: false }
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
export function applyFrame(draft, frame) {
  if (frame.error) draft.error = frame.error
  else if (frame.text) draft.content += frame.text
  else if (frame.think) addTrace(draft.trace, 'thinking', frame.think)
  else if (frame.search) addTrace(draft.trace, 'search', frame.search)
  else if (frame.fetch) addTrace(draft.trace, 'fetch', frame.fetch)
  else if (frame.results) addTrace(draft.trace, 'results', frame.results)
  else if (frame.tool) addTrace(draft.trace, 'tool', frame.tool)
  else if (frame.artifact) draft.artifacts.push(frame.artifact)
  else if (frame.usage) draft.usage = frame.usage
  else if (frame.done) draft.done = true
  return draft
}

// outcome is done, error, stopped, or gone. Every outcome keeps the draft's text and releases the turn.
export function settleMessage(message, draft, outcome) {
  message.content = draft.content
  if (draft.artifacts.length) message.artifacts = [...draft.artifacts]
  if (outcome === 'error') {
    message.content += `${message.content ? '\n\n' : ''}> ⚠️ **Error:** ${draft.error}`
  }
  delete message.turnId
}

// A frame may only write into a message that is still in the store and still owns this turn.
export function turnStillWanted(conversations, convo, message, turnId) {
  return conversations.includes(convo) && convo.messages.includes(message) && message.turnId === turnId
}
