import { computed, ref } from 'vue'
import { prepareResearch } from '../api/client.js'
import { attachTurn, cancelTurn, startTurn, turnState } from '../chat/coordinator.js'
import { beginPreparation, endPreparation, getPreparationSignal, isPreparationCurrent, startRun } from './coordinator.js'
import { useStreamGuard } from '../composables/useStreamGuard.js'
import { tr } from '../i18n/index.js'
import { buildResearchInput } from '../prompt/research-input.js'
import { chatRequest } from '../prompt/request.js'
import { effectiveSettings, RESEARCH_KEYS } from '../state/settings.js'
import { attachedDocs, createRun, currentConversation, images, persistNow, workspaceOf } from '../state/store.js'

// Orchestrates chat completion and research routing for the viewed conversation.
// Chat turns run in the module-level chat coordinator, so `streaming` reflects whichever conversation is current.
// Called once per ChatPane mount; lifecycle hooks (wake lock, visibility) bind to that component.
export function useStreamOrchestration() {
  const preparing = ref(false)
  const liveOpen = ref(true)

  const pendingMessage = computed(() => currentConversation.value?.messages.find((m) => m.turnId) ?? null)
  const streaming = computed(() => !!pendingMessage.value)
  useStreamGuard(
    () => streaming.value,
    () => turnState(pendingMessage.value?.id)?.lastFrameAt,
    () => pendingMessage.value && attachTurn(currentConversation.value, pendingMessage.value),
  )

  // The placeholder carries its turnId and is saved before the request starts, so a reload mid-reply finds the pending turn.
  async function runCompletion(c) {
    const settings = effectiveSettings(c)
    // The tool selection is fixed here: settings edits mid-stream affect the next turn, not this one.
    const payload = chatRequest(c, settings, workspaceOf(c), attachedDocs(c), images.value)
    c.messages.push({ id: crypto.randomUUID(), role: 'assistant', content: '', turnId: crypto.randomUUID(), createdAt: Date.now() })
    const assistant = c.messages.at(-1)
    await persistNow()
    return startTurn(c, assistant, payload, settings)
  }

  // Preparation sees the exact normal-chat context.
  // Regeneration passes the existing user message back through this same decision instead of inventing a second turn.
  async function routeResearch(c, user) {
    preparing.value = true
    const chatSettings = effectiveSettings(c)
    const input = buildResearchInput(c, chatSettings, workspaceOf(c), attachedDocs(c), images.value)
    const generation = beginPreparation(c.id)
    try {
      await persistNow()
      const signal = getPreparationSignal(c.id)
      const prepared = await prepareResearch({ ...input, model: chatSettings.model }, signal)
      if (!isPreparationCurrent(c.id, generation) || c.mode !== 'research') {
        user.mode = 'chat'
        await persistNow()
        runCompletion(c)
        return
      }
      if (prepared.action === 'answer') {
        user.mode = 'chat'
        await persistNow()
        runCompletion(c)
        return
      }
      const rawBrief = prepared.brief || { objective: prepared.goal, deliverable: prepared.goal }
      const scope = Array.isArray(rawBrief.scope) && rawBrief.scope.length ? rawBrief.scope : ['The requested subject']
      const constraints = Array.isArray(rawBrief.constraints) && rawBrief.constraints.length ? rawBrief.constraints : ['Use current public sources']
      const brief = {
        objective: (rawBrief.objective || 'Research').trim(),
        deliverable: (rawBrief.deliverable || 'A sourced research brief').trim(),
        scope,
        constraints,
        questions: Array.isArray(rawBrief.questions) ? rawBrief.questions : [],
      }
      const placeholder = { id: crypto.randomUUID(), role: 'assistant', content: '', mode: 'research', createdAt: Date.now() }
      const researchSettings = effectiveSettings(c, RESEARCH_KEYS)
      const run = createRun(c, user.id, placeholder.id, { ...input, model: chatSettings.model }, { brief }, researchSettings)
      user.runId = placeholder.runId = run.id
      c.messages.push(placeholder)
      if (c.title === tr('sidebar.newConversation')) c.title = user.content.slice(0, 60)
      await persistNow()
      if (!brief.questions?.length) {
        void startRun(run)
      }
    } catch (error) {
      if (error?.name === 'AbortError' || !isPreparationCurrent(c.id, generation)) {
        return
      }
      const placeholder = { id: crypto.randomUUID(), role: 'assistant', content: '', mode: 'research', createdAt: Date.now() }
      const run = createRun(c, user.id, placeholder.id, { ...input, model: chatSettings.model }, { brief: { objective: user.content, deliverable: user.content, scope: ['The requested subject'], constraints: ['Use current public sources'], questions: [] } }, effectiveSettings(c, RESEARCH_KEYS))
      run.status = 'error'
      run.preparationFailed = true
      run.error = error.message
      user.runId = placeholder.runId = run.id
      c.messages.push(placeholder)
      await persistNow()
    } finally {
      endPreparation(c.id, generation)
      preparing.value = false
    }
  }

  async function sendResearch(c, text) {
    const user = { id: crypto.randomUUID(), role: 'user', content: text, mode: 'research', createdAt: Date.now() }
    c.messages.push(user)
    await routeResearch(c, user)
  }

  function stop() {
    if (pendingMessage.value) cancelTurn(currentConversation.value, pendingMessage.value)
  }

  return { streaming, preparing, liveOpen, runCompletion, routeResearch, sendResearch, stop }
}
