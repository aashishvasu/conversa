// Run: node src/selfchecks/cardMutations.selfcheck.js.
import assert from 'node:assert'
import {
  addCard,
  cardOverrideOf,
  insertGeneratedCards,
  removeCard,
  reorderCard,
  setCardForce,
  setCardOverride,
} from '../prompt/cardMutations.js'

const conversation = (cards = []) => ({ id: 'c', mode: 'chat', title: 't', cards })
// A workspace-shaped owner that carries a conversation-like workspaceId is the imported-explain case: it must still never gain cardOverrides.
const workspace = (cards = []) => ({ id: 'w', name: 'n', messages: [], cards, docIds: [], workspaceId: 'x' })

const shared = [
  { id: 'a', triggers: 'one', content: 'A', path: 'docs' },
  { id: 'b', triggers: 'two', content: 'B', path: '' },
  { id: 'c', triggers: 'three', content: 'C', path: 'docs' },
]

// add / reorder / remove / force are legitimately shared and behave identically on a conversation and a workspace.
{
  for (const make of [conversation, workspace]) {
    const owner = make(shared.map((c) => ({ ...c })))
    addCard(owner)
    assert.equal(owner.cards.length, 4, `${make.name}: add appends one blank card`)
    const blank = owner.cards[3]
    assert.equal(blank.triggers, '', `${make.name}: the new card is blank`)
    assert.equal(blank.content, '', `${make.name}: the new card has no content`)
    assert.ok(blank.id, `${make.name}: the new card gets an id`)

    reorderCard(owner, 'c', 'a')
    assert.deepEqual(owner.cards.map((ca) => ca.id), ['c', 'a', 'b', blank.id], `${make.name}: the dragged card lands next to its target`)
    assert.equal(owner.cards[0].path, 'docs', `${make.name}: the dragged card adopts the target's folder`)

    setCardForce(owner.cards[1], 'skip')
    assert.equal(owner.cards[1].force, 'skip', `${make.name}: force is set`)
    setCardForce(owner.cards[1], '')
    assert.equal(owner.cards[1].force, null, `${make.name}: clearing force clamps it to null`)
    assert.equal(owner.cards[0].force, undefined, `${make.name}: force lives on the card alone`)

    removeCard(owner, 'b')
    assert.deepEqual(owner.cards.map((ca) => ca.id), ['c', 'a', blank.id], `${make.name}: remove drops the card by id`)
  }
}

// Override set/clear is conversation-only; a workspace never gains the field, no matter what is handed in.
{
  const c = conversation([{ id: 'w1', triggers: '', content: 'shared' }])
  setCardOverride(c, 'w1', 'include')
  assert.equal(cardOverrideOf(c, 'w1'), 'include', 'a conversation carries a per-convo override')
  setCardOverride(c, 'w1', '')
  assert.equal(cardOverrideOf(c, 'w1'), null, 'clearing an override removes the key')
  assert.deepEqual(c.cardOverrides, {}, 'an empty override map stays empty')

  const w = workspace(shared)
  setCardOverride(w, 'a', 'include')
  setCardOverride(w, 'b', 'skip')
  assert.ok(!Object.hasOwn(w, 'cardOverrides'), 'a workspace never gains cardOverrides')
  assert.equal(cardOverrideOf(w, 'a'), null, 'a workspace reports no overrides')
}

// Generated cards are inserted with a fresh id each, preserving their parsed shape.
{
  const c = conversation()
  const parsed = [{ triggers: 't1', content: 'C1' }, { triggers: 't2', content: 'C2' }]
  insertGeneratedCards(c, parsed)
  assert.equal(c.cards.length, 2, 'each generated card is inserted')
  assert.deepEqual(c.cards.map((ca) => ca.triggers), ['t1', 't2'], 'generated triggers land in order')
  assert.deepEqual(c.cards.map((ca) => ca.content), ['C1', 'C2'], 'generated content lands intact')
  assert.ok(c.cards.every((ca) => ca.id), 'every generated card carries its own id')
  const w = workspace()
  insertGeneratedCards(w, parsed)
  assert.equal(w.cards.length, 2, 'generated cards insert into a workspace the same way')
}