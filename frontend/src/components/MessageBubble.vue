<script setup>
import { Bot, Check, ChevronRight, Cog, Copy, Pencil, Pin, RotateCcw, Trash2, User, X } from '@lucide/vue'
import { ref } from 'vue'
import { formatTime } from '../utils/format.js'
import { renderMarkdown } from '../utils/md.js'

const props = defineProps({
  message: { type: Object, required: true },
  editing: Boolean, // this message is the one being edited; the parent owns which one that is
  active: Boolean, // tapped bubble: shows its action toolbar (mobile has no hover)
  windowStart: Boolean, // first message of the send window: renders the "sent from here" divider
  trace: { type: Array, default: null }, // live thinking/search steps while this message streams
  traceOpen: Boolean,
})
const emit = defineEmits(['edit', 'cancel-edit', 'done-edit', 'delete', 'regenerate', 'activate', 'toggle-trace'])

const ROLE_ICON = { user: User, assistant: Bot, system: Cog }
const copied = ref(false)

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

function togglePin() {
  props.message.pinned = !props.message.pinned
}
async function copyMessage() {
  await navigator.clipboard.writeText(props.message.content)
  copied.value = true
  setTimeout(() => (copied.value = false), 1200)
}
</script>

<template>
  <!-- Render the live trace as soon as search or thinking events arrive. -->
  <div v-if="trace && trace.length" class="mb-1 text-xs text-muted">
    <button class="flex items-center gap-0.5 hover:text-base" @click.stop="emit('toggle-trace')">
      <ChevronRight :size="12" class="transition-transform" :class="traceOpen && 'rotate-90'" />
      {{ trace.length }} step{{ trace.length > 1 ? 's' : '' }}
    </button>
    <div v-if="traceOpen" class="mt-1 flex flex-col gap-2 border-l-2 border-indigo-500/40 pl-2">
      <div v-for="(s, i) in trace" :key="i">
        <div class="text-[10px] uppercase tracking-wide opacity-60">{{ s.type }}</div>
        <div v-if="s.type === 'results'" class="flex flex-col gap-0.5">
          <a v-for="(l, j) in s.links" :key="j" :href="l.url" target="_blank" rel="noopener" class="truncate text-indigo-400 hover:underline">{{ l.title || l.url }}</a>
        </div>
        <div v-else class="whitespace-pre-wrap [overflow-wrap:anywhere]">{{ s.text }}</div>
      </div>
    </div>
  </div>
  <div class="group">
    <div v-if="windowStart" class="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-wide text-indigo-400" title="Messages from here down are sent to the model">
      <div class="h-px flex-1 bg-indigo-500/40"></div>
      sent from here
      <div class="h-px flex-1 bg-indigo-500/40"></div>
    </div>
    <!-- edit mode -->
    <div v-if="editing" class="rounded-lg border border-edge bg-surface p-2">
      <div class="mb-2 flex items-center gap-2">
        <select v-model="message.role" class="rounded bg-surface2 px-2 py-1 text-xs">
          <option value="system">system</option>
          <option value="user">user</option>
          <option value="assistant">assistant</option>
        </select>
        <button class="ml-auto rounded p-1.5 text-muted hover:bg-surface2 hover:text-base" title="Cancel" @click="emit('cancel-edit')"><X :size="14" /></button>
        <button class="rounded bg-indigo-600 p-1.5 text-white hover:bg-indigo-500" title="Done" @click="emit('done-edit')"><Check :size="14" /></button>
      </div>
      <textarea v-model="message.content" rows="5" class="w-full rounded bg-surface2 px-3 py-2 text-sm outline-none"></textarea>
    </div>

    <!-- view mode -->
    <div v-else class="flex" :class="rowAlign(message.role)" @click="emit('activate')">
      <div class="flex min-w-0 max-w-2xl flex-col" :class="colAlign(message.role)">
        <!-- min-w leaves room for the right-anchored hover toolbar inside narrow bubbles. -->
        <div class="relative min-w-[11rem] max-w-full rounded-lg px-4 py-2" :class="bubbleClass(message.role)">
          <div class="mb-1 flex items-center gap-1 opacity-60">
            <component :is="ROLE_ICON[message.role]" :size="13" />
            <Pin v-if="message.pinned" :size="12" class="fill-current text-indigo-400" />
          </div>
          <div v-if="message.role === 'system'" class="whitespace-pre-wrap [overflow-wrap:anywhere] text-sm" :class="!message.content && 'italic text-muted'">{{ message.content || 'You are a helpful assistant.' }}</div>
          <div v-else-if="message.content" class="md [overflow-wrap:anywhere]" v-html="renderMarkdown(message.content)"></div>
          <div v-else class="text-muted">…</div>
          <div class="absolute -top-3 right-2 hidden gap-0.5 rounded-md border border-edge bg-surface p-0.5 text-muted shadow group-hover:flex" :class="{ '!flex': active }">
            <button class="rounded p-1 hover:bg-surface2 hover:text-base" title="Regenerate from here" @click="emit('regenerate')"><RotateCcw :size="14" /></button>
            <button class="rounded p-1 hover:bg-surface2 hover:text-base" title="Edit" @click="emit('edit')"><Pencil :size="14" /></button>
            <button v-if="message.role !== 'system'" class="rounded p-1 hover:bg-surface2" :class="message.pinned ? 'text-indigo-400' : 'hover:text-base'" :title="message.pinned ? 'Unpin' : 'Pin (always sent)'" @click="togglePin"><Pin :size="14" :class="message.pinned && 'fill-current'" /></button>
            <button class="rounded p-1 hover:bg-surface2 hover:text-base" title="Copy raw" @click="copyMessage">
              <Check v-if="copied" :size="14" class="text-green-500" />
              <Copy v-else :size="14" />
            </button>
            <button class="rounded p-1 hover:bg-surface2 hover:text-red-500" title="Delete" @click="emit('delete')"><Trash2 :size="14" /></button>
          </div>
        </div>
        <div v-if="message.role !== 'system' && message.createdAt" class="mt-0.5 px-1 text-[10px] text-muted">
          {{ formatTime(message.createdAt) }}
        </div>
      </div>
    </div>
  </div>
</template>
