<script setup>
import { X } from 'lucide-vue-next'
import { computed } from 'vue'

const props = defineProps({ convo: Object })

// The always-sent context: every system message plus any pinned turn. Same message
// objects rendered inline in the chat — editing here updates both places.
const contextMessages = computed(() =>
  props.convo.messages.filter((m) => m.role === 'system' || m.pinned),
)

function addSystem() {
  props.convo.messages.unshift({ id: crypto.randomUUID(), role: 'system', content: '', createdAt: Date.now() })
}
// System messages are deleted; pinned turns are just unpinned (they stay in the chat).
function remove(m) {
  if (m.role === 'system') props.convo.messages = props.convo.messages.filter((x) => x.id !== m.id)
  else m.pinned = false
}
</script>

<template>
  <div class="space-y-2 text-sm">
    <p class="text-muted">
      System and pinned messages are always sent — they ignore the messages-to-send limit.
      Editing here and in the conversation are the same thing.
    </p>

    <details v-for="msg in contextMessages" :key="msg.id" class="group rounded border border-edge">
      <summary class="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 [&::-webkit-details-marker]:hidden">
        <span class="shrink-0 text-xs uppercase tracking-wide text-muted">{{ msg.role }}</span>
        <span class="flex-1 truncate text-muted group-open:hidden">{{ msg.content.trim() }}</span>
        <button class="shrink-0 text-muted hover:text-red-500" :title="msg.role === 'system' ? 'Delete' : 'Unpin'" @click.stop.prevent="remove(msg)"><X :size="14" /></button>
      </summary>
      <textarea v-model="msg.content" rows="4" placeholder="Instructions for the assistant…" class="w-full rounded-b border-t border-edge bg-surface2 px-2 py-2 outline-none"></textarea>
    </details>

    <p v-if="!contextMessages.length" class="text-muted">No system or pinned messages yet.</p>

    <button class="w-full rounded bg-surface2 py-2 hover:opacity-80" @click="addSystem">+ Add system message</button>
  </div>
</template>
