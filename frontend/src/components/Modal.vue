<script setup>
import { X } from '@lucide/vue'
import { DialogClose, DialogContent, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
defineProps({ title: String })
const emit = defineEmits(['close'])
</script>

<template>
  <DialogRoot :open="true" @update:open="open => !open && emit('close')">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-40 bg-black/50" />
      <DialogContent class="fixed left-1/2 top-1/2 z-50 flex min-h-0 max-h-[85vh] w-full max-w-lg -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl border border-edge bg-surface text-base shadow-xl outline-none focus-visible:ring-2 focus-visible:ring-focus max-sm:inset-0 max-sm:max-h-none max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none">
        <div class="flex items-center justify-between border-b border-edge px-4 py-3">
          <DialogTitle class="text-sm font-medium">{{ title }}</DialogTitle>
          <DialogClose class="inline-flex size-8 items-center justify-center rounded-md text-muted outline-none hover:bg-surface2 hover:text-base focus-visible:ring-2 focus-visible:ring-focus" :aria-label="$t('common.close')"><X :size="16" /></DialogClose>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto">
          <div class="p-4"><slot /></div>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
