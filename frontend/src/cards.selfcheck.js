// Run: node src/cards.selfcheck.js  — fails loudly if card logic breaks.
import assert from 'node:assert'
import { buildPayload, matchCards, parseTriggers } from './cards.js'

const cards = [
  { id: '1', triggers: 'dragon, wyrm', content: 'DRAGON_LORE' },
  { id: '2', triggers: 'castle', content: 'CASTLE_LORE' },
]

// whole-phrase, case-insensitive; content prefixed with the matched trigger phrase
assert.deepEqual(matchCards(cards, [{ role: 'user', content: 'The DRAGON flew' }], false), ['dragon: DRAGON_LORE'])
// word boundary: "dragonfly" must NOT trigger "dragon"
assert.deepEqual(matchCards(cards, [{ role: 'user', content: 'a dragonfly' }], false), [])
// multiple phrases of same card hit once (dedup); prefix is the first matching phrase
assert.deepEqual(matchCards(cards, [{ role: 'user', content: 'dragon and wyrm' }], false), ['dragon: DRAGON_LORE'])
// assistant scanned only when enabled
assert.deepEqual(matchCards(cards, [{ role: 'assistant', content: 'castle' }], false), [])
assert.deepEqual(matchCards(cards, [{ role: 'assistant', content: 'castle' }], true), ['castle: CASTLE_LORE'])

// buildPayload: system msg + activated card both land in system; window trims turns
const convo = {
  scanAssistant: false,
  cards,
  messages: [
    { role: 'system', content: 'You are a bard.' },
    { role: 'user', content: 'old turn' },
    { role: 'user', content: 'tell me of the dragon' },
  ],
}
const p = buildPayload(convo, {
  model: 'm', temperature: 1, max_tokens: 10, num_messages_to_send: 1, send_system_prompt: true,
})
assert.equal(p.messages.length, 1, 'window should keep only last turn')
assert.equal(p.messages[0].content, 'tell me of the dragon')
assert.ok(p.system.includes('You are a bard.') && p.system.includes('DRAGON_LORE'))

// send_system_prompt=false drops base system but keeps triggered cards
const p2 = buildPayload(convo, {
  model: 'm', temperature: 1, max_tokens: 10, num_messages_to_send: 5, send_system_prompt: false,
})
assert.ok(!p2.system.includes('bard') && p2.system.includes('DRAGON_LORE'))

// force override: 'include' sends without a trigger, 'skip' suppresses a matched trigger
const forced = [
  { id: 'i', triggers: 'never', content: 'ALWAYS', force: 'include' },
  { id: 's', triggers: 'dragon', content: 'SUPPRESSED', force: 'skip' },
]
assert.deepEqual(matchCards(forced, [{ role: 'user', content: 'a dragon' }], false), ['ALWAYS'])

// comma = OR of clauses; & inside a clause = AND of phrases
assert.deepEqual(parseTriggers(' a , b ,, c '), [['a'], ['b'], ['c']])
assert.deepEqual(parseTriggers('dragon & red, wyrm'), [['dragon', 'red'], ['wyrm']])
const andCards = [{ id: 'x', triggers: 'dragon & red, wyrm', content: 'RED_DRAGON' }]
assert.deepEqual(matchCards(andCards, [{ role: 'user', content: 'a dragon appears' }], false), [], 'partial AND clause must not fire')
assert.deepEqual(matchCards(andCards, [{ role: 'user', content: 'a red dragon' }], false), ['dragon & red: RED_DRAGON'])
assert.deepEqual(matchCards(andCards, [{ role: 'user', content: 'a wyrm' }], false), ['wyrm: RED_DRAGON'], 'OR clause fires alone')

// pinned turns lead the messages array and bypass the send-window limit; deduped vs the window
const pinConvo = {
  scanAssistant: false,
  cards: [],
  messages: [
    { id: 's', role: 'system', content: 'sys' },
    { id: 'a', role: 'user', content: 'pinned old', pinned: true },
    { id: 'b', role: 'user', content: 'filler' },
    { id: 'c', role: 'user', content: 'recent' },
  ],
}
const pp = buildPayload(pinConvo, {
  model: 'm', temperature: 1, max_tokens: 10, num_messages_to_send: 1, send_system_prompt: true,
})
assert.deepEqual(pp.messages.map((m) => m.content), ['pinned old', 'recent'], 'pinned first, then window')
// a pinned turn already inside the window is not duplicated
pinConvo.messages[3].pinned = true
const pp2 = buildPayload(pinConvo, {
  model: 'm', temperature: 1, max_tokens: 10, num_messages_to_send: 1, send_system_prompt: true,
})
assert.deepEqual(pp2.messages.map((m) => m.content), ['pinned old', 'recent'], 'no dup when pinned is recent')

// memory mode: window = turns after memoryCount; memory injected into system
const memConvo = {
  scanAssistant: false,
  cards: [],
  memory: 'EARLIER_SUMMARY',
  memoryCount: 1,
  messages: [
    { role: 'system', content: 'sys' },
    { role: 'user', content: 'old summarized turn' },
    { role: 'assistant', content: 'reply' },
    { role: 'user', content: 'recent' },
  ],
}
const mp = buildPayload(memConvo, {
  model: 'm', temperature: 1, max_tokens: 10, send_system_prompt: true, use_memory: true,
})
assert.equal(mp.messages.length, 2, 'memory window should drop the folded turn')
assert.equal(mp.messages[0].content, 'reply')
assert.ok(mp.system.includes('EARLIER_SUMMARY') && mp.system.includes('sys'))

console.log('cards selfcheck OK')
