<script setup>
import { Boxes, DollarSign, MessageSquare, Telescope } from '@lucide/vue'
import { TabsList, TabsTrigger } from 'reka-ui'

const tabs = [
  { value: 'chat', icon: MessageSquare },
  { value: 'research', icon: Telescope },
  { value: 'workspaces', icon: Boxes },
  { value: 'usage', icon: DollarSign },
]
</script>

<template>
  <TabsList class="flex flex-col gap-0.5 text-sm">
    <TabsTrigger
      v-for="tab in tabs"
      :key="tab.value"
      :value="tab.value"
      class="flex h-9 items-center gap-2 rounded-md border-l-2 border-transparent px-2 text-muted outline-none transition-colors hover:bg-surface2 focus-visible:ring-2 focus-visible:ring-focus data-[state=active]:border-accent data-[state=active]:bg-accent/10 data-[state=active]:text-base"
    >
      <component :is="tab.icon" :size="14" /> {{ $t(`sidebar.${tab.value}`) }}
    </TabsTrigger>
  </TabsList>
</template>
