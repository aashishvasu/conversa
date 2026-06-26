import { streamChat } from './api.js'

// Generate/refresh a short title from the conversation's recent direction (not just its
// opening), seeding the existing title so a regen refines rather than starts over.
export async function generateTitle(convo, model) {
  const recent = convo.messages
    .filter((m) => m.role !== 'system')
    .slice(-6)
    .map((m) => `${m.role}: ${m.content}`)
    .join('\n')
  if (!recent) return ''

  const existing = convo.title && convo.title !== 'New conversation' ? convo.title : ''
  const user = existing
    ? `Current title: ${existing}\n\nRecent messages:\n${recent}\n\nGive an updated 3-6 word title reflecting where the conversation is now.`
    : `Recent messages:\n${recent}\n\nGive a 3-6 word title.`

  let out = ''
  await streamChat(
    {
      model,
      max_tokens: 20,
      temperature: 0.5,
      system: 'Reply with only a short conversation title — no quotes, no trailing punctuation, no preamble.',
      messages: [{ role: 'user', content: user }],
    },
    (t) => (out += t),
  )
  return out.trim().replace(/^["']|["']$/g, '').slice(0, 80)
}
