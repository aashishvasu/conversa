<script setup>
import { MessageSquare, Telescope } from '@lucide/vue'
import { TabsList, TabsTrigger } from 'reka-ui'

// Chat/Research mode switch: a segmented control (single-select, tab look). Renders inside the
// TabsRoot App.vue wraps around Sidebar and the panes, so trigger and panel share one Reka vocabulary.
</script>

<template>
  <TabsList class="flex gap-1 rounded bg-surface2 p-1 text-sm">
    <TabsTrigger value="chat" class="flex flex-1 items-center justify-center gap-1.5 rounded px-2 py-1.5 text-muted outline-none data-[state=active]:bg-surface data-[state=active]:text-base">
      <MessageSquare :size="14" /> Chat
    </TabsTrigger>
    <TabsTrigger value="research" class="flex flex-1 items-center justify-center gap-1.5 rounded px-2 py-1.5 text-muted outline-none data-[state=active]:bg-surface data-[state=active]:text-base">
      <Telescope :size="14" /> Research
    </TabsTrigger>
  </TabsList>
</template>
