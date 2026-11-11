import { discardChatTurn, startChatTurn } from '../api/client.js'
import { applyFrame, newDraft } from '../chat/turn.js'
import { tr } from '../i18n/index.js'
import { utilityRequest } from '../prompt/request.js'
import { addConvoUsage, recordUsage } from '../state/usage.js'

// Shared transport for one-shot utility-model calls (memory refresh, titles, card gen, doc revise):
// accumulate the stream, tag spend against the owning convo or workspace, retry once on any error.
// Each attempt is its own server turn, never reattached, and discarded once read.
// Error surfacing stays with the caller, which alone knows whether the failure belongs in a toast (background) or inline next to the button (user-initiated).
export async function utilityCall(owner, payload) {
  const attempt = async () => {
    const turnId = crypto.randomUUID()
    const draft = newDraft()
    try {
      await startChatTurn(turnId, utilityRequest(payload), (frame) => applyFrame(draft, frame), null)
    } finally {
      discardChatTurn(turnId)
    }
    if (draft.usage) {
      addConvoUsage(owner, draft.usage)
      recordUsage('utility', draft.usage)
    }
    if (draft.error) throw new Error(draft.error)
    if (!draft.done) throw new Error(tr('chat.replyInterrupted'))
    return draft.content.trim()
  }
  try {
    return await attempt()
  } catch {
    return await attempt() // persistent failure rethrows to the caller
  }
}
