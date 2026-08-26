<script setup>
import { EllipsisVertical } from '@lucide/vue'
import { DropdownMenuContent, DropdownMenuItem, DropdownMenuPortal, DropdownMenuRoot, DropdownMenuTrigger } from 'reka-ui'

// One dropdown for a sidebar row's actions (export, delete, ...), replacing per-row hover icon strips.
// actions: [{ label, icon, danger?, onSelect }]
defineProps({ actions: { type: Array, required: true } })
</script>

<template>
  <DropdownMenuRoot>
    <DropdownMenuTrigger
      class="rounded p-1 text-muted opacity-40 hover:bg-surface2 hover:text-base group-hover:opacity-100 pointer-coarse:opacity-100 data-[state=open]:opacity-100 data-[state=open]:bg-surface2"
      title="Actions"
    >
      <EllipsisVertical :size="14" />
    </DropdownMenuTrigger>
    <DropdownMenuPortal>
      <DropdownMenuContent class="z-30 min-w-36 rounded border border-edge bg-surface p-1 text-sm shadow-lg" :side-offset="4" align="end">
        <DropdownMenuItem
          v-for="a in actions"
          :key="a.label"
          class="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 outline-none data-[highlighted]:bg-surface2"
          :class="a.danger && 'text-red-500'"
          @select="a.onSelect"
        >
          <component :is="a.icon" :size="14" />{{ a.label }}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
