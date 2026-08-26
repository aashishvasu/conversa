<script setup>
import { Bot, Brain, Bug, ChevronDown, Layers, Menu, NotebookText, Plus, RotateCcw, Send, SlidersHorizontal, Square } from '@lucide/vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { streamChat } from '../api.js'
import { useStreamGuard } from '../composables/useStreamGuard.js'
import { refreshMemory } from '../memory.js'
import { notify } from '../utils/notify.js'
import { buildPayload, sendWindow } from '../payload.js'
import { effectiveSettings, EFFORT_LEVELS } from '../settings.js'
import { addConvoUsage, recordUsage } from '../usage.js'
import { attachedDocs, createDoc, currentConversation, persistNow, sidebarOpen, workspaceOf } from '../store.js'
import { generateTitle } from '../titles.js'
import { confirmDelete } from '../utils/confirm.js'
import { CHECK_SVG, COPY_SVG } from '../utils/md.js'
import { enterToSend, fontScale } from '../utils/prefs.js'
import CardsPanel from '../components/CardsPanel.vue'
import DebugPanel from '../components/DebugPanel.vue'
import MessageBubble from '../components/MessageBubble.vue'
import ModelSelect from '../components/ModelSelect.vue'
import Modal from '../components/Modal.vue'
import SpendBadge from '../components/SpendBadge.vue'
import ContextPanel from '../components/ContextPanel.vue'
import SettingsPanel from '../components/SettingsPanel.vue'

const convo = currentConversation
const input = ref('')
const streaming = ref(false)
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

// This conversation's running spend, same shape and rendering as the research pane's.
const convoSpend = computed(() => convo.value?.usage || { calls: 0, input: 0, output: 0, usd: 0, unpriced: 0 })

function setModel(id) {
  convo.value.settings.model = id
}
function setThinking(v) {
  convo.value.settings.effort = v
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
  convo.value.messages = convo.value.messages.filter((m) => m.id !== id)
  if (editingId.value === id) editingId.value = null
}
// Trash button: confirm first.
// (cancelEdit calls removeMessage directly, since discarding a blank new message needs no confirmation.)
async function confirmRemoveMessage(id) {
  if (await confirmDelete('Delete this message?')) removeMessage(id)
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
    const payload = buildPayload(c, settings, workspaceOf(c), attachedDocs(c)) // built BEFORE the empty assistant placeholder
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
      const last = liveTrace.value.at(-1) // coalesce a run of thinking deltas into one entry
      if (type === 'thinking' && last?.type === 'thinking') last.text += value
      else if (type === 'results') liveTrace.value.push({ type, links: value })
      else liveTrace.value.push({ type, text: value })
    }, (usage) => {
      addConvoUsage(c, usage)
      recordUsage('chat', usage)
    })
    if (c.title === 'New conversation') {
      try {
        const t = await generateTitle(c, settings.utility_model)
        if (t) c.title = t
      } catch (e) {
        notify({ key: 'utility:title', severity: 'warning', text: `Title generation failed: ${e.message}` })
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
    refreshMemory(c, settings).catch((e) => notify({ key: 'utility:memory', severity: 'warning', text: `Memory summary failed: ${e.message}` }))
    persistNow() // don't let a quick reload lose the completed message
  }
}

// Enter behaviour is a frontend pref: by default Enter sends and Shift+Enter makes a newline; flip enterToSend and they swap.
// Let the textarea insert the newline itself.
const composerHint = computed(() => enterToSend.value
  ? 'Enter to send, Shift+Enter for newline'
  : 'Shift+Enter to send, Enter for newline')
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

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value || !convo.value) return
  const c = convo.value
  c.messages.push({ id: crypto.randomUUID(), role: 'user', content: text, createdAt: Date.now() })
  input.value = ''
  // Sending is an explicit jump to the present: follow the new turn even if the user had scrolled up, and re-arm the streaming autoscroll below.
  atBottom.value = true
  scrollDown()
  runCompletion(c)
}

