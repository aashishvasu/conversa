// Deletion and regeneration lifecycle for a conversation tail.
// No Vue, network, or store imports: the owner hands in the cancel/release/run hooks so the selfcheck calls these directly.

// Rewind to the originating user turn and repeat it, using the same cancellation and cleanup as a fresh deletion.
export async function regenerate(convo, message, hooks) {
  const { preparing, runActive, cancelTurn, releaseImages, removeRun, routeResearch, runCompletion } = hooks
  if (preparing || runActive || !convo) return
  const idx = convo.messages.findIndex((m) => m.id === message.id)
  if (idx < 0) return
  let cut = idx
  if (message.role === 'assistant') {
    while (cut >= 0 && convo.messages[cut].role !== 'user') cut--
    if (cut < 0) return // no user turn before it, so nothing to regenerate from
  }
  const user = convo.messages[cut]
  for (const m of convo.messages.slice(cut + 1)) if (m.turnId) await cancelTurn(convo, m)
  const removed = convo.messages.slice(cut + 1).flatMap((m) => m.imageIds || [])
  convo.messages = convo.messages.filter((m, index) => index <= cut || m.role === 'system')
  releaseImages(removed)

  if (convo.mode === 'research') {
    user.mode = 'research'
    if (user.runId) removeRun(user.runId)
    delete user.runId
    void routeResearch(convo, user)
    return
  }
  user.mode = 'chat'
  if (user.runId) removeRun(user.runId)
  delete user.runId
  runCompletion(convo)
}

// Drop one message from the tail, cancelling its live turn and releasing its images first.
export async function removeMessage(convo, id, hooks) {
  const { cancelTurn, releaseImages } = hooks
  const message = convo.messages.find((m) => m.id === id)
  if (message?.turnId) await cancelTurn(convo, message)
  convo.messages = convo.messages.filter((m) => m.id !== id)
  releaseImages(message?.imageIds)
}

// A user-edited replacement is no longer the failed generation: drop its stale status and artifacts.
export function applyEdit(message, backup) {
  if (backup && (message.role !== backup.role || message.content !== backup.content)) {
    delete message.artifacts
    delete message.generation
  }
}