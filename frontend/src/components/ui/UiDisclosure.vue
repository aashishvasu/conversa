<script setup>
import { ChevronRight } from '@lucide/vue'
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from 'reka-ui'

const props = defineProps({
  defaultOpen: Boolean,
  padded: { type: Boolean, default: true },
})
</script>

<template>
  <CollapsibleRoot v-slot="{ open }" :default-open="defaultOpen" class="overflow-hidden rounded-md border border-edge bg-surface">
    <div class="flex min-h-9 items-center gap-1 px-2">
      <CollapsibleTrigger as-child>
        <button type="button" class="flex min-w-0 flex-1 items-center gap-2 rounded-sm py-1.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-focus">
          <ChevronRight :size="14" class="shrink-0 text-muted transition-transform" :class="open && 'rotate-90'" />
          <slot name="title" />
        </button>
      </CollapsibleTrigger>
      <slot name="actions" />
    </div>
    <CollapsibleContent class="ui-disclosure-content border-t border-edge" :class="padded && 'p-2'">
      <slot />
    </CollapsibleContent>
  </CollapsibleRoot>
</template>
