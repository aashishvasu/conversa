// Card matching + system-prompt assembly. Pure functions, no Vue — testable in node.
//
// A card = { id, triggers, content }. `triggers` is a comma-separated string of
// phrases. A card activates if ANY of its phrases appears as a whole phrase
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

export function parseTriggers(triggers) {
  return (triggers || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

// Scans user messages always; assistant messages only if scanAssistant.
function scanText(messages, scanAssistant) {
  return messages
    .filter((m) => m.role === 'user' || (scanAssistant && m.role === 'assistant'))
    .map((m) => m.content)
    .join('\n')
}

function cardHits(card, text) {
  return parseTriggers(card.triggers).some((p) => wholePhraseMatch(text, p))
}

// Content of every activated card. One entry per card => dedup is automatic
// even when several of a card's phrases match.
export function matchCards(cards, messages, scanAssistant) {
  const text = scanText(messages, scanAssistant)
  return (cards || []).filter((c) => cardHits(c, text)).map((c) => c.content)
}

// Set of activated card ids — for live "active" indicators in the UI.
export function matchedCardIds(cards, messages, scanAssistant) {
  const text = scanText(messages, scanAssistant)
  return new Set((cards || []).filter((c) => cardHits(c, text)).map((c) => c.id))
}

// Build the {system, messages} payload for the API from a conversation + settings.
// System-role messages, memory, and activated cards all feed the top-level `system`
// param; only user/assistant turns go in `messages` (Anthropic requirement).
//
// With memory on, the window is everything not yet folded into memory (kept verbatim);
// compression (see memory.js) must run first so memoryCount/memory are current. With
// memory off, it's the last num_messages_to_send turns.
export function buildPayload(conversation, settings) {
  const turns = conversation.messages.filter((m) => m.role !== 'system')
  const window = settings.use_memory
    ? turns.slice(conversation.memoryCount || 0)
    : turns.slice(-settings.num_messages_to_send)

  // Pinned turns bypass the send-window limit and lead the messages array, ahead of the
  // window; dedup so a pinned turn that's also recent isn't sent twice.
  // Note: this doesn't enforce user/assistant alternation — odd pin sets may be rejected.
  const inWindow = new Set(window.map((m) => m.id))
  const pinned = turns.filter((m) => m.pinned && !inWindow.has(m.id))
  const outgoing = [...pinned, ...window]

  const parts = []
  if (settings.send_system_prompt) {
    for (const m of conversation.messages) {
      if (m.role === 'system' && m.content.trim()) parts.push(m.content)
    }
  }
  if (settings.use_memory && conversation.memory) {
    parts.push(`Summary of earlier conversation:\n${conversation.memory}`)
  }
  // Cards are intentional, trigger-gated context — injected even if base system is off.
  parts.push(...matchCards(conversation.cards, window, conversation.scanAssistant))

  return {
    system: parts.join('\n\n') || undefined,
    messages: outgoing.map((m) => ({ role: m.role, content: m.content })),
    model: settings.model,
    temperature: settings.temperature,
    max_tokens: settings.max_tokens,
  }
}
