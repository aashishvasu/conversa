import { streamChat } from './api.js'

// Fold a batch of old messages into the running summary using the utility model.
async function summarize(existingMemory, foldMessages, model) {
  const transcript = foldMessages.map((m) => `${m.role}: ${m.content}`).join('\n\n')
  const system =
    'You maintain a concise running summary of a conversation. Preserve key facts, ' +
    'decisions, names, and anything needed to continue coherently. Output only the ' +
    'updated summary — no preamble, no commentary.'
  const user = existingMemory
    ? `Current summary:\n${existingMemory}\n\nNew messages to fold in:\n${transcript}\n\nReturn the updated summary.`
    : `Summarize this conversation so far:\n${transcript}`

  let out = ''
  await streamChat(
    { model, max_tokens: 1024, temperature: 0.3, system, messages: [{ role: 'user', content: user }] },
    (t) => (out += t),
  )
  return out.trim()
}

const charsFrom = (turns, start) =>
  turns.slice(start).reduce((n, m) => n + m.content.length, 0)

// If the unsummarized tail exceeds the threshold, fold its oldest messages into
// memory until the tail fits (always leaving at least one verbatim message).
// Mutates convo.memory / convo.memoryCount. No-op when memory is off or not needed.
export async function compressIfNeeded(convo, settings) {
  if (!settings.use_memory) return
  const turns = convo.messages.filter((m) => m.role !== 'system')

  // If history was truncated into the summarized region, the summary is stale — rebuild.
  if ((convo.memoryCount || 0) > turns.length) {
    convo.memory = ''
    convo.memoryCount = 0
  }

  let start = convo.memoryCount || 0
  let remaining = charsFrom(turns, start)
  const toFold = []
  while (remaining > settings.compression_threshold && turns.length - start > 1) {
    toFold.push(turns[start])
    remaining -= turns[start].content.length
    start++
  }
  if (!toFold.length) return

  convo.memory = await summarize(convo.memory || '', toFold, settings.utility_model)
  convo.memoryCount = start
}
