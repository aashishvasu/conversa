<script setup>
import { Brain, Bug, ChevronDown, Layers, Menu, NotebookText, Paperclip, Plus, RotateCcw, Send, SlidersHorizontal, Square, Telescope, X } from '@lucide/vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { EditableArea, EditableInput, EditablePreview, EditableRoot, Toggle, ToolbarRoot } from 'reka-ui'
import { prepareResearch, streamChat } from '../api/client.js'
import { useStreamGuard } from '../composables/useStreamGuard.js'
import { refreshMemory } from '../jobs/memory.js'
import { notify } from '../utils/notify.js'
import { tr } from '../i18n.js'
import { buildPayload, sendWindow } from '../prompt/payload.js'
import { buildResearchInput } from '../prompt/research-input.js'
import { effectiveSettings, EFFORT_LEVELS, RESEARCH_KEYS } from '../state/settings.js'
import { addConvoUsage, recordUsage } from '../state/usage.js'
import { activeRunOf, attachedDocs, createDoc, createImage, createRun, currentConversation, images, imagesOf, persistNow, releaseImages, removeRun, sidebarOpen, workspaceOf } from '../state/store.js'
import { generateTitle } from '../jobs/titles.js'
import { confirmDelete } from '../utils/confirm.js'
import { CHECK_SVG, COPY_SVG } from '../utils/md.js'
import { enterToSend, fontScale, showThinkingAndSearch } from '../utils/prefs.js'
import CardsPanel from '../components/CardsPanel.vue'
import DebugPanel from '../components/DebugPanel.vue'
import MessageBubble from '../components/MessageBubble.vue'
import ModelSelect from '../components/ModelSelect.vue'
import ResearchBlock from '../components/ResearchBlock.vue'
import Modal from '../components/Modal.vue'
import SpendBadge from '../components/SpendBadge.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiIconButton from '../components/ui/UiIconButton.vue'
import UiSelect from '../components/ui/UiSelect.vue'
import UiToolbarButton from '../components/ui/UiToolbarButton.vue'
import ContextPanel from '../components/ContextPanel.vue'
import SettingsPanel from '../components/SettingsPanel.vue'

const convo = currentConversation
const input = ref('')
const pendingImages = ref([])
const imageInput = ref(null)
const streaming = ref(false)
const preparing = ref(false)
const titling = ref(false)
const panel = ref(null)
const editingId = ref(null)
let editBackup = null // original {content, role} so Cancel can revert; null = newly added
const activeId = ref(null) // tapped bubble: shows its action toolbar (mobile has no hover)
// Live thinking/search trace for the latest turn.
// Deliberately ephemeral: not on the message, not persisted, so a reload wipes it.
// It stays visible after the turn completes (until the next send resets it), and can be collapsed via liveOpen.
const streamId = ref(null)
const liveTrace = ref([])
const liveOpen = ref(true)
const showTrace = computed(() => convo.value?.showThinkingAndSearch ?? showThinkingAndSearch.value)
const atBottom = ref(true)
const scroller = ref(null)
let controller = null
const guard = useStreamGuard(() => streaming.value, () => controller?.abort())

// Render only the last N messages for speed; "Load more" reveals older ones in PAGE_SIZE batches.
// Tune PAGE_SIZE here.
// Display-only: all messages stay in memory, and what's sent to the API is governed separately by num_messages_to_send.
const PAGE_SIZE = 100
const visibleCount = ref(PAGE_SIZE)
const visibleMessages = computed(() => {
  const all = convo.value?.messages || []
  return all.length > visibleCount.value ? all.slice(-visibleCount.value) : all
})

// First message of the send window.
// A divider renders above it so the user can see how much of the conversation goes to the model.
// Pins and system messages go every turn regardless, so they carry no marker.
const windowStartId = computed(() =>
  convo.value ? sendWindow(convo.value, effectiveSettings(convo.value))[0]?.id : null,
)

// This conversation's running spend.
const convoSpend = computed(() => convo.value?.usage || { calls: 0, input: 0, output: 0, usd: 0, unpriced: 0 })

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

function setModel(id) {
  convo.value.settings.model = id
}
function setThinking(v) {
  convo.value.settings.effort = v
}
function toggleResearch() {
  if (pendingImages.value.length) {
    notify({ key: 'image:attach', severity: 'warning', text: tr('chat.sendImagesFirst') })
    return
  }
  convo.value.mode = researchMode.value ? 'chat' : 'research'
}

