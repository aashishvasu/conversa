import { buildPayload } from './payload.js'

// Preparation sends the turns without their tool evidence.
// payload.js gates the artifact trust instruction on the same field, so stripping removes both.
function withoutArtifacts(convo) {
  return { ...convo, messages: (convo.messages || []).map((message) => (message.artifacts ? { ...message, artifacts: undefined } : message)) }
}

export function buildResearchInput(convo, settings, workspace = null, docs = [], images = []) {
  const scoped = withoutArtifacts(convo)
  const payload = buildPayload(scoped, settings, workspace, docs, images)
  return { system: payload.system, messages: payload.messages }
}
