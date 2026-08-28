<script setup>
import { Bot, Check, ChevronRight, Cog, Copy, FileText, Pencil, Pin, RotateCcw, Trash2, User, X } from '@lucide/vue'
import { ref } from 'vue'
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger, ToolbarRoot } from 'reka-ui'
import { formatTime } from '../utils/format.js'
import { renderMarkdown } from '../utils/md.js'
import UiIconButton from './ui/UiIconButton.vue'
import UiSelect from './ui/UiSelect.vue'
import UiToolbarButton from './ui/UiToolbarButton.vue'
import UiTooltip from './ui/UiTooltip.vue'

const props = defineProps({
  message: { type: Object, required: true },
  editing: Boolean, // this message is the one being edited; the parent owns which one that is
  active: Boolean, // tapped bubble: shows its action toolbar (mobile has no hover)
  windowStart: Boolean, // first message of the send window: renders the "sent from here" divider
  trace: { type: Array, default: null }, // live thinking/search steps while this message streams
  traceOpen: Boolean,
  images: { type: Array, default: () => [] },
})
const emit = defineEmits(['edit', 'cancel-edit', 'done-edit', 'delete', 'regenerate', 'activate', 'toggle-trace', 'promote'])

const ROLE_ICON = { user: User, assistant: Bot, system: Cog }
const copied = ref(false)
const promoted = ref(false)

function bubbleClass(role) {
  if (role === 'user') return 'bg-accent text-on-accent'
  if (role === 'system') return 'border border-warning/40 bg-surface'
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
function promote() {
  emit('promote')
  promoted.value = true
  setTimeout(() => (promoted.value = false), 1200)
}
</script>

<template>
  <!-- Render the live trace as soon as search or thinking events arrive. -->
  <CollapsibleRoot v-if="trace && trace.length" :open="traceOpen" class="mb-1 text-xs text-muted" @update:open="$event !== traceOpen && emit('toggle-trace')">
    <CollapsibleTrigger class="flex items-center gap-0.5 rounded-sm outline-none hover:text-base focus-visible:ring-2 focus-visible:ring-focus">
      <ChevronRight :size="12" class="transition-transform" :class="traceOpen && 'rotate-90'" />
      {{ $t('message.steps', trace.length, { count: trace.length }) }}
    </CollapsibleTrigger>
    <CollapsibleContent class="mt-1 flex flex-col gap-2 border-l-2 border-accent/40 pl-2">
      <div v-for="(s, i) in trace" :key="i">
        <div class="text-[10px] uppercase tracking-wide opacity-60">{{ s.type }}</div>
        <div v-if="s.type === 'results'" class="flex flex-col gap-0.5">
          <a v-for="(l, j) in s.links" :key="j" :href="l.url" target="_blank" rel="noopener" class="truncate text-accent hover:underline">{{ l.title || l.url }}</a>
        </div>
        <div v-else class="whitespace-pre-wrap [overflow-wrap:anywhere]">{{ s.text }}</div>
      </div>
    </CollapsibleContent>
  </CollapsibleRoot>
  <div class="group">
    <UiTooltip v-if="windowStart" :content="$t('message.sendBoundary')">
      <div class="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-wide text-accent">
        <div class="h-px flex-1 bg-accent/40"></div>
        {{ $t('message.sentFromHere') }}
        <div class="h-px flex-1 bg-accent/40"></div>
      </div>
    </UiTooltip>
    <!-- edit mode -->
    <div v-if="editing" class="rounded-lg border border-edge bg-surface p-2">
      <div class="mb-2 flex items-center gap-2">
        <UiSelect
          v-model="message.role"
          :aria-label="$t('message.role')"
          :options="[
            { value: 'system', label: $t('message.roleSystem') },
            { value: 'user', label: $t('message.roleUser') },
            { value: 'assistant', label: $t('message.roleAssistant') },
          ]"
          compact
          class="!w-36"
        />
        <UiIconButton class="ml-auto" :label="$t('message.cancelEdit')" @click="emit('cancel-edit')"><X :size="14" /></UiIconButton>
        <UiIconButton :label="$t('message.doneEditing')" variant="primary" @click="emit('done-edit')"><Check :size="14" /></UiIconButton>
      </div>
      <textarea v-model="message.content" rows="5" class="w-full rounded-md border border-edge bg-surface2 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-focus"></textarea>
    </div>

    <!-- view mode -->
    <div v-else class="flex" :class="rowAlign(message.role)" @click="emit('activate')">
      <div class="flex min-w-0 max-w-2xl flex-col" :class="colAlign(message.role)">
        <!-- min-w leaves room for the right-anchored hover toolbar inside narrow bubbles. -->
        <div class="relative min-w-[11rem] max-w-full rounded-lg px-4 py-2" :class="bubbleClass(message.role)">
          <div class="mb-1 flex items-center gap-1 opacity-60">
            <component :is="ROLE_ICON[message.role]" :size="13" />
            <Pin v-if="message.pinned" :size="12" class="fill-current text-accent" />
          </div>
          <div v-if="images.length" class="mb-2 flex gap-2 overflow-x-auto">
            <img v-for="image in images" :key="image.id" :src="`data:${image.media_type};base64,${image.data}`" class="h-20 w-20 rounded object-cover" />
          </div>
          <div v-if="message.role === 'system'" class="whitespace-pre-wrap [overflow-wrap:anywhere] text-sm" :class="!message.content && 'italic text-muted'">{{ message.content || $t('message.emptySystem') }}</div>
          <div v-else-if="message.content" class="md [overflow-wrap:anywhere]" v-html="renderMarkdown(message.content)"></div>
          <div v-else class="text-muted">…</div>
          <ToolbarRoot class="absolute -top-3 right-2 hidden gap-0.5 rounded-md border border-edge bg-surface p-0.5 text-muted shadow group-hover:flex" :class="{ '!flex': active }" :aria-label="$t('common.actions')">
            <UiToolbarButton :label="$t('message.regenerate')" @click="emit('regenerate')"><RotateCcw :size="14" /></UiToolbarButton>
            <UiToolbarButton :label="$t('message.edit')" @click="emit('edit')"><Pencil :size="14" /></UiToolbarButton>
            <UiToolbarButton v-if="message.role !== 'system'" :label="message.pinned ? $t('message.unpin') : $t('message.pin')" :active="message.pinned" @click="togglePin"><Pin :size="14" :class="message.pinned && 'fill-current'" /></UiToolbarButton>
            <UiToolbarButton v-if="message.role === 'assistant' && message.content" :label="$t('message.saveDoc')" @click="promote">
              <Check v-if="promoted" :size="14" class="text-success" />
              <FileText v-else :size="14" />
            </UiToolbarButton>
            <UiToolbarButton :label="$t('message.copyRaw')" @click="copyMessage">
              <Check v-if="copied" :size="14" class="text-success" />
              <Copy v-else :size="14" />
            </UiToolbarButton>
            <UiToolbarButton :label="$t('message.delete')" danger @click="emit('delete')"><Trash2 :size="14" /></UiToolbarButton>
          </ToolbarRoot>
        </div>
        <div v-if="message.role !== 'system' && message.createdAt" class="mt-0.5 px-1 text-[10px] text-muted">
          {{ formatTime(message.createdAt) }}
        </div>
      </div>
    </div>
  </div>
</template>