function addMessage() {
  const m = { id: crypto.randomUUID(), role: 'user', content: '', createdAt: Date.now() }
  convo.value.messages.push(m)
  editBackup = null // new message: Cancel removes it
  editingId.value = m.id
}
function startEdit(m) {
  editBackup = { content: m.content, role: m.role }
  editingId.value = m.id
}
function cancelEdit(m) {
  if (editBackup) Object.assign(m, editBackup) // existing: revert edits
  else removeMessage(m.id) // newly added: drop it
  editingId.value = null
}
function removeMessage(id) {
  const message = convo.value.messages.find((m) => m.id === id)
  convo.value.messages = convo.value.messages.filter((m) => m.id !== id)
  releaseImages(message?.imageIds)
  if (editingId.value === id) editingId.value = null
}
// Trash button: confirm first.
// (cancelEdit calls removeMessage directly, since discarding a blank new message needs no confirmation.)
async function confirmRemoveMessage(id) {
  if (await confirmDelete(tr('confirm.deleteMessage'))) removeMessage(id)
}

// Promote a reply into the doc store, where any conversation or workspace can attach it (ContextPanel, WorkspacePanel).
// Deliberately not attached here: the text is already in this transcript, and attaching would resend it with every request.
function promoteToDoc(m) {
  const name = m.content.match(/^#+\s+(.+)$/m)?.[1] || convo.value.title
  createDoc({ name, text: m.content, source: { kind: 'chat', convoId: convo.value.id, messageId: m.id } })
}

// Delegated handler for every code-block Copy button (markdown is v-html).
function onContentClick(e) {
  const btn = e.target.closest('.code-copy')
  if (!btn) return
  const code = btn.parentElement.querySelector('code')
  if (!code) return
  navigator.clipboard.writeText(code.textContent)
  btn.innerHTML = CHECK_SVG
  setTimeout(() => (btn.innerHTML = COPY_SVG), 1200)
}

function scrollDown() {
  nextTick(() => {
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  })
}
function onScroll() {
  const el = scroller.value
  if (el) atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}
// Only auto-follow the stream when the user is already at the bottom.
watch(() => convo.value?.messages.at(-1)?.content, () => atBottom.value && scrollDown(), { flush: 'post' })
watch(convo, () => {
  visibleCount.value = PAGE_SIZE
  atBottom.value = true
  scrollDown()
})
// On reload, convo already has its value when this mounts, so the watcher above won't fire.
// Scroll to the bottom once for the initial conversation.
onMounted(scrollDown)

async function runCompletion(c) {
  const settings = effectiveSettings(c)
  streaming.value = true
  controller = new AbortController()
  guard.start()
  let assistant = null
  try {
    const payload = { ...buildPayload(c, settings, workspaceOf(c), attachedDocs(c), images.value), allow_tools: true } // built BEFORE the empty assistant placeholder
    c.messages.push({ id: crypto.randomUUID(), role: 'assistant', content: '', createdAt: Date.now() })
    assistant = c.messages.at(-1) // the reactive proxy, so streamed tokens render live
    liveTrace.value = []
    streamId.value = assistant.id
    // Every frame, text or trace, counts as liveness for the stall watchdog.
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
    // Refresh the memory summary in the background, off the send path.
    // The key dedupes: this fires after every reply, so a persistently failing utility model refreshes one toast instead of stacking.
    refreshMemory(c, settings).catch((e) => notify({ key: 'utility:memory', severity: 'warning', text: tr('chat.memoryFailed', { error: e.message }) }))
    persistNow() // don't let a quick reload lose the completed message
  }
}

// Enter behaviour is a frontend pref: by default Enter sends and Shift+Enter makes a newline; flip enterToSend and they swap.
// Let the textarea insert the newline itself.
const composerHint = computed(() => tr(enterToSend.value ? 'chat.enterHint' : 'chat.shiftEnterHint'))
function onComposerKeydown(e) {
  if (e.key !== 'Enter' || e.isComposing) return // don't fire mid-IME-composition
  const isSend = enterToSend.value ? !e.shiftKey : e.shiftKey
  if (isSend) {
    e.preventDefault()
    send()
  }
}

// Auto-grow the composer with its content, capped by max-h; shrinks back when cleared (watch also fires when send() empties it).
// Native field-sizing:content would be one line of CSS, but Firefox still lacks it.
// fontScale reflows the text, so re-measure.
const composerEl = ref(null)
watch([input, fontScale], () => {
  const el = composerEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}, { flush: 'post' })

// The first cut allows one generation per conversation: a running research turn blocks new sends here while other conversations stay free.
const runActive = computed(() => !!activeRunOf(convo.value?.id))
const researchMode = computed(() => convo.value?.mode === 'research')

async function send() {
  const text = input.value.trim()
  if ((!text && !pendingImages.value.length) || streaming.value || preparing.value || runActive.value || !convo.value) return
  const c = convo.value
  if (researchMode.value && !text) return
  const imageIds = pendingImages.value.map((image) => image.id)
  pendingImages.value = []
  input.value = ''
  // Sending is an explicit jump to the present: follow the new turn even if the user had scrolled up, and re-arm the streaming autoscroll below.
  atBottom.value = true
  if (researchMode.value) {
    await sendResearch(c, text)
    scrollDown()
    return
  }
  c.messages.push({ id: crypto.randomUUID(), role: 'user', content: text, imageIds, mode: 'chat', createdAt: Date.now() })
  scrollDown()
  runCompletion(c)
}

function clarificationContent(questions) {
  return questions.length
    ? `Before I research this, please answer:\n\n${questions.map((question) => `- ${question}`).join('\n')}`
    : 'Before I research this, please provide the missing detail.'
}

// Preparation sees the exact normal-chat context, including the request and no placeholder.
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

// Regenerate: discard the generated tail and repeat the originating user turn.
// A research-enabled turn goes through preparation again, so the model still chooses answer, clarify, or research.
function regenerate(m) {
  if (streaming.value || preparing.value || runActive.value || !convo.value) return
  const c = convo.value
  const idx = c.messages.findIndex((message) => message.id === m.id)
  if (idx < 0) return
  let cut = idx
  if (m.role === 'assistant') {
    while (cut >= 0 && c.messages[cut].role !== 'user') cut--
    if (cut < 0) return // no user turn before it, so nothing to regenerate from
  }
  const user = c.messages[cut]
  const removed = c.messages.slice(cut + 1).flatMap((message) => message.imageIds || [])
  c.messages = c.messages.filter((message, index) => index <= cut || message.role === 'system')
  releaseImages(removed)

  if (user.mode === 'research') {
    if (user.runId) removeRun(user.runId)
    delete user.runId
    void routeResearch(c, user)
    return
  }
  runCompletion(c)
}

async function attachImages(files) {
  for (const file of files) {
    try {
      if (!['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(file.type)) throw new Error(tr('chat.unsupportedImage', { name: file.name || tr('chat.file') }))
      const bitmap = await createImageBitmap(file)
      const scale = Math.min(1, 2000 / Math.max(bitmap.width, bitmap.height))
      const width = Math.round(bitmap.width * scale)
      const height = Math.round(bitmap.height * scale)
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const context = canvas.getContext('2d')
      if (!context) {
        bitmap.close()
        throw new Error(tr('chat.processImageFailed'))
      }
      context.drawImage(bitmap, 0, 0, width, height)
      bitmap.close()
      const encode = (type) => new Promise((resolve) => canvas.toBlob(resolve, type, 0.85))
      let blob = file.type === 'image/png' ? await encode('image/png') : null
      if (!blob || blob.size > 1024 * 1024) blob = await encode('image/webp')
      if (!blob || blob.type !== 'image/webp') blob = await encode('image/jpeg')
      if (!blob) throw new Error(tr('chat.encodeImageFailed', { name: file.name || tr('chat.image') }))
      const bytes = new Uint8Array(await blob.arrayBuffer())
      let binary = ''
      for (const byte of bytes) binary += String.fromCharCode(byte)
      const data = btoa(binary)
      if (data.length > 10 * 1024 * 1024) throw new Error(tr('chat.imageTooLarge', { name: file.name || tr('chat.image') }))
      pendingImages.value.push(await createImage({ id: crypto.randomUUID(), media_type: blob.type, width, height, data, createdAt: Date.now() }))
    } catch (e) {
      notify({ key: 'image:attach', severity: 'warning', text: e.message })
    }
  }
}

function onImageInput(e) {
  attachImages(e.target.files)
  e.target.value = ''
}
function onPaste(e) {
  if (e.clipboardData.files.length) attachImages(e.clipboardData.files)
}
function onDrop(e) {
  e.preventDefault()
  attachImages(e.dataTransfer.files)
}
function removePending(image) {
  pendingImages.value = pendingImages.value.filter((x) => x.id !== image.id)
  releaseImages([image.id])
}

function stop() {
  controller?.abort()
}

async function regenTitle() {
  if (titling.value || !convo.value) return
  titling.value = true
  try {
    const t = await generateTitle(convo.value, effectiveSettings(convo.value).utility_model)
    if (t) {
      convo.value.title = t
      await persistNow()
    } else {
      notify({ key: 'title', text: tr('chat.emptyTitle'), foreground: true })
    }
  } catch (e) {
    notify({ key: 'title', text: e.message, foreground: true })
  } finally {
    titling.value = false
  }
}
</script>

<template>
  <section v-if="convo" class="flex flex-1 flex-col overflow-hidden bg-app text-base">
    <!-- Top bar -->
    <header class="flex items-center gap-2 border-b border-edge px-3 py-2.5">
      <UiIconButton class="md:hidden" :label="$t('sidebar.menu')" @click="sidebarOpen = true"><Menu :size="18" /></UiIconButton>
      <EditableRoot v-model="convo.title" activation-mode="focus" submit-mode="both" select-on-focus class="min-w-0 flex-1">
        <EditableArea class="rounded-sm focus-within:ring-2 focus-within:ring-focus">
          <EditablePreview class="block truncate rounded-sm text-base font-semibold outline-none focus-visible:ring-2 focus-visible:ring-focus" />
          <EditableInput :aria-label="$t('chat.conversationTitle')" class="w-full bg-transparent text-base font-semibold outline-none" />
        </EditableArea>
      </EditableRoot>
      <UiIconButton :label="$t('chat.regenerateTitle')" :disabled="titling" @click="regenTitle">
        <RotateCcw :size="15" :class="titling && 'animate-spin'" />
      </UiIconButton>
      <span v-if="convo.isTemplate" class="rounded bg-warning/15 px-1.5 py-0.5 text-[10px] uppercase text-warning">{{ $t('chat.template') }}</span>
    </header>

    <!-- Messages -->
    <div class="relative flex-1 overflow-hidden">
      <div ref="scroller" class="h-full space-y-3 overflow-y-auto px-3 py-6 sm:px-4" @scroll="onScroll" @click="onContentClick">
        <div v-if="convo.messages.length > visibleCount" class="flex justify-center">
          <UiButton size="compact" variant="ghost" @click="visibleCount += PAGE_SIZE">
            {{ $t('chat.loadMore', { count: PAGE_SIZE, older: convo.messages.length - visibleCount }) }}
          </UiButton>
        </div>
        <!-- The component boundary scopes re-renders: streaming one message re-renders only its own bubble, so it doesn't re-parse markdown for every other visible message. -->
        <template v-for="m in visibleMessages" :key="m.id">
          <ResearchBlock v-if="m.role === 'assistant' && m.runId" :message="m" :convo="convo" />
          <MessageBubble
            v-else
            :message="m"
            :editing="editingId === m.id"
            :active="activeId === m.id"
            :window-start="windowStartId === m.id"
            :trace="showTrace && m.id === streamId ? liveTrace : null"
            :trace-open="liveOpen"
            :images="imagesOf(m)"
            @activate="activeId = m.id"
            @edit="startEdit(m)"
            @cancel-edit="cancelEdit(m)"
            @done-edit="editingId = null"
            @delete="confirmRemoveMessage(m.id)"
            @regenerate="regenerate(m)"
            @toggle-trace="liveOpen = !liveOpen"
            @promote="promoteToDoc(m)"
          />
        </template>

        <div class="flex justify-center">
          <UiButton size="compact" variant="ghost" @click="addMessage">
            <Plus :size="14" /> {{ $t('chat.addMessage') }}
          </UiButton>
        </div>
      </div>

      <UiIconButton
        v-if="!atBottom"
        class="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-edge bg-surface shadow-lg"
        :label="$t('chat.scrollBottom')"
        @click="scrollDown"
      >
        <ChevronDown :size="18" />
      </UiIconButton>
    </div>

    <!-- Toolbar + composer -->
    <div class="border-t border-edge">
      <div class="flex items-center gap-2 px-3 py-1.5">
        <ModelSelect
          :model-value="effectiveSettings(convo).model"
          :label="$t('common.model')"
          icon-only
          compact
          @update:model-value="setModel"
        />
        <UiSelect
          :model-value="effectiveSettings(convo).effort || ''"
          :label="$t('settings.thinkingEffort')"
          :aria-label="$t('settings.thinkingEffort')"
          :options="EFFORT_LEVELS.map(value => ({ value, label: $t(`effort.${value || 'off'}`) }))"
          icon-only
          @update:model-value="setThinking"
        >
          <template #trigger><Brain :size="14" /></template>
        </UiSelect>
        <Toggle
          :model-value="researchMode"
          :title="$t('chat.research')"
          class="flex size-8 items-center justify-center rounded-md border border-edge bg-surface2 text-muted outline-none transition-colors hover:bg-edge hover:text-base data-[state=on]:border-accent data-[state=on]:bg-accent data-[state=on]:text-on-accent focus-visible:ring-2 focus-visible:ring-focus"
          :aria-label="researchMode ? $t('chat.researchOn') : $t('chat.researchOff')"
          @update:model-value="toggleResearch"
        >
          <Telescope :size="14" />
        </Toggle>
        <span v-if="convoSpend.calls" class="inline-flex h-8 items-center rounded bg-surface2 px-2 text-xs text-muted">
          <SpendBadge :spend="convoSpend" />
        </span>
        <ToolbarRoot class="ml-auto flex gap-0.5" :aria-label="$t('chat.tools')">
          <UiToolbarButton :label="$t('chat.contextEditor')" @click="panel = 'context'"><NotebookText :size="16" /></UiToolbarButton>
          <UiToolbarButton :label="$t('common.cards')" @click="panel = 'cards'"><Layers :size="16" /></UiToolbarButton>
          <UiToolbarButton :label="$t('chat.conversationSettings')" @click="panel = 'settings'"><SlidersHorizontal :size="16" /></UiToolbarButton>
          <UiToolbarButton class="opacity-60" :label="$t('debug.button')" @click="panel = 'debug'"><Bug :size="16" /></UiToolbarButton>
        </ToolbarRoot>
      </div>
      <div class="flex items-stretch gap-2 px-3 pb-3" @dragover.prevent @drop="!researchMode && onDrop($event)">
        <div class="flex min-w-0 flex-1 flex-col gap-2">
          <div v-if="pendingImages.length" class="flex gap-2 overflow-x-auto">
            <div v-for="image in pendingImages" :key="image.id" class="relative shrink-0">
              <img :src="`data:${image.media_type};base64,${image.data}`" class="h-16 w-16 rounded object-cover" />
              <UiIconButton class="absolute -right-2 -top-2 !size-6 rounded-full border border-edge bg-surface" :label="$t('chat.removeImage')" @click="removePending(image)"><X :size="12" /></UiIconButton>
            </div>
          </div>
          <div class="flex items-stretch gap-2">
            <textarea
          ref="composerEl"
          v-model="input"
          rows="2"
          :placeholder="runActive || preparing ? $t('chat.researchRunning') : `${researchMode ? $t('chat.researchPrompt') : $t('chat.messagePlaceholder')}  (${composerHint})`"
          :disabled="runActive || preparing"
          class="min-h-16 max-h-40 flex-1 resize-none rounded-md border border-edge bg-surface2 px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-focus disabled:opacity-60"
          @keydown="onComposerKeydown"
          @paste="onPaste"
        ></textarea>
            <input ref="imageInput" type="file" multiple accept="image/jpeg,image/png,image/gif,image/webp" class="hidden" @change="onImageInput" />
            <UiIconButton class="h-auto w-10" :label="$t('chat.attachImages')" :disabled="researchMode" @click="imageInput.click()"><Paperclip :size="18" /></UiIconButton>
          </div>
        </div>
        <UiIconButton v-if="!streaming" class="h-auto w-12" variant="primary" :label="researchMode ? $t('chat.startResearch') : $t('common.send')" :disabled="runActive || preparing" @click="send">
          <Telescope v-if="researchMode" :size="18" />
          <Send v-else :size="18" />
        </UiIconButton>
        <UiIconButton v-else class="h-auto w-12" variant="dangerSolid" :label="$t('common.stop')" @click="stop">
          <Square :size="18" />
        </UiIconButton>
      </div>
    </div>

    <Modal v-if="panel === 'context'" :title="$t('chat.contextEditor')" @close="panel = null">
      <ContextPanel :convo="convo" />
    </Modal>
    <Modal v-if="panel === 'settings'" :title="$t('chat.conversationSettings')" @close="panel = null">
      <SettingsPanel :convo="convo" />
    </Modal>
    <Modal v-if="panel === 'cards'" :title="$t('common.cards')" @close="panel = null">
      <CardsPanel :convo="convo" />
    </Modal>
    <Modal v-if="panel === 'debug'" :title="$t('debug.title')" @close="panel = null">
      <DebugPanel :convo="convo" />
    </Modal>
  </section>

  <section v-else class="flex flex-1 items-center justify-center bg-app text-muted">
    {{ $t('chat.createFirst') }}
  </section>
</template>
