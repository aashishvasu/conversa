// Run: node src/selfchecks/cards.selfcheck.js.
// Fails loudly if card logic breaks.
import assert from 'node:assert'
import { matchCards, parseGeneratedCards, parseTriggers } from '../prompt/cards.js'

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

// parseGeneratedCards: tolerant of fences and prose, strict on shape
const gen = parseGeneratedCards('```json\n[{"triggers": "a, b", "content": " X "}, {"triggers": "c", "content": ""}]\n```')
assert.deepEqual(gen, [{ triggers: 'a, b', content: 'X' }], 'trims fields, drops empty-content cards')
assert.deepEqual(parseGeneratedCards('Here you go: [{"triggers": "t", "content": "body [1]"}] hope that helps'), [{ triggers: 't', content: 'body [1]' }], 'survives surrounding prose and brackets in content')
assert.throws(() => parseGeneratedCards('no json here'), /card_list_missing/)
assert.throws(() => parseGeneratedCards('[{"triggers": 1, "content": 2}]'), /cards_unusable/)

console.log('cards selfcheck OK')
