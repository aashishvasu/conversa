// Card matching. Pure functions, no Vue, so it runs in node.
//
// A card = { id, triggers, content }.
// `triggers` is a comma-separated string of clauses: comma = OR, `&` inside a clause = AND.
// So "dragon & red, wyrm" fires on wyrm, or on dragon and red together.
// Each phrase must appear whole in the scanned text, case-insensitive and on word boundaries.
// Activated cards inject their content into the system prompt exactly once each.

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// Whole-phrase, case-insensitive.
// "dragon" hits "the dragon flew", not "dragonfly". \b is an ASCII word boundary: right for typical phrases, wrong for CJK text.
function wholePhraseMatch(text, phrase) {
  if (!phrase) return false
  return new RegExp(`\\b${escapeRegex(phrase)}\\b`, 'i').test(text)
}

// Returns clauses: [['dragon','red'],['wyrm']] for "dragon & red, wyrm".
// A literal & inside a phrase parses as AND between its words.
// Add quoting syntax if someone actually hits it.
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

// Whether a card sends this turn.
// `force` overrides triggers: 'include' always sends, 'skip' never does; anything else falls back to trigger matching.
function cardActive(card, text) {
  if (card.force === 'include') return true
  if (card.force === 'skip') return false
  return cardHits(card, text)
}

// Content of every activated card, prefixed with the phrase that triggered it ("phrase: content") so the model sees why the card fired.
// Force-include cards with no matching phrase send bare content.
// One entry per card => dedup is automatic.
export function matchCards(cards, messages, scanAssistant) {
  const text = scanText(messages, scanAssistant)
  return (cards || []).filter((c) => cardActive(c, text)).map((c) => {
    const hit = firstHit(c, text)
    return hit ? `${hit}: ${c.content}` : c.content
  })
}

// Set of activated card ids, for the live "active" indicators in the UI.
export function matchedCardIds(cards, messages, scanAssistant) {
  const text = scanText(messages, scanAssistant)
  return new Set((cards || []).filter((c) => cardActive(c, text)).map((c) => c.id))
}

// Workspace cards merged ahead of the convo's own, so a convo card can refine a workspace one. convo.cardOverrides[cardId] = 'include' | 'skip' replaces that card's force for this convo; an absent key keeps the shared card's own force and triggers.
// The copy is per-call, so the override stays on the convo that set it.
export function effectiveCards(convo, workspace) {
  const overrides = convo?.cardOverrides || {}
  return [
    ...(workspace?.cards || []).map((c) => (overrides[c.id] ? { ...c, force: overrides[c.id] } : c)),
    ...(convo?.cards || []),
  ]
}

// System prompt for the card builder in CardsPanel: utility model turns pasted text into trigger cards.
export const CARDGEN_SYSTEM =
  'You convert text into trigger cards for a chat app. A card is {"triggers": "...", "content": "..."}.\n' +
  'Trigger syntax: comma separates alternatives (OR); "&" joins words that must all appear (AND). ' +
  'Example: "dragon & red, wyrm" fires on "wyrm", or on "dragon" and "red" together. ' +
  'Triggers match case-insensitively as substrings of the last few conversation messages.\n' +
  'Split the text into self-contained topical chunks. Give each chunk the triggers someone would naturally type when that chunk becomes relevant. ' +
  'Prefer chunks that apply occasionally over always-on material, but every part of the source text must land in exactly one card\'s content: never drop anything.\n' +
  'Output only a JSON array of {"triggers", "content"} objects. No code fences, no commentary.'

// Parse the card builder's reply: tolerate fences or prose around the array, keep only well-shaped cards.
export function parseGeneratedCards(text) {
  const start = text.indexOf('[')
  const end = text.lastIndexOf(']')
  if (start === -1 || end <= start) throw new Error('No card list in model output')
  const cards = JSON.parse(text.slice(start, end + 1))
    .filter((c) => c && typeof c.triggers === 'string' && typeof c.content === 'string' && c.content.trim())
    .map((c) => ({ triggers: c.triggers.trim(), content: c.content.trim() }))
  if (!cards.length) throw new Error('No usable cards in model output')
  return cards
}
