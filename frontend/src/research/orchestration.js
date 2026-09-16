import { computed, ref } from 'vue'
import { prepareResearch, streamChat } from '../api/client.js'
import { useStreamGuard } from '../composables/useStreamGuard.js'
import { refreshMemory } from '../jobs/memory.js'
import { generateTitle } from '../jobs/titles.js'
import { tr } from '../i18n/index.js'
import { buildPayload } from '../prompt/payload.js'
import { buildResearchInput } from '../prompt/research-input.js'
import { effectiveSettings, enabledTools, RESEARCH_KEYS } from '../state/settings.js'
import { addConvoUsage, recordUsage } from '../state/usage.js'
import { attachedDocs, createRun, currentConversation, images, persistNow, workspaceOf } from '../state/store.js'
import { notify } from '../utils/notify.js'
import { showThinkingAndSearch } from '../utils/prefs.js'

function clarificationContent(questions) {
  return questions.length
    ? `Before I research this, please answer:\n\n${questions.map((q) => `- ${q}`).join('\n')}`
    : 'Before I research this, please provide the missing detail.'
}

// Orchestrates chat completion and research routing.
// Both share the streaming/preparing flags and the live trace, so they live together.
// Called once per ChatPane mount; lifecycle hooks (wake lock, visibility) bind to that component.
export function useStreamOrchestration() {
  const streaming = ref(false)
  const preparing = ref(false)
  const liveTrace = ref([])
  const streamId = ref(null)
  const liveOpen = ref(true)
  let controller = null

  const showTrace = computed(() => currentConversation.value?.showThinkingAndSearch ?? showThinkingAndSearch.value)
  const guard = useStreamGuard(() => streaming.value, () => controller?.abort())

  function traceText(value) {
    return typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value)
  }

  function addTrace(type, value) {
    const last = liveTrace.value.at(-1)
    if (type === 'thinking' && last?.type === 'thinking') last.text += value
    else if (type === 'results') liveTrace.value.push({ type, links: value })
    else if (type === 'tool') {
      const { id, name, status, trace } = value
      liveTrace.value.push({ id, type, text: [name, status, traceText(trace)].filter(Boolean).join('\n') })
    } else liveTrace.value.push({ type, text: value })
  }

  async function runCompletion(c) {
    const settings = effectiveSettings(c)
    streaming.value = true
    controller = new AbortController()
    guard.start()
    let assistant = null
    try {
      // Snapshot the payload before pushing the empty assistant placeholder.
      // The tool selection is fixed here: settings edits mid-stream affect the next turn, not this one.
      const payload = { ...buildPayload(c, settings, workspaceOf(c), attachedDocs(c), images.value), enabled_tools: enabledTools(settings) }
      c.messages.push({ id: crypto.randomUUID(), role: 'assistant', content: '', createdAt: Date.now() })
      assistant = c.messages.at(-1) // reactive proxy, so streamed tokens render live
      liveTrace.value = []
      streamId.value = assistant.id
      await streamChat(payload, (t) => {
        guard.heartbeat()
        assistant.content += t
      }, controller.signal, (type, value) => {
        guard.heartbeat()
        if (!showTrace.value) return
        addTrace(type, value)
      }, (usage) => {
        addConvoUsage(c, usage)
        recordUsage('chat', usage)
      }, (artifact) => {
        // Durable provenance attaches to the message regardless of trace visibility; persistNow below saves it with the reply.
        (assistant.artifacts ||= []).push(artifact)
      })
      if (c.title === tr('sidebar.newConversation')) {
        try {
          const t = await generateTitle(c, settings.utility_model)
          if (t) c.title = t
        } catch (e) {
          notify({ key: 'utility:title', severity: 'warning', text: tr('chat.titleFailed', { error: e.message }) })
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError' && assistant) {
        assistant.content += `${assistant.content ? '\n\n' : ''}> ⚠️ **Error:** ${e.message}`
      } else if (e.name !== 'AbortError') {
        notify({ key: 'chat', text: e.message, foreground: true })
      }
    } finally {
      streaming.value = false
      guard.end()
      // Refresh memory in the background, off the send path.
      // The key dedupes: a persistently failing utility model refreshes one toast instead of stacking.
      refreshMemory(c, settings).catch((e) => notify({ key: 'utility:memory', severity: 'warning', text: tr('chat.memoryFailed', { error: e.message }) }))
      persistNow() // don't let a quick reload lose the completed message
    }
  }

  // Preparation sees the exact normal-chat context.
  // Regeneration passes the existing user message back through this same decision instead of inventing a second turn.
  async function routeResearch(c, user) {
    preparing.value = true
    const chatSettings = effectiveSettings(c)
    const input = buildResearchInput(c, chatSettings, workspaceOf(c), attachedDocs(c), images.value)
    try {
      await persistNow()
      const prepared = await prepareResearch({ ...input, model: chatSettings.model })
      if (prepared.action === 'answer') {
        runCompletion(c)
        return
      }
      if (prepared.action === 'clarify') {
        c.messages.push({
          id: crypto.randomUUID(),
          role: 'assistant',
          content: clarificationContent(prepared.questions),
          // Normal text stays visible to preparation; this preserves the original standalone intent for export/debugging.
          researchPreparation: { originalRequest: user.content, goal: prepared.goal, questions: prepared.questions },
          createdAt: Date.now(),
        })
        await persistNow()
        return
      }
      const placeholder = { id: crypto.randomUUID(), role: 'assistant', content: '', mode: 'research', createdAt: Date.now() }
      const researchSettings = effectiveSettings(c, RESEARCH_KEYS)
      const run = createRun(c, user.id, placeholder.id, input, prepared, researchSettings)
      user.runId = placeholder.runId = run.id
      c.messages.push(placeholder)
      if (c.title === tr('sidebar.newConversation')) c.title = user.content.slice(0, 60)
      // ResearchBlock owns the one initial POST after this durable record reaches IndexedDB.
      await persistNow()
    } catch (error) {
      notify({ key: 'research:prepare', text: error.message, foreground: true })
    } finally {
      preparing.value = false
    }
  }

  async function sendResearch(c, text) {
    const user = { id: crypto.randomUUID(), role: 'user', content: text, mode: 'research', createdAt: Date.now() }
    c.messages.push(user)
    await routeResearch(c, user)
  }

  function stop() {
    controller?.abort()
  }

  return { streaming, preparing, liveTrace, streamId, liveOpen, runCompletion, routeResearch, sendResearch, stop }
}
