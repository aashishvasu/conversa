<script setup>
import {
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogRoot,
  AlertDialogTitle,
} from 'reka-ui'
import { answerConfirm, confirmState } from '../utils/confirm.js'
</script>

<template>
  <AlertDialogRoot v-if="confirmState" :open="true" @update:open="open => !open && confirmState && answerConfirm(false)">
    <AlertDialogPortal>
      <AlertDialogOverlay class="fixed inset-0 z-40 bg-black/50" />
      <AlertDialogContent class="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg bg-surface p-4 text-base shadow-xl">
        <AlertDialogTitle class="text-sm font-medium">Please confirm</AlertDialogTitle>
        <AlertDialogDescription class="mt-3 text-sm">{{ confirmState.message }}</AlertDialogDescription>
        <div class="mt-4 flex justify-end gap-2">
          <AlertDialogCancel class="rounded px-3 py-1.5 text-sm hover:bg-surface2">Cancel</AlertDialogCancel>
          <AlertDialogAction class="rounded bg-danger px-3 py-1.5 text-sm font-medium text-on-danger hover:opacity-90" @click="answerConfirm(true)">{{ confirmState.label }}</AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialogPortal>
  </AlertDialogRoot>
</template>
