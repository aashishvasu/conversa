<script setup>
import { Bot, Bug, Check, ChevronDown, ChevronRight, Cog, Copy, Layers, Menu, NotebookText, Pencil, Pin, Plus, RotateCcw, Send, SlidersHorizontal, Square, Trash2, User, X } from 'lucide-vue-next'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { streamChat } from '../api.js'
import { buildPayload, sendWindow } from '../cards.js'
import { confirmDelete } from '../confirm.js'
import { formatTime } from '../format.js'
import { CHECK_SVG, COPY_SVG, renderMarkdown } from '../md.js'
import { compressIfNeeded } from '../memory.js'
import { enterToSend, fontScale } from '../prefs.js'
import { currentConversation, effectiveSettings, models, persistNow, sidebarOpen } from '../store.js'
import { generateTitle } from '../titles.js'
import CardsPanel from './CardsPanel.vue'
import DebugPanel from './DebugPanel.vue'
import Modal from './Modal.vue'
import ContextPanel from './ContextPanel.vue'
import SettingsPanel from './SettingsPanel.vue'

const convo = currentConversation
const input = ref('')
const streaming = ref(false)
const titling = ref(false)
const titleErr = ref('')
const panel = ref(null)
const editingId = ref(null)
let editBackup = null // original {content, role} so Cancel can revert; null = newly added
const copiedId = ref(null)
const activeId = ref(null) // tapped bubble: shows its action toolbar (mobile has no hover)
// Live thinking/search trace for the latest turn. Deliberately ephemeral: not on the
// message, not persisted — a reload wipes it. It stays visible after the turn completes
// (until the next send resets it), and can be collapsed via liveOpen.
const streamId = ref(null)
const liveTrace = ref([])
const liveOpen = ref(true)
const atBottom = ref(true)
const scroller = ref(null)
let controller = null

// Render only the last N messages for speed; "Load more" reveals older ones in
// PAGE_SIZE batches. Tune PAGE_SIZE here. Display-only — all messages stay in memory
// and what's sent to the API is governed separately by num_messages_to_send.
const PAGE_SIZE = 100
const visibleCount = ref(PAGE_SIZE)
const visibleMessages = computed(() => {
  const all = convo.value?.messages || []
  return all.length > visibleCount.value ? all.slice(-visibleCount.value) : all
})

const ROLE_ICON = { user: User, assistant: Bot, system: Cog }

// First message of the send window — a divider renders above it so the user can
// see how much of the conversation goes to the model. Pins/system are always sent
// regardless and aren't marked.
const windowStartId = computed(() =>
  convo.value ? sendWindow(convo.value, effectiveSettings(convo.value))[0]?.id : null,
)

