// Card matching + system-prompt assembly. Pure functions, no Vue — testable in node.
//
// A card = { id, triggers, content }. `triggers` is a comma-separated string of
// clauses; comma = OR, `&` inside a clause = AND ("dragon & red, wyrm" fires on
// wyrm, or on dragon and red together). Each phrase must appear whole
// (case-insensitive, word-boundary) in the scanned text. Activated cards inject
// their content into the system prompt exactly once each.

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// Whole-phrase, case-insensitive. "dragon" hits "the dragon flew", not "dragonfly".
// \b is an ASCII word boundary — fine for typical phrases, not CJK text.
function wholePhraseMatch(text, phrase) {
  if (!phrase) return false
  return new RegExp(`\\b${escapeRegex(phrase)}\\b`, 'i').test(text)
}

// Returns clauses: [['dragon','red'],['wyrm']] for "dragon & red, wyrm".
// A literal & inside a phrase becomes an AND of its words — looser
// match, not broken; quoting syntax only if someone actually hits it.
export function parseTriggers(triggers) {
  return (triggers || '')
    .split(',')
    .map((clause) => clause.split('&').map((p) => p.trim()).filter(Boolean))
    .filter((c) => c.length)
}

// Scans user messages always; assistant messages only if scanAssistant.
function scanText(messages, scanAssistant) {
  return messages
    .filter((m) => m.role === 'user' || (scanAssistant && m.role === 'assistant'))
    .map((m) => m.content)
    .join('\n')
}

function cardHits(card, text) {
  return parseTriggers(card.triggers).some((clause) => clause.every((p) => wholePhraseMatch(text, p)))
}

// First clause that fully matched, joined for display ("dragon & red"), or null.
// Null only for force-include cards, which send with no matching clause.
function firstHit(card, text) {
  const clause = parseTriggers(card.triggers).find((c) => c.every((p) => wholePhraseMatch(text, p)))
  return clause ? clause.join(' & ') : null
}

// Whether a card sends this turn. `force` overrides triggers: 'include' always
// sends, 'skip' never does; anything else falls back to trigger matching.
function cardActive(card, text) {
  if (card.force === 'include') return true
  if (card.force === 'skip') return false
  return cardHits(card, text)
}

// Content of every activated card, prefixed with the phrase that triggered it
// ("phrase: content") so the model sees why the card fired. Force-include cards
// with no matching phrase send bare content. One entry per card => dedup is automatic.
export function matchCards(cards, messages, scanAssistant) {
  const text = scanText(messages, scanAssistant)
  return (cards || []).filter((c) => cardActive(c, text)).map((c) => {
    const hit = firstHit(c, text)
    return hit ? `${hit}: ${c.content}` : c.content
  })
}

// Set of activated card ids — for live "active" indicators in the UI.
export function matchedCardIds(cards, messages, scanAssistant) {
  const text = scanText(messages, scanAssistant)
  return new Set((cards || []).filter((c) => cardActive(c, text)).map((c) => c.id))
}

// Build the {system, messages} payload for the API from a conversation + settings.
// System-role messages, memory, and activated cards all feed the top-level `system`
// param; only user/assistant turns go in `messages` (Anthropic requirement).
//
// With memory on, the window is everything not yet folded into memory (kept verbatim);
// compression (see memory.js) must run first so memoryCount/memory are current. With
// memory off, it's the last num_messages_to_send turns.
export function buildPayload(convo, settings) {
  const turns = convo.messages.filter((m) => m.role !== 'system')
  const window = settings.use_memory
    ? turns.slice(convo.memoryCount || 0)
    : turns.slice(-settings.num_messages_to_send)

  // Pinned turns bypass the send-window limit and lead the messages array, ahead of the
  // window; dedup so a pinned turn that's also recent isn't sent twice.
  // Note: this doesn't enforce user/assistant alternation — odd pin sets may be rejected.
  const inWindow = new Set(window.map((m) => m.id))
  const pinned = turns.filter((m) => m.pinned && !inWindow.has(m.id))
  const outgoing = [...pinned, ...window]

  const parts = []
  if (settings.send_system_prompt) {
    for (const m of convo.messages) {
      if (m.role === 'system' && m.content.trim()) parts.push(m.content)
    }
  }
  if (settings.use_memory && convo.memory) {
    parts.push(`Summary of earlier conversation:\n${convo.memory}`)
  }
  // Cards are intentional, trigger-gated context — injected even if base system is off.
  parts.push(...matchCards(convo.cards, window, convo.scanAssistant))

  return {
    system: parts.join('\n\n') || undefined,
    messages: outgoing.map((m) => ({ role: m.role, content: m.content })),
    model: settings.model,
    temperature: settings.temperature,
    max_tokens: settings.max_tokens,
  }
}
