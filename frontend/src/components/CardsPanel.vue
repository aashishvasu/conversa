<script setup>
import { X } from 'lucide-vue-next'
import { computed } from 'vue'
import { matchedCardIds } from '../cards.js'
import { effectiveSettings } from '../store.js'

const props = defineProps({ convo: Object })

// Live preview: which cards would fire against the current send window.
const active = computed(() => {
  const n = effectiveSettings(props.convo).num_messages_to_send
  const turns = props.convo.messages.filter((m) => m.role !== 'system').slice(-n)
  return matchedCardIds(props.convo.cards, turns, props.convo.scanAssistant)
})

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

    <details
      v-for="card in convo.cards"
      :key="card.id"
      class="rounded border"
      :class="active.has(card.id) ? 'border-green-500' : 'border-edge'"
    >
      <summary class="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 [&::-webkit-details-marker]:hidden">
        <span class="h-2 w-2 shrink-0 rounded-full" :class="active.has(card.id) ? 'bg-green-500' : 'bg-muted'" :title="active.has(card.id) ? 'Active for next send' : 'Inactive'"></span>
        <span class="flex-1 truncate text-muted">{{ card.triggers || 'No triggers' }}</span>
        <button class="shrink-0 text-muted hover:text-red-500" @click.stop.prevent="removeCard(card.id)"><X :size="14" /></button>
      </summary>
      <div class="space-y-2 border-t border-edge p-2">
        <input v-model="card.triggers" placeholder="dragon, red wyrm, ancient lizard" class="w-full rounded bg-surface2 px-2 py-1" />
        <textarea v-model="card.content" rows="4" placeholder="Context to inject when triggered…" class="w-full rounded bg-surface2 px-2 py-1"></textarea>
      </div>
    </details>

    <button class="w-full rounded bg-surface2 py-2 hover:opacity-80" @click="addCard()">+ Add card</button>
  </div>
</template>
