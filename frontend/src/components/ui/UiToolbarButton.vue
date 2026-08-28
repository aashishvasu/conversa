<script setup>
import { ToolbarButton, TooltipContent, TooltipPortal, TooltipRoot, TooltipTrigger } from 'reka-ui'

defineOptions({ inheritAttrs: false })

defineProps({
  label: { type: String, required: true },
  danger: Boolean,
  active: Boolean,
})
</script>

<template>
  <TooltipRoot>
    <TooltipTrigger as-child>
      <ToolbarButton
        v-bind="$attrs"
        type="button"
        :aria-label="label"
        class="inline-flex size-8 items-center justify-center rounded-md text-muted outline-none transition-colors hover:bg-surface2 hover:text-base focus-visible:ring-2 focus-visible:ring-focus data-[orientation=horizontal]:shrink-0"
        :class="[danger && 'hover:bg-danger/10 hover:text-danger', active && 'bg-accent/10 text-accent']"
      >
        <slot />
      </ToolbarButton>
    </TooltipTrigger>
    <TooltipPortal>
      <TooltipContent class="z-[70] max-w-64 rounded-md border border-edge bg-surface px-2 py-1 text-xs shadow-lg" :side-offset="6">
        {{ label }}
      </TooltipContent>
    </TooltipPortal>
  </TooltipRoot>
</template>
