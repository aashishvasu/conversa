import { completeChat, discardChatTurn, startChatTurn } from '../api/client.js'
import { applyFrame, newDraft } from '../chat/turn.js'
import { tr } from '../i18n/index.js'
import { utilityRequest } from '../prompt/request.js'
import { addConvoUsage, recordUsage } from '../state/usage.js'

// Shared transports for one-shot utility-model calls: tag spend against the owning convo or workspace, retry once on any error.
// Error surfacing stays with the caller, which alone knows whether the failure belongs in a toast (background) or inline next to the button (user-initiated).

function recordSpend(owner, usage) {
  if (!usage) return
  addConvoUsage(owner, usage)
  recordUsage('utility', usage)
}

async function retryOnce(attempt) {
  try {
    return await attempt()
  } catch {
    return await attempt() // persistent failure rethrows to the caller
  }
}

// Memory refresh, card gen, doc revise: each attempt is its own detached server turn, never reattached, and discarded once read.
export function utilityCall(owner, payload) {
  return retryOnce(async () => {
    const turnId = crypto.randomUUID()
    const draft = newDraft()
    try {
      await startChatTurn(turnId, utilityRequest(payload), (frame) => applyFrame(draft, frame), null)
    } finally {
      discardChatTurn(turnId)
    }
    recordSpend(owner, draft.usage)
    if (draft.error) throw new Error(draft.error)
    if (!draft.done) throw new Error(tr('chat.replyInterrupted'))
    return draft.content.trim()
  })
}

// Titles: one request to /api/complete, lost if the connection drops, which the retry covers.
export function utilityComplete(owner, payload) {
  return retryOnce(async () => {
    const { text, usage } = await completeChat(utilityRequest(payload))
    recordSpend(owner, usage)
    return text.trim()
  })
}
