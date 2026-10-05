// Research preparation uses the normal request context before an assistant placeholder exists.
// The preparer routes the request instead of answering it.
import { buildPayload } from './payload.js'

// Preparation sends the turns without their tool evidence.
// payload.js gates the artifact trust instruction on the same field, so stripping removes both.
function withoutArtifacts(convo) {
  return { ...convo, messages: (convo.messages || []).map((message) => (message.artifacts ? { ...message, artifacts: undefined } : message)) }
}

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
  const scoped = withoutArtifacts(convo)
  const payload = buildPayload(scoped, settings, workspace, docs, images)
  const pending = pendingPreparation(scoped)
  if (!pending) return { system: payload.system, messages: payload.messages }
  const context = continuation(pending)
  const system = Array.isArray(payload.system)
    ? [payload.system[0], [payload.system[1], context].filter(Boolean).join('\n\n')]
    : [payload.system, context].filter(Boolean).join('\n\n')
  return { system, messages: payload.messages }
}
