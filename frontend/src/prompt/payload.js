// Request assembly: send window, lexical recall, and buildPayload. Pure functions, no Vue, so it runs in node.
import { effectiveCards, matchCards } from './cards.js'

// The turns sent verbatim this round.
// With memory on, that is everything past the summary's coverage (memoryCount), floored at num_messages_to_send.
// A summary that has not caught up, or deletes that shrank the list, therefore only widen the window.
// With memory off, it is the last num_messages_to_send turns.
// Exported so the UI can mark where the window starts.
export function sendWindow(convo, settings) {
  const turns = convo.messages.filter((m) => m.role !== 'system')
  if (!settings.use_memory) return turns.slice(-settings.num_messages_to_send)
  const cut = Math.min(convo.memoryCount || 0, Math.max(0, turns.length - settings.num_messages_to_send))
  return turns.slice(cut)
}

// --- Lexical recall -----------------------------------------------------------
// With use_recall on, the dropped turns most relevant to the latest user message are resent verbatim via the system prompt.
// Dropped means neither pinned nor inside the send window.
// This complements the lossy memory summary, and folding stays non-destructive, so edits and deletes can't desync it.
// Known ceiling: bag-of-words overlap over ASCII-only tokens, so no CJK, the same limitation as card matching in cards.js.
// Move to BM25 or embeddings if quality disappoints.

const RECALL_COUNT = 3

// Common words that carry no retrieval signal ("what was the..." shouldn't match everything).
// Tokens under 3 chars never tokenize, so none shorter are listed.
const STOPWORDS = new Set(
  ('the and you are was were not but for with this that have had has his her its from they will would could ' +
    'should there their been when where how why can just like about them then than your all any who did does ' +
    'say said skip get got out now one also very really what which while into onto some more most much such').split(' '),
)

function tokenize(s) {
  return new Set(((s || '').toLowerCase().match(/[a-z0-9]{3,}/g) || []).filter((w) => !STOPWORDS.has(w)))
}

// Top dropped turns by token overlap with the latest user message, returned chronologically as "role: content" strings.
// Empty when nothing overlaps.
export function recallMessages(convo, outgoing) {
  const query = tokenize(outgoing.findLast((m) => m.role === 'user')?.content)
  if (!query.size) return []
  const sent = new Set(outgoing.map((m) => m.id))
  return convo.messages
    .map((m, i) => ({ m, i }))
    .filter(({ m }) => m.role !== 'system' && !sent.has(m.id) && m.content)
    .map((x) => {
      const words = tokenize(x.m.content)
      let shared = 0
      for (const w of words) if (query.has(w)) shared++
      // normalize by length so long rambly turns don't always outrank short relevant ones
      return { ...x, shared, score: shared / Math.sqrt(words.size || 1) }
    })
    .filter((x) => x.shared > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, RECALL_COUNT)
    .sort((a, b) => a.i - b.i) // chronological reads better in the prompt
    .map((x) => `${x.m.role}: ${x.m.content}`)
}

// Build the {system, messages} payload for the API from a conversation + settings.
// System-role messages, memory, and activated cards all feed the top-level `system` param.
// Only user and assistant turns go in `messages`, which Anthropic requires.
//
// With memory on, the summary refreshes in the background after each reply (see memory.js).
// This reads whatever memory and memoryCount currently hold.
//
// `workspace` (optional) = { systemPrompt, cards, docIds } shared across its convos.
// Its prompt leads the system param and its cards merge ahead of the convo's own, so a convo card can refine a workspace card.
// `docs` = the resolved documents to send (attachedDocs in store.js: workspace docs first, then convo attachments, deduped).
// Docs are plain text sent whole, no chunking or retrieval.
// Score chunks with the recall tokenizer above if attached docs ever outgrow the context window.
export function buildPayload(convo, settings, workspace = null, docs = [], images = []) {
  const imageMap = new Map(images.map((image) => [image.id, image]))
  const turns = convo.messages.filter((m) => m.role !== 'system')
  const window = sendWindow(convo, settings)

  // Pinned turns bypass the send-window limit and lead the messages array, ahead of the window; dedup so a pinned turn that's also recent isn't sent twice.
  // Note: this leaves user/assistant alternation unenforced, so odd pin sets may be rejected.
  const inWindow = new Set(window.map((m) => m.id))
  const pinned = turns.filter((m) => m.pinned && !inWindow.has(m.id))
  const outgoing = [...pinned, ...window]

  const parts = []
  if (settings.send_system_prompt) {
    if (workspace?.systemPrompt?.trim()) parts.push(workspace.systemPrompt)
    for (const m of convo.messages) {
      if (m.role === 'system' && m.content.trim()) parts.push(m.content)
    }
  }
  // Docs are intentional shared context, like cards: sent even with base system off.
  for (const d of docs) {
    if (d.text) parts.push(`Reference document "${d.name}":\n${d.text}`)
  }

  // Cache breakpoint.
  // Everything pushed above holds still turn to turn; memory, recall and cards below all change.
  // Caching is prefix-match, so cards go last: a card firing mid-conversation rewrites only the uncached tail. system_param() in main.py turns the split into API blocks.
  const stable = parts.length

  if (settings.use_memory && convo.memory) {
    parts.push(`Summary of earlier conversation:\n${convo.memory}`)
  }
  if (settings.use_recall) {
    const recalled = recallMessages(convo, outgoing)
    if (recalled.length) parts.push(`Relevant earlier messages (verbatim, for reference):\n\n${recalled.join('\n\n')}`)
  }
  // Cards are intentional, trigger-gated context, injected even when the base system prompt is off.
  parts.push(...matchCards(effectiveCards(convo, workspace), window, convo.scanAssistant))

  // Array = [stable, volatile] for the backend to cache the first half, and a plain string when there is no stable half.
  // Messages stay uncached.
  // The send window drops turns off the front as it slides, so the message prefix shifts on most turns.
  // Revisit if pinning gets used heavily enough to hold the head of `outgoing` still.
  const system =
    settings.use_cache && stable
      ? [parts.slice(0, stable).join('\n\n'), parts.slice(stable).join('\n\n')]
      : parts.join('\n\n') || undefined

  return {
    system,
    // Contentless turns (a research placeholder awaiting its report) carry nothing and providers reject empty messages.
    messages: outgoing.map((m) => {
      const imageBlocks = (m.imageIds || []).map((id) => imageMap.get(id)).filter(Boolean).map((image) => ({
        type: 'image', source: { type: 'base64', media_type: image.media_type, data: image.data },
      }))
      const content = imageBlocks.length ? [...imageBlocks, ...(m.content ? [{ type: 'text', text: m.content }] : [])] : m.content
      return content ? { role: m.role, content } : null
    }).filter(Boolean),
    model: settings.model,
    temperature: settings.temperature,
    max_tokens: settings.max_tokens,
    effort: settings.effort,
  }
}
