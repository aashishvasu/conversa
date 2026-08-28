<script setup>
import { TooltipContent, TooltipPortal, TooltipRoot, TooltipTrigger } from 'reka-ui'

defineProps({ content: { type: String, required: true } })
</script>

<template>
  <TooltipRoot>
    <TooltipTrigger as-child><slot /></TooltipTrigger>
    <TooltipPortal>
      <TooltipContent class="z-[70] max-w-64 rounded-md border border-edge bg-surface px-2 py-1 text-xs shadow-lg" :side-offset="6">
        {{ content }}
      </TooltipContent>
    </TooltipPortal>
  </TooltipRoot>
</template>
