import { streamChat } from '../api/client.js'
import { addConvoUsage, recordUsage } from '../state/usage.js'

// Shared transport for one-shot utility-model calls (memory refresh, titles, card gen, doc revise):
// accumulate the stream, tag spend against the owning convo or workspace, retry once on any error.
// Error surfacing stays with the caller, which alone knows whether the failure belongs in a toast (background) or inline next to the button (user-initiated).
export async function utilityCall(owner, payload) {
  const attempt = async () => {
    let out = ''
    await streamChat({ ...payload, allow_tools: false }, (t) => (out += t), null, null, (usage) => {
      addConvoUsage(owner, usage)
      recordUsage('utility', usage)
    })
    return out.trim()
  }
  try {
    return await attempt()
  } catch {
    return await attempt() // persistent failure rethrows to the caller
  }
}
