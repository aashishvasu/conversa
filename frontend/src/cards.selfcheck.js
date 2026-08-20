// Run: node src/cards.selfcheck.js.
// Fails loudly if card logic breaks.
import assert from 'node:assert'
import { buildPayload, matchCards, parseTriggers, recallMessages } from './cards.js'

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
const mSettings = {
  model: 'm', temperature: 1, max_tokens: 10, send_system_prompt: true, use_memory: true,
  num_messages_to_send: 2,
}
const mp = buildPayload(memConvo, mSettings)
assert.equal(mp.messages.length, 2, 'memory window should drop the summarized turn')
assert.equal(mp.messages[0].content, 'reply')
assert.ok(mp.system.includes('EARLIER_SUMMARY') && mp.system.includes('sys'))

// summary behind (memoryCount low): verbatim window widens, nothing falls in a gap
const behind = buildPayload({ ...memConvo, memoryCount: 0 }, mSettings)
assert.equal(behind.messages.length, 3, 'lagging summary must widen the verbatim window')
// memoryCount overshooting (e.g. after deletes): clamped so at least n turns still go verbatim
const overshoot = buildPayload({ ...memConvo, memoryCount: 5 }, mSettings)
assert.equal(overshoot.messages.length, 2, 'overshooting memoryCount must not empty the window')

// recall: dropped turns relevant to the latest user message are resent via system
const recallConvo = {
  scanAssistant: false,
  cards: [],
  messages: [
    { id: 's', role: 'system', content: 'sys' },
    { id: '1', role: 'user', content: 'my dragon is called Smaug' },
    { id: '2', role: 'assistant', content: 'Smaug, a fine dragon name.' },
    { id: '3', role: 'user', content: 'unrelated filler regarding weather' },
    { id: '4', role: 'assistant', content: 'sunny tomorrow' },
    { id: '5', role: 'user', content: 'remind me what my dragon is called?' },
  ],
}
const rSettings = { model: 'm', max_tokens: 10, num_messages_to_send: 1, send_system_prompt: true, use_recall: true }
const rp = buildPayload(recallConvo, rSettings)
assert.ok(rp.system.includes('Smaug'), 'recall should resend the relevant dropped turn')
assert.ok(!rp.system.includes('weather'), 'irrelevant dropped turns must not be recalled')
// recalled turns come back in chronological order
assert.ok(rp.system.indexOf('my dragon is called') < rp.system.indexOf('a fine dragon name'))
// off by default: same convo without use_recall sends no old turns
const rpOff = buildPayload(recallConvo, { ...rSettings, use_recall: false })
assert.ok(!rpOff.system.includes('Smaug'), 'recall off: dropped turns stay dropped')

// stopwords/short words alone never trigger recall ("what was the..." matches nothing)
const noSignal = recallMessages(recallConvo, [{ id: 'q', role: 'user', content: 'what was the it?' }])
assert.deepEqual(noSignal, [])
// turns already outgoing (in window or pinned) are never recalled
const dup = recallMessages(recallConvo, [recallConvo.messages[1], recallConvo.messages[5]])
assert.ok(!dup.some((s) => s.includes('called Smaug')), 'outgoing turn must not also be recalled')
// capped at 3, best-scoring first
const manyConvo = {
  messages: [
    ...['a', 'b', 'c', 'd'].map((id) => ({ id, role: 'user', content: `dragon fact ${id}` })),
    { id: 'q', role: 'user', content: 'dragon?' },
  ],
}
assert.equal(recallMessages(manyConvo, [manyConvo.messages.at(-1)]).length, 3)

// workspace: prompt leads system, docs sent whole, workspace cards precede convo cards
const ws = {
  id: 'w', name: 'W', systemPrompt: 'WS_PROMPT',
  cards: [{ id: 'wc', triggers: 'dragon', content: 'WS_CARD' }],
  docs: [{ id: 'd', name: 'lore.md', text: 'DOC_TEXT' }],
}
const wSettings = { model: 'm', max_tokens: 10, num_messages_to_send: 5, send_system_prompt: true }
const wp = buildPayload(convo, wSettings, ws)
assert.ok(wp.system.includes('WS_PROMPT') && wp.system.includes('You are a bard.'))
assert.ok(wp.system.indexOf('WS_PROMPT') < wp.system.indexOf('You are a bard.'), 'workspace prompt leads')
assert.ok(wp.system.includes('DOC_TEXT'), 'workspace docs are injected')
assert.ok(wp.system.indexOf('WS_CARD') < wp.system.indexOf('DRAGON_LORE'), 'workspace cards precede convo cards')
// send_system_prompt=false drops the workspace prompt but keeps docs and cards (intentional context)
const wp2 = buildPayload(convo, { ...wSettings, send_system_prompt: false }, ws)
assert.ok(!wp2.system.includes('WS_PROMPT') && wp2.system.includes('DOC_TEXT') && wp2.system.includes('WS_CARD'))
// no workspace arg: payload identical to before the feature
assert.equal(buildPayload(convo, wSettings).system, buildPayload(convo, wSettings, null).system)

// per-convo overrides of workspace cards: 'skip' mutes a triggered card, 'include' sends an untriggered one, and the shared card keeps its own force for other convos
const wsMulti = { ...ws, cards: [...ws.cards, { id: 'wq', triggers: 'kraken', content: 'WS_QUIET' }] }
const skipped = buildPayload({ ...convo, cardOverrides: { wc: 'skip' } }, wSettings, wsMulti)
assert.ok(!skipped.system.includes('WS_CARD'), 'convo override skips a workspace card')
assert.ok(skipped.system.includes('DRAGON_LORE'), 'convo cards unaffected by the override')
const forcedWs = buildPayload({ ...convo, cardOverrides: { wq: 'include' } }, wSettings, wsMulti)
assert.ok(forcedWs.system.includes('WS_QUIET'), 'convo override force-includes an untriggered workspace card')
assert.equal(wsMulti.cards[0].force, undefined, 'override never mutates the shared card')
assert.ok(buildPayload(convo, wSettings, wsMulti).system.includes('WS_CARD'), 'other convos keep the card')

// use_cache: system splits into [stable, volatile].
// Anything that changes turn to turn belongs in the second half, or it invalidates the cache on the turn it changes.
const cSettings = { ...wSettings, use_cache: true, use_memory: true }
const cached = buildPayload({ ...convo, memory: 'MEM', memoryCount: 0 }, cSettings, ws)
assert.ok(Array.isArray(cached.system) && cached.system.length === 2, 'use_cache splits system in two')
const [stableHalf, volatileHalf] = cached.system
assert.ok(stableHalf.includes('WS_PROMPT') && stableHalf.includes('DOC_TEXT'), 'workspace prompt + docs cached')
assert.ok(!stableHalf.includes('WS_CARD') && volatileHalf.includes('WS_CARD'), 'a firing card must not invalidate the cache')
assert.ok(!stableHalf.includes('MEM') && volatileHalf.includes('MEM'), 'the memory summary refreshes, so it stays uncached')
// off (the default) leaves the payload exactly as it was before the flag existed
assert.equal(typeof buildPayload(convo, wSettings, ws).system, 'string')
// nothing stable to cache: no breakpoint rather than an empty cached block
const noStable = buildPayload(convo, { ...cSettings, send_system_prompt: false })
assert.equal(typeof noStable.system, 'string', 'a bare convo has no cacheable prefix')
assert.ok(noStable.system.includes('DRAGON_LORE'))

console.log('cards selfcheck OK')
