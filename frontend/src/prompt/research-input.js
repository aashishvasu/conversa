// Research preparation uses the normal request context before an assistant placeholder exists.
// Keep this separate from the transport so tests can prove the preparer sees the same assembled request.
import { buildPayload } from './payload.js'

function pendingPreparation(convo) {
  // Only the latest assistant reply can leave a clarification pending; old exchanges stay history.
  const latestAssistant = convo.messages.findLast((message) => message.role === 'assistant')
  return latestAssistant?.researchPreparation ? latestAssistant : null
}

function continuation(preparation) {
  const { goal, questions = [] } = preparation.researchPreparation
  return [
    'Pending research preparation:',
    `Standalone goal: ${goal}`,
    questions.length ? `Questions awaiting an answer:\n${questions.map((question) => `- ${question}`).join('\n')}` : '',
  ].filter(Boolean).join('\n\n')
}

export function buildResearchInput(convo, settings, workspace = null, docs = [], images = []) {
  const payload = buildPayload(convo, settings, workspace, docs, images)
  const pending = pendingPreparation(convo)
  if (!pending) return { system: payload.system, messages: payload.messages }
  const context = continuation(pending)
  const system = Array.isArray(payload.system)
    ? [payload.system[0], [payload.system[1], context].filter(Boolean).join('\n\n')]
    : [payload.system, context].filter(Boolean).join('\n\n')
  return { system, messages: payload.messages }
}
