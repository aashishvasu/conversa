<script setup>
import { GripVertical, X } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { matchedCardIds } from '../cards.js'
import { effectiveSettings } from '../store.js'

const props = defineProps({ convo: Object })

// Live preview: which cards would fire against the current send window.
const active = computed(() => {
  const n = effectiveSettings(props.convo).num_messages_to_send
  const turns = props.convo.messages.filter((m) => m.role !== 'system').slice(-n)
  return matchedCardIds(props.convo.cards, turns, props.convo.scanAssistant)
})

// Cards grouped by their (display-only) folder path. Named folders first in
// first-appearance order, ungrouped cards last. Matching ignores path entirely.
const groups = computed(() => {
  const byPath = new Map()
  for (const card of props.convo.cards) {
    const key = (card.path || '').trim()
    if (!byPath.has(key)) byPath.set(key, [])
    byPath.get(key).push(card)
  }
  const entries = [...byPath.entries()]
  return [...entries.filter(([k]) => k), ...entries.filter(([k]) => !k)]
})

// Flattened to header + card rows so every <details> shares one parent. Editing a
// card's folder then moves its node instead of recreating it — keeping it open and
// focused mid-edit.
const rows = computed(() => {
  const out = []
  for (const [path, cards] of groups.value) {
    if (path) out.push({ key: `h:${path}`, header: path })
    for (const card of cards) out.push({ key: card.id, card })
  }
  return out
})

// Drag-to-reorder. Dropping onto a card moves the dragged card next to it and
// adopts its folder — so one gesture reorders and re-files across groups.
const dragId = ref(null)
function onDragStart(e, id) {
  dragId.value = id
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', '') // Firefox won't start a drag without data
}
function onDrop(target) {
  const id = dragId.value
  dragId.value = null
  if (!id || id === target.id) return
  const cards = props.convo.cards
  const moved = cards.splice(cards.findIndex((c) => c.id === id), 1)[0]
  moved.path = target.path || ''
  cards.splice(cards.findIndex((c) => c.id === target.id), 0, moved)
}

function addCard() {
  props.convo.cards.push({ id: crypto.randomUUID(), triggers: '', content: '' })
}
function removeCard(id) {
  props.convo.cards = props.convo.cards.filter((c) => c.id !== id)
}
</script>

<template>
  <div class="space-y-2 text-sm">
    <p class="text-muted">
      Trigger phrases (comma-separated). When one appears in the last messages sent,
      the card's text is added to the system prompt. Click a card to expand.
    </p>

    <template v-for="row in rows" :key="row.key">
      <p v-if="row.header" class="px-1 pt-1 text-xs text-muted">{{ row.header }}</p>
      <details
        v-else
        class="rounded border"
        :class="[active.has(row.card.id) ? 'border-green-500' : 'border-edge', dragId === row.card.id ? 'opacity-50' : '']"
        @dragover.prevent
        @drop="onDrop(row.card)"
      >
        <summary class="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 [&::-webkit-details-marker]:hidden">
          <span class="shrink-0 cursor-grab text-muted active:cursor-grabbing" draggable="true" title="Drag to reorder or move folder" @click.stop.prevent @dragstart="onDragStart($event, row.card.id)"><GripVertical :size="14" /></span>
          <span class="h-2 w-2 shrink-0 rounded-full" :class="active.has(row.card.id) ? 'bg-green-500' : 'bg-muted'" :title="active.has(row.card.id) ? 'Active for next send' : 'Inactive'"></span>
          <span class="flex-1 truncate text-muted">{{ row.card.triggers || 'No triggers' }}</span>
          <button class="shrink-0 text-muted hover:text-red-500" @click.stop.prevent="removeCard(row.card.id)"><X :size="14" /></button>
        </summary>
        <div class="space-y-2 border-t border-edge p-2">
          <input v-model="row.card.path" placeholder="Folder (optional)" class="w-full rounded bg-surface2 px-2 py-1 text-xs text-muted" />
          <input v-model="row.card.triggers" placeholder="dragon, red wyrm, ancient lizard" class="w-full rounded bg-surface2 px-2 py-1" />
          <textarea v-model="row.card.content" rows="4" placeholder="Context to inject when triggered…" class="w-full rounded bg-surface2 px-2 py-1"></textarea>
        </div>
      </details>
    </template>

    <button class="w-full rounded bg-surface2 py-2 hover:opacity-80" @click="addCard()">+ Add card</button>
  </div>
</template>
