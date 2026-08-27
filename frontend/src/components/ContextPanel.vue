<script setup>
import { Trash2, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import { fetchUrl } from '../api/client.js'
import { deleteDoc, docs, docsOf, removeDocRef } from '../state/store.js'
import { confirmDelete } from '../utils/confirm.js'
import { tr } from '../i18n.js'
import DocRow from './DocRow.vue'

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
  if (await confirmDelete(tr('confirm.deleteSystem'))) {
    props.convo.messages = props.convo.messages.filter((x) => x.id !== m.id)
  }
}

// Standing document attachments: the convo's own docIds, alongside whatever its workspace already shares.
const attached = computed(() => docsOf(props.convo))
const unattached = computed(() => docs.value.filter((d) => !props.convo.docIds?.includes(d.id)))

function attach(id) {
  ;(props.convo.docIds ??= []).push(id)
}
async function detach(id) {
  if (await confirmDelete(tr('confirm.removeConversationDoc'), tr('common.remove'))) {
    removeDocRef(props.convo, id)
  }
}
async function destroyDoc(id) {
  if (await confirmDelete(tr('confirm.deleteDoc'))) {
    deleteDoc(id)
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
    <p class="text-muted">{{ $t('context.help') }}</p>

    <details v-for="msg in contextMessages" :key="msg.id" class="group rounded border border-edge">
      <summary class="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 [&::-webkit-details-marker]:hidden">
        <span class="shrink-0 text-xs uppercase tracking-wide text-muted">{{ msg.role }}</span>
        <span class="flex-1 truncate text-muted group-open:hidden">{{ msg.content.trim() }}</span>
        <button class="shrink-0 text-muted hover:text-red-500" :title="msg.role === 'system' ? $t('common.delete') : $t('message.unpin')" @click.stop.prevent="remove(msg)"><X :size="14" /></button>
      </summary>
      <textarea v-model="msg.content" rows="4" :placeholder="$t('context.assistantInstructions')" class="w-full rounded-b border-t border-edge bg-surface2 px-2 py-2 outline-none"></textarea>
    </details>

    <p v-if="!contextMessages.length" class="text-muted">{{ $t('context.empty') }}</p>

    <button class="w-full rounded bg-surface2 py-2 hover:opacity-80" @click="addSystem">{{ $t('context.addSystem') }}</button>

    <div class="flex gap-2">
      <input
        v-model="pageUrl" type="url" :placeholder="$t('context.fetchPlaceholder')"
        class="min-w-0 flex-1 rounded bg-surface2 px-2 py-2 outline-none"
        @keydown.enter.prevent="addPage"
      />
      <button class="shrink-0 rounded bg-surface2 px-3 py-2 hover:opacity-80 disabled:opacity-50" :disabled="fetching" @click="addPage">
        {{ fetching ? $t('context.fetching') : $t('context.fetch') }}
      </button>
    </div>
    <p v-if="fetchError" class="text-xs text-red-500">{{ fetchError }}</p>

    <hr class="border-edge" />

    <p class="text-muted">{{ $t('context.docsHelp') }}</p>
    <DocRow v-for="d in attached" :key="d.id" :doc="d" :owner="convo" @remove="detach(d.id)" />
    <p v-if="!attached.length" class="text-xs italic text-muted">{{ $t('context.noDocs') }}</p>

    <details v-if="unattached.length" class="rounded border border-edge">
      <summary class="cursor-pointer list-none px-2 py-1.5 text-muted [&::-webkit-details-marker]:hidden">{{ $t('context.attachDoc', unattached.length, { count: unattached.length }) }}</summary>
      <div class="space-y-1 border-t border-edge p-2">
        <div v-for="d in unattached" :key="d.id" class="flex items-center gap-2">
          <span class="min-w-0 flex-1 truncate">{{ d.name }}</span>
          <span class="shrink-0 text-xs text-muted">{{ $t('common.charCount', { count: (d.text.length / 1000).toFixed(1) }) }}</span>
          <button class="shrink-0 rounded bg-surface2 px-2 py-0.5 hover:opacity-80" @click="attach(d.id)">{{ $t('context.attach') }}</button>
          <button class="shrink-0 text-muted hover:text-red-500" :title="$t('common.delete')" @click="destroyDoc(d.id)"><Trash2 :size="14" /></button>
        </div>
      </div>
    </details>
  </div>
</template>
