// Pure and node-runnable; a workspace never carries `mode`, so the override setters no-op there.

export function setCardForce(card, mode) {
  card.force = mode || null
}

function isWorkspace(owner) {
  return !owner || owner.mode === undefined
}

export function cardOverrideOf(owner, id) {
  return owner?.cardOverrides?.[id] || null
}

export function setCardOverride(owner, id, mode) {
  if (isWorkspace(owner)) return
  const overrides = (owner.cardOverrides ||= {})
  if (mode) overrides[id] = mode
  else delete overrides[id]
}

export function addCard(owner) {
  owner.cards.push({ id: crypto.randomUUID(), triggers: '', content: '' })
}

export function removeCard(owner, id) {
  owner.cards = owner.cards.filter((c) => c.id !== id)
}

// Move the dragged card next to the target and adopt the target's folder in one gesture.
export function reorderCard(owner, draggedId, targetId) {
  if (!draggedId || !targetId || draggedId === targetId) return
  const cards = owner.cards
  const moved = cards.splice(cards.findIndex((c) => c.id === draggedId), 1)[0]
  moved.path = cards.find((c) => c.id === targetId)?.path || ''
  cards.splice(cards.findIndex((c) => c.id === targetId), 0, moved)
}

export function insertGeneratedCards(owner, cards) {
  for (const c of cards) owner.cards.push({ id: crypto.randomUUID(), ...c })
}