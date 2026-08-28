<script setup>
import { ScrollAreaRoot, ScrollAreaScrollbar, ScrollAreaThumb, ScrollAreaViewport } from 'reka-ui'
</script>

<template>
  <ScrollAreaRoot type="hover" class="min-h-0 overflow-hidden">
    <ScrollAreaViewport class="size-full">
      <slot />
    </ScrollAreaViewport>
    <ScrollAreaScrollbar orientation="vertical" class="flex w-2 touch-none select-none p-0.5">
      <ScrollAreaThumb class="flex-1 rounded-full bg-muted/40" />
    </ScrollAreaScrollbar>
  </ScrollAreaRoot>
</template>
