import { streamChat } from './api.js'

// Summarize a window of turns via the utility model. Stateless: the window is
// re-read in full on every refresh, so message edits/deletes can never desync it.
async function summarize(msgs, model) {
  const transcript = msgs.map((m) => `${m.role}: ${m.content}`).join('\n\n')
  const system =
    'You summarize part of a conversation. Preserve key facts, decisions, names, ' +
    'and anything needed to continue coherently. Output only the summary — no ' +
    'preamble, no commentary.'
  let out = ''
  await streamChat(
    {
      model,
      max_tokens: 1024,
      temperature: 0.3,
      system,
      messages: [{ role: 'user', content: `Summarize this conversation excerpt:\n${transcript}` }],
    },
    (t) => (out += t),
  )
  return out.trim()
}

// Refresh convo.memory in the background, fired after each assistant reply and left
// off the send path. Summarizes the summarize_n turns just above the send window.
// memoryCount records where coverage ends; buildPayload sends everything after it
// verbatim, so an in-flight or stale summary only widens the verbatim window and
// every turn stays covered by one or the other.
// Turns older than summarize_n + the send window drop out of context entirely, and
// use_recall retrieves them on demand. Rolling accumulation is the upgrade path.
const inflight = new Map() // convo.id -> seq; the last-started refresh wins
export async function refreshMemory(convo, settings) {
  if (!settings.use_memory) return
  const seq = (inflight.get(convo.id) || 0) + 1
  inflight.set(convo.id, seq)
  const turns = convo.messages.filter((m) => m.role !== 'system')
  const end = Math.max(0, turns.length - settings.num_messages_to_send)
  const start = Math.max(0, end - settings.summarize_n)
  const window = turns.slice(start, end)
  const summary = window.length ? await summarize(window, settings.utility_model) : ''
  if (inflight.get(convo.id) !== seq) return // superseded by a newer refresh
  convo.memory = summary
  convo.memoryCount = end
}
