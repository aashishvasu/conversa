<script setup>
import { Brain, Bug, ChevronDown, Layers, Menu, NotebookText, Paperclip, Plus, Send, SlidersHorizontal, Sparkles, Square, Telescope, X } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { EditableArea, EditableInput, EditablePreview, EditableRoot, Toggle, ToolbarRoot } from 'reka-ui'
import { useAutoGrowTextarea } from '../composables/useAutoGrowTextarea.js'
import { useAutoScroll } from '../composables/useAutoScroll.js'
import { useImageAttachments } from '../composables/useImageAttachments.js'
import { generateTitle } from '../jobs/titles.js'
import { notify } from '../utils/notify.js'
import { tr } from '../i18n/index.js'
import { sendWindow } from '../prompt/payload.js'
import { effectiveSettings, EFFORT_LEVELS } from '../state/settings.js'
import { activeRunOf, createDoc, currentConversation, imagesOf, persistNow, releaseImages, removeRun, sidebarOpen } from '../state/store.js'
import { useStreamOrchestration } from '../research/orchestration.js'
import { confirmDelete } from '../utils/confirm.js'
import { CHECK_SVG, COPY_SVG } from '../utils/md.js'
import { enterToSend, showThinkingAndSearch } from '../utils/prefs.js'
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
const panel = ref(null)
const editingId = ref(null)
let editBackup = null // original {content, role} so Cancel can revert; null = newly added
const activeId = ref(null) // tapped bubble: shows its action toolbar (mobile has no hover)
const titling = ref(false)

const { streaming, preparing, liveTrace, streamId, liveOpen, runCompletion, routeResearch, sendResearch, stop } = useStreamOrchestration()
const { pendingImages, imageInput, onImageInput, onPaste, onDrop, removePending } = useImageAttachments()
const { atBottom, scroller, scrollDown, onScroll } = useAutoScroll(convo)
const { composerEl } = useAutoGrowTextarea(input)

// Live thinking/search trace for the latest turn.
// Deliberately ephemeral: not on the message, not persisted, so a reload wipes it.
// It stays visible after the turn completes (until the next send resets it), and can be collapsed via liveOpen.
const showTrace = computed(() => convo.value?.showThinkingAndSearch ?? showThinkingAndSearch.value)

// Render only the last N messages for speed; "Load more" reveals older ones in PAGE_SIZE batches.
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

const convoSpend = computed(() => convo.value?.usage || { calls: 0, input: 0, output: 0, usd: 0, unpriced: 0 })

watch(convo, () => {
  visibleCount.value = PAGE_SIZE
  atBottom.value = true
  scrollDown()
})

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

// A running research turn blocks new sends in its conversation; other conversations stay free.
const runActive = computed(() => !!activeRunOf(convo.value?.id))
const researchMode = computed(() => convo.value?.mode === 'research')

// Enter behaviour is a frontend pref: by default Enter sends and Shift+Enter makes a newline; flip enterToSend and they swap.
const composerHint = computed(() => tr(enterToSend.value ? 'chat.enterHint' : 'chat.shiftEnterHint'))
function onComposerKeydown(e) {
  if (e.key !== 'Enter' || e.isComposing) return // don't fire mid-IME-composition
  const isSend = enterToSend.value ? !e.shiftKey : e.shiftKey
  if (isSend) {
    e.preventDefault()
    send()
  }
}

async function send() {
  const text = input.value.trim()
  if ((!text && !pendingImages.value.length) || streaming.value || preparing.value || runActive.value || !convo.value) return
  const c = convo.value
  if (researchMode.value && !text) return
  const imageIds = pendingImages.value.map((image) => image.id)
  pendingImages.value = []
  input.value = ''
  // Sending is an explicit jump to the present: follow the new turn even if the user had scrolled up.
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
        <Sparkles :size="15" :class="titling && 'animate-pulse'" />
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
      <SettingsPanel :convo="convo" @close="panel = null" />
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