// Regenerate: re-stream from a message, discarding everything after it.
// From an assistant turn, the turn itself is discarded too, back to the last user turn, which is kept.
// System messages are never discarded (they're standing instructions).
function regenerate(m) {
  if (streaming.value || !convo.value) return
  const c = convo.value
  const idx = c.messages.findIndex((x) => x.id === m.id)
  if (idx < 0) return
  let cut = idx
  if (m.role === 'assistant') {
    while (cut >= 0 && c.messages[cut].role !== 'user') cut--
    if (cut < 0) return // no user turn before it, so nothing to regenerate from
  }
  c.messages = c.messages.filter((x, i) => i <= cut || x.role === 'system')
  runCompletion(c)
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
      notify({ key: 'title', text: 'Empty title returned', foreground: true })
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
      <button class="rounded p-1.5 hover:bg-surface2 md:hidden" @click="sidebarOpen = true">
        <Menu :size="18" />
      </button>
      <input
        v-model="convo.title"
        class="min-w-0 flex-1 truncate bg-transparent text-base font-semibold outline-none"
      />
      <button class="rounded p-1.5 text-muted hover:bg-surface2 hover:text-base disabled:opacity-50" title="Regenerate title" :disabled="titling" @click="regenTitle">
        <RotateCcw :size="15" :class="titling && 'animate-spin'" />
      </button>
      <span v-if="convo.isTemplate" class="rounded bg-amber-600/20 px-1.5 py-0.5 text-[10px] uppercase text-amber-600">template</span>
    </header>

    <!-- Messages -->
    <div class="relative flex-1 overflow-hidden">
      <div ref="scroller" class="h-full space-y-3 overflow-y-auto px-3 py-6 sm:px-4" @scroll="onScroll" @click="onContentClick">
        <div v-if="convo.messages.length > visibleCount" class="flex justify-center">
          <button class="rounded px-3 py-1 text-xs text-muted hover:bg-surface2 hover:text-base" @click="visibleCount += PAGE_SIZE">
            Load {{ PAGE_SIZE }} more ({{ convo.messages.length - visibleCount }} older)
          </button>
        </div>
        <!-- The component boundary scopes re-renders: streaming one message re-renders only its own bubble, so it doesn't re-parse markdown for every other visible message. -->
        <MessageBubble
          v-for="m in visibleMessages"
          :key="m.id"
          :message="m"
          :editing="editingId === m.id"
          :active="activeId === m.id"
          :window-start="windowStartId === m.id"
          :trace="m.id === streamId ? liveTrace : null"
          :trace-open="liveOpen"
          @activate="activeId = m.id"
          @edit="startEdit(m)"
          @cancel-edit="cancelEdit(m)"
          @done-edit="editingId = null"
          @delete="confirmRemoveMessage(m.id)"
          @regenerate="regenerate(m)"
          @toggle-trace="liveOpen = !liveOpen"
          @promote="promoteToDoc(m)"
        />

        <div class="flex justify-center">
          <button class="flex items-center gap-1 rounded px-3 py-1 text-xs text-muted hover:bg-surface2 hover:text-base" @click="addMessage">
            <Plus :size="14" /> Add message
          </button>
        </div>
      </div>

      <button
        v-if="!atBottom"
        class="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-edge bg-surface p-2 text-muted shadow-lg hover:text-base"
        title="Scroll to bottom"
        @click="scrollDown"
      >
        <ChevronDown :size="18" />
      </button>
    </div>

    <!-- Toolbar + composer -->
    <div class="border-t border-edge">
      <div class="flex items-center gap-2 px-3 py-1.5">
        <div class="flex items-center gap-1 rounded bg-surface2 pl-2 text-muted" title="Model">
          <Bot :size="14" />
          <ModelSelect
            :model-value="effectiveSettings(convo).model"
            class="max-w-[9rem] bg-transparent py-1 pr-1 text-xs text-base outline-none"
            @update:model-value="setModel"
          />
        </div>
        <div class="flex items-center gap-1 rounded bg-surface2 pl-2 text-muted" title="Thinking effort">
          <Brain :size="14" />
          <select
            :value="effectiveSettings(convo).effort || ''"
            class="bg-transparent py-1 pr-1 text-xs text-base outline-none"
            @change="setThinking($event.target.value)"
          >
            <option v-for="l in EFFORT_LEVELS" :key="l.value" :value="l.value">{{ l.label }}</option>
          </select>
        </div>
        <span v-if="convoSpend.calls" class="rounded bg-surface2 px-2 py-1 text-xs text-muted">
          <SpendBadge :spend="convoSpend" />
        </span>
        <div class="ml-auto flex gap-1">
          <button class="rounded p-1.5 hover:bg-surface2" title="Context editor" @click="panel = 'context'"><NotebookText :size="16" /></button>
          <button class="rounded p-1.5 hover:bg-surface2" title="Cards" @click="panel = 'cards'"><Layers :size="16" /></button>
          <button class="rounded p-1.5 hover:bg-surface2" title="Conversation settings" @click="panel = 'settings'"><SlidersHorizontal :size="16" /></button>
          <!-- debug peek, deliberately lighter weight than the real panels -->
          <button class="rounded p-1.5 opacity-50 hover:bg-surface2 hover:opacity-100" title="Debug: live system prompt" @click="panel = 'debug'"><Bug :size="16" /></button>
        </div>
      </div>
      <div class="flex items-stretch gap-2 px-3 pb-3">
        <textarea
          ref="composerEl"
          v-model="input"
          rows="2"
          :placeholder="`Message…  (${composerHint})`"
          class="min-h-16 max-h-40 flex-1 resize-none rounded bg-surface2 px-3 py-2 outline-none"
          @keydown="onComposerKeydown"
        ></textarea>
        <button v-if="!streaming" class="flex items-center justify-center rounded bg-indigo-600 px-4 text-white hover:bg-indigo-500" title="Send" @click="send">
          <Send :size="18" />
        </button>
        <button v-else class="flex items-center justify-center rounded bg-red-600 px-4 text-white hover:bg-red-500" title="Stop" @click="stop">
          <Square :size="18" />
        </button>
      </div>
    </div>

    <Modal v-if="panel === 'context'" title="Context editor" @close="panel = null">
      <ContextPanel :convo="convo" />
    </Modal>
    <Modal v-if="panel === 'settings'" title="Conversation settings" @close="panel = null">
      <SettingsPanel :convo="convo" />
    </Modal>
    <Modal v-if="panel === 'cards'" title="Cards" @close="panel = null">
      <CardsPanel :convo="convo" />
    </Modal>
    <Modal v-if="panel === 'debug'" title="System prompt (live)" @close="panel = null">
      <DebugPanel :convo="convo" />
    </Modal>
  </section>

  <section v-else class="flex flex-1 items-center justify-center bg-app text-muted">
    Create a conversation to begin.
  </section>
</template>