function setModel(id) {
  convo.value.settings.model = id
}
function bubbleClass(role) {
  if (role === 'user') return 'bg-indigo-600 text-white'
  if (role === 'system') return 'border border-amber-600/40 bg-surface'
  return 'bg-surface2'
}
function rowAlign(role) {
  if (role === 'user') return 'justify-end'
  if (role === 'system') return 'justify-center'
  return 'justify-start'
}
function colAlign(role) {
  return role === 'user' ? 'items-end' : 'items-start'
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
// Trash button: confirm first. (cancelEdit calls removeMessage directly — discarding
// a blank new message needs no confirmation.)
async function confirmRemoveMessage(id) {
  if (await confirmDelete('Delete this message?')) removeMessage(id)
}
function togglePin(m) {
  m.pinned = !m.pinned
}
async function copyMessage(m) {
  await navigator.clipboard.writeText(m.content)
  copiedId.value = m.id
  setTimeout(() => {
    if (copiedId.value === m.id) copiedId.value = null
  }, 1200)
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
// On reload, convo already has its value when this mounts, so the watcher above
// won't fire — scroll to the bottom once for the initial conversation.
onMounted(scrollDown)

async function runCompletion(c) {
  const settings = effectiveSettings(c)
  streaming.value = true
  controller = new AbortController()
  let assistant = null
  try {
    // Fold old turns into memory first (when enabled) so the payload reflects it.
    if (settings.use_memory) {
      try {
        await compressIfNeeded(c, settings)
      } catch { /* on failure, just send uncompressed */ }
    }
    const payload = buildPayload(c, settings) // built BEFORE the empty assistant placeholder
    c.messages.push({ id: crypto.randomUUID(), role: 'assistant', content: '', createdAt: Date.now() })
    assistant = c.messages.at(-1) // reactive proxy, not the raw object — so streamed tokens render live
    liveTrace.value = []
    streamId.value = assistant.id
    await streamChat(payload, (t) => (assistant.content += t), controller.signal, (type, value) => {
      const last = liveTrace.value.at(-1) // coalesce a run of thinking deltas into one entry
      if (type === 'thinking' && last?.type === 'thinking') last.text += value
      else if (type === 'results') liveTrace.value.push({ type, links: value })
      else liveTrace.value.push({ type, text: value })
    })
    if (c.title === 'New conversation') {
      try {
        const t = await generateTitle(c, settings.utility_model)
        if (t) c.title = t
      } catch { /* best-effort */ }
    }
  } catch (e) {
    if (e.name !== 'AbortError' && assistant)
      assistant.content += `${assistant.content ? '\n\n' : ''}> ⚠️ **Error:** ${e.message}`
  } finally {
    streaming.value = false
    persistNow() // don't let a quick reload lose the completed message
  }
}

// Enter behaviour is a frontend pref: by default Enter sends and Shift+Enter makes a
// newline; flip enterToSend and they swap. Let the textarea insert the newline itself.
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

// Auto-grow the composer with its content, capped by max-h; shrinks back when cleared
// (watch also fires when send() empties it). Native field-sizing:content would be one
// line of CSS, but Firefox still lacks it. fontScale reflows the text, so re-measure.
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
  runCompletion(c)
}

// Regenerate: re-stream from a message, discarding everything after it. From an
// assistant turn, the turn itself is discarded too — back to the last user turn,
// which is kept. System messages are never discarded (they're standing instructions).
function regenerate(m) {
  if (streaming.value || !convo.value) return
  const c = convo.value
  const idx = c.messages.findIndex((x) => x.id === m.id)
  if (idx < 0) return
  let cut = idx
  if (m.role === 'assistant') {
    while (cut >= 0 && c.messages[cut].role !== 'user') cut--
    if (cut < 0) return // no user turn before it — nothing to regenerate from
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
  titleErr.value = ''
  try {
    const t = await generateTitle(convo.value, effectiveSettings(convo.value).utility_model)
    if (t) {
      convo.value.title = t
      await persistNow()
    } else {
      titleErr.value = 'Empty title returned'
    }
  } catch (e) {
    titleErr.value = e.message
  } finally {
    titling.value = false
    if (titleErr.value) setTimeout(() => (titleErr.value = ''), 5000)
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
      <span v-if="titleErr" class="max-w-[35%] truncate text-xs text-red-500" :title="titleErr">{{ titleErr }}</span>
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
        <!-- v-memo: re-render a bubble only when something it shows changes, so streaming
             one message doesn't re-parse markdown for every other visible message. -->
        <template v-for="m in visibleMessages" :key="m.id">
          <!-- Ephemeral live trace, rendered ABOVE the streaming bubble and OUTSIDE the
               v-memo below, so it appears the instant search/thinking events arrive rather
               than waiting for the first text token to invalidate the memo. -->
          <div v-if="m.id === streamId && liveTrace.length" class="mb-1 text-xs text-muted">
            <button class="flex items-center gap-0.5 hover:text-base" @click.stop="liveOpen = !liveOpen">
              <ChevronRight :size="12" class="transition-transform" :class="liveOpen && 'rotate-90'" />
              {{ liveTrace.length }} step{{ liveTrace.length > 1 ? 's' : '' }}
            </button>
            <div v-if="liveOpen" class="mt-1 flex flex-col gap-2 border-l-2 border-indigo-500/40 pl-2">
              <div v-for="(s, i) in liveTrace" :key="i">
                <div class="text-[10px] uppercase tracking-wide opacity-60">{{ s.type }}</div>
                <div v-if="s.type === 'results'" class="flex flex-col gap-0.5">
                  <a v-for="(l, j) in s.links" :key="j" :href="l.url" target="_blank" rel="noopener" class="truncate text-indigo-400 hover:underline">{{ l.title || l.url }}</a>
                </div>
                <div v-else class="whitespace-pre-wrap [overflow-wrap:anywhere]">{{ s.text }}</div>
              </div>
            </div>
          </div>
        <div v-memo="[m.content, m.role, m.pinned, editingId === m.id, copiedId === m.id, activeId === m.id, windowStartId === m.id]" class="group">
          <div v-if="windowStartId === m.id" class="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-wide text-indigo-400" title="Messages from here down are sent to the model">
            <div class="h-px flex-1 bg-indigo-500/40"></div>
            sent from here
            <div class="h-px flex-1 bg-indigo-500/40"></div>
          </div>
          <!-- edit mode -->
          <div v-if="editingId === m.id" class="rounded-lg border border-edge bg-surface p-2">
            <div class="mb-2 flex items-center gap-2">
              <select v-model="m.role" class="rounded bg-surface2 px-2 py-1 text-xs">
                <option value="system">system</option>
                <option value="user">user</option>
                <option value="assistant">assistant</option>
              </select>
              <button class="ml-auto rounded p-1.5 text-muted hover:bg-surface2 hover:text-base" title="Cancel" @click="cancelEdit(m)"><X :size="14" /></button>
              <button class="rounded bg-indigo-600 p-1.5 text-white hover:bg-indigo-500" title="Done" @click="editingId = null"><Check :size="14" /></button>
            </div>
            <textarea v-model="m.content" rows="5" class="w-full rounded bg-surface2 px-3 py-2 text-sm outline-none"></textarea>
          </div>

          <!-- view mode -->
          <div v-else class="flex" :class="rowAlign(m.role)" @click="activeId = m.id">
            <div class="flex min-w-0 max-w-2xl flex-col" :class="colAlign(m.role)">
              <div class="relative rounded-lg px-4 py-2" :class="bubbleClass(m.role)">
                <div class="mb-1 flex items-center gap-1 opacity-60">
                  <component :is="ROLE_ICON[m.role]" :size="13" />
                  <Pin v-if="m.pinned" :size="12" class="fill-current text-indigo-400" />
                </div>
                <div v-if="m.role === 'system'" class="whitespace-pre-wrap [overflow-wrap:anywhere] text-sm" :class="!m.content && 'italic text-muted'">{{ m.content || 'You are a helpful assistant.' }}</div>
                <div v-else-if="m.content" class="md [overflow-wrap:anywhere]" v-html="renderMarkdown(m.content)"></div>
                <div v-else class="text-muted">…</div>
                <div class="absolute -top-3 right-2 hidden gap-0.5 rounded-md border border-edge bg-surface p-0.5 text-muted shadow group-hover:flex" :class="{ '!flex': activeId === m.id }">
                  <button class="rounded p-1 hover:bg-surface2 hover:text-base" title="Regenerate from here" @click="regenerate(m)"><RotateCcw :size="14" /></button>
                  <button class="rounded p-1 hover:bg-surface2 hover:text-base" title="Edit" @click="startEdit(m)"><Pencil :size="14" /></button>
                  <button v-if="m.role !== 'system'" class="rounded p-1 hover:bg-surface2" :class="m.pinned ? 'text-indigo-400' : 'hover:text-base'" :title="m.pinned ? 'Unpin' : 'Pin (always sent)'" @click="togglePin(m)"><Pin :size="14" :class="m.pinned && 'fill-current'" /></button>
                  <button class="rounded p-1 hover:bg-surface2 hover:text-base" title="Copy raw" @click="copyMessage(m)">
                    <Check v-if="copiedId === m.id" :size="14" class="text-green-500" />
                    <Copy v-else :size="14" />
                  </button>
                  <button class="rounded p-1 hover:bg-surface2 hover:text-red-500" title="Delete" @click="confirmRemoveMessage(m.id)"><Trash2 :size="14" /></button>
                </div>
              </div>
              <div v-if="m.role !== 'system' && m.createdAt" class="mt-0.5 px-1 text-[10px] text-muted">
                {{ formatTime(m.createdAt) }}
              </div>
            </div>
          </div>
        </div>
        </template>

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
        <select
          :value="effectiveSettings(convo).model"
          class="max-w-[10rem] rounded bg-surface2 px-2 py-1 text-xs"
          @change="setModel($event.target.value)"
        >
          <option v-for="m in models" :key="m.id" :value="m.id">{{ m.label }}</option>
        </select>
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
