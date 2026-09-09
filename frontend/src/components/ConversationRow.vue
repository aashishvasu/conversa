<script setup>
import { BookmarkPlus, Download, Send, X } from '@lucide/vue'
import { tr } from '../i18n/index.js'
import { formatShort } from '../utils/format.js'
import RowActionsMenu from './RowActionsMenu.vue'

defineProps({
  convo: { type: Object, required: true },
  active: { type: Boolean, default: false },
  indent: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'transfer', 'export', 'save-template', 'delete'])

const lastTs = (c) => c.messages.at(-1)?.createdAt
</script>

<template>
  <div
    class="group relative rounded hover:bg-surface2"
    :class="[active && 'bg-surface2', indent && 'ml-2']"
  >
    <button
      class="w-full rounded-md px-2 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-focus"
      @click="emit('select')"
    >
      <div class="truncate pr-8 text-sm">{{ convo.title }}</div>
      <div class="mt-0.5 flex justify-between text-[10px] text-muted">
        <span>{{ $t('sidebar.messageCount', convo.messages.length, { count: convo.messages.length }) }}</span>
        <span>{{ formatShort(lastTs(convo)) }}</span>
      </div>
    </button>
    <div class="absolute right-1 top-1.5">
      <RowActionsMenu :actions="[
        { label: tr('sidebar.transferConversation'), icon: Send, onSelect: () => emit('transfer') },
        { label: tr('sidebar.exportConversation'), icon: Download, onSelect: () => emit('export') },
        { label: tr('settings.saveTemplate'), icon: BookmarkPlus, onSelect: () => emit('save-template') },
        { label: tr('common.delete'), icon: X, danger: true, onSelect: () => emit('delete') },
      ]" />
    </div>
  </div>
</template>
