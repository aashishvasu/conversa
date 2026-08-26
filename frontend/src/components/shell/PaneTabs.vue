<script setup>
import { DollarSign, MessageSquare, Telescope } from '@lucide/vue'
import { TabsList, TabsTrigger } from 'reka-ui'

// App.vue owns the TabsRoot so this list shares it with every pane.
</script>

<template>
  <TabsList class="flex gap-1 rounded bg-surface2 p-1 text-sm">
    <TabsTrigger value="chat" class="flex flex-1 items-center justify-center gap-1.5 rounded px-2 py-1.5 text-muted outline-none data-[state=active]:bg-surface data-[state=active]:text-base">
      <MessageSquare :size="14" /> Chat
    </TabsTrigger>
    <TabsTrigger value="research" class="flex flex-1 items-center justify-center gap-1.5 rounded px-2 py-1.5 text-muted outline-none data-[state=active]:bg-surface data-[state=active]:text-base">
      <Telescope :size="14" /> Research
    </TabsTrigger>
    <TabsTrigger value="usage" class="flex flex-1 items-center justify-center gap-1.5 rounded px-2 py-1.5 text-muted outline-none data-[state=active]:bg-surface data-[state=active]:text-base">
      <DollarSign :size="14" /> Usage
    </TabsTrigger>
  </TabsList>
</template>
