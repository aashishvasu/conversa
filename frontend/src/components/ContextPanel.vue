<script setup>
import { Trash2, X } from '@lucide/vue'
import { computed } from 'vue'
import { deleteDoc, docs, docsOf, removeDocRef } from '../state/store.js'
import { confirmDelete } from '../utils/confirm.js'
import { tr } from '../i18n.js'
import DocRow from './DocRow.vue'
import UiButton from './ui/UiButton.vue'
import UiDisclosure from './ui/UiDisclosure.vue'
import UiIconButton from './ui/UiIconButton.vue'

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
</script>

<template>
  <div class="space-y-2 text-sm">
    <p class="text-muted">{{ $t('context.help') }}</p>

    <UiDisclosure v-for="msg in contextMessages" :key="msg.id" :padded="false">
      <template #title>
        <span class="shrink-0 text-xs uppercase tracking-wide text-muted">{{ msg.role }}</span>
        <span class="truncate text-muted">{{ msg.content.trim() }}</span>
      </template>
      <template #actions>
        <UiIconButton :label="msg.role === 'system' ? $t('common.delete') : $t('message.unpin')" variant="danger" @click="remove(msg)"><X :size="14" /></UiIconButton>
      </template>
      <textarea v-model="msg.content" rows="4" :placeholder="$t('context.assistantInstructions')" class="w-full bg-surface2 px-2 py-2 outline-none focus-visible:ring-2 focus-visible:ring-focus"></textarea>
    </UiDisclosure>

    <p v-if="!contextMessages.length" class="text-muted">{{ $t('context.empty') }}</p>

    <UiButton class="w-full" @click="addSystem">{{ $t('context.addSystem') }}</UiButton>

    <hr class="border-edge" />

    <p class="text-muted">{{ $t('context.docsHelp') }}</p>
    <DocRow v-for="d in attached" :key="d.id" :doc="d" :owner="convo" @remove="detach(d.id)" />
    <p v-if="!attached.length" class="text-xs italic text-muted">{{ $t('context.noDocs') }}</p>

    <UiDisclosure v-if="unattached.length">
      <template #title><span class="text-muted">{{ $t('context.attachDoc', unattached.length, { count: unattached.length }) }}</span></template>
      <div class="space-y-1">
        <div v-for="d in unattached" :key="d.id" class="flex items-center gap-2">
          <span class="min-w-0 flex-1 truncate">{{ d.name }}</span>
          <span class="shrink-0 text-xs text-muted">{{ $t('common.charCount', { count: (d.text.length / 1000).toFixed(1) }) }}</span>
          <UiButton size="compact" @click="attach(d.id)">{{ $t('context.attach') }}</UiButton>
          <UiIconButton :label="$t('common.delete')" variant="danger" @click="destroyDoc(d.id)"><Trash2 :size="14" /></UiIconButton>
        </div>
      </div>
    </UiDisclosure>
  </div>
</template>
