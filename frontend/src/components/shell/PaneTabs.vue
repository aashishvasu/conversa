<script setup>
import { Boxes, DollarSign, MessageSquare, Telescope } from '@lucide/vue'
import { TabsList, TabsTrigger } from 'reka-ui'

// App.vue owns the TabsRoot so this list shares it with the panes.
// Each tab scopes the sidebar sublist below it: Chat lists chat conversations, Research lists research-mode ones, Workspaces lists workspaces, Usage has none.
</script>

<template>
  <TabsList class="flex flex-col gap-0.5 text-sm">
    <TabsTrigger value="chat" class="flex items-center gap-2 rounded px-2 py-1.5 text-muted outline-none hover:bg-surface2 data-[state=active]:bg-surface2 data-[state=active]:text-base">
      <MessageSquare :size="14" /> Chat
    </TabsTrigger>
    <TabsTrigger value="research" class="flex items-center gap-2 rounded px-2 py-1.5 text-muted outline-none hover:bg-surface2 data-[state=active]:bg-surface2 data-[state=active]:text-base">
      <Telescope :size="14" /> Research
    </TabsTrigger>
    <TabsTrigger value="workspaces" class="flex items-center gap-2 rounded px-2 py-1.5 text-muted outline-none hover:bg-surface2 data-[state=active]:bg-surface2 data-[state=active]:text-base">
      <Boxes :size="14" /> Workspaces
    </TabsTrigger>
    <TabsTrigger value="usage" class="flex items-center gap-2 rounded px-2 py-1.5 text-muted outline-none hover:bg-surface2 data-[state=active]:bg-surface2 data-[state=active]:text-base">
      <DollarSign :size="14" /> Usage
    </TabsTrigger>
  </TabsList>
</template>
