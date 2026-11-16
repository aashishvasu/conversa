// Pure request builders: the payload contract lives here so both the production
// call sites and the settings selfcheck exercise the same functions.
import { buildPayload } from './payload.js'
import { enabledTools } from '../state/settings.js'

// Chat turns fix their tool selection at assembly time; settings edits mid-stream
// affect the next turn, not this one.
export function chatRequest(convo, settings, workspace = null, docs = [], images = []) {
  return { ...buildPayload(convo, settings, workspace, docs, images), enabled_tools: enabledTools(settings) }
}

// Utility jobs stay tool-free: they never run tools, so the list is always empty.
export function utilityRequest(payload) {
  return { ...payload, enabled_tools: [] }
}
