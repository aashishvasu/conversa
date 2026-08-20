<script setup>
import { X } from '@lucide/vue'
import { computed, ref } from 'vue'
import { fetchUrl } from '../api.js'
import { confirmDelete } from '../confirm.js'

const props = defineProps({ convo: Object })

// The always-sent context: every system message plus any pinned turn.
// These are the same message objects rendered inline in the chat, so editing here updates both places.
const contextMessages = computed(() =>
  props.convo.messages.filter((m) => m.role === 'system' || m.pinned),
)

function addSystem() {
  props.convo.messages.unshift({ id: crypto.randomUUID(), role: 'system', content: '', createdAt: Date.now() })
}
// System messages are deleted, so they confirm first.
// Pinned turns are only unpinned, which is reversible, so they go straight through.
async function remove(m) {
  if (m.role !== 'system') { m.pinned = false; return }
  if (await confirmDelete('Delete this system message?')) {
    props.convo.messages = props.convo.messages.filter((x) => x.id !== m.id)
  }
}

// A fetched page lands as a system message, so it edits, deletes and sends like any other context.
const pageUrl = ref('')
const fetching = ref(false)
const fetchError = ref('')
async function addPage() {
  const url = pageUrl.value.trim()
  if (!url || fetching.value) return
  fetching.value = true
  fetchError.value = ''
  try {
    const page = await fetchUrl(url)
    props.convo.messages.unshift({
      id: crypto.randomUUID(),
      role: 'system',
      content: `Reference page "${page.title || page.url}" (${page.url}):\n\n${page.content}`,
      createdAt: Date.now(),
    })
    pageUrl.value = ''
  } catch (e) {
    fetchError.value = e.message
  } finally {
    fetching.value = false
  }
}
</script>

<template>
  <div class="space-y-2 text-sm">
    <p class="text-muted">
      System and pinned messages are always sent. They ignore the messages-to-send limit.
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

    <div class="flex gap-2">
      <input
        v-model="pageUrl" type="url" placeholder="https://… fetch a page as context"
        class="min-w-0 flex-1 rounded bg-surface2 px-2 py-2 outline-none"
        @keydown.enter.prevent="addPage"
      />
      <button class="shrink-0 rounded bg-surface2 px-3 py-2 hover:opacity-80 disabled:opacity-50" :disabled="fetching" @click="addPage">
        {{ fetching ? 'Fetching…' : 'Fetch' }}
      </button>
    </div>
    <p v-if="fetchError" class="text-xs text-red-500">{{ fetchError }}</p>
  </div>
</template>
