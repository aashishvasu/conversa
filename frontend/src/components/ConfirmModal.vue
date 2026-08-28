<script setup>
import {
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
      <AlertDialogContent class="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-edge bg-surface p-4 text-base shadow-xl outline-none focus-visible:ring-2 focus-visible:ring-focus">
        <AlertDialogTitle class="text-sm font-medium">{{ $t('confirm.title') }}</AlertDialogTitle>
        <AlertDialogDescription class="mt-3 text-sm">{{ confirmState.message }}</AlertDialogDescription>
        <div class="mt-4 flex justify-end gap-2">
          <AlertDialogCancel class="inline-flex h-9 items-center rounded-md px-3 text-sm font-medium outline-none hover:bg-surface2 focus-visible:ring-2 focus-visible:ring-focus">{{ $t('common.cancel') }}</AlertDialogCancel>
          <!-- AlertDialogAction's built-in close can fire before the click handler, letting the update:open dismissal above resolve the confirm as false first.
               Resolving true nulls confirmState, so the v-if unmounts the dialog and the confirm button needs no built-in close. -->
          <button class="inline-flex h-9 items-center rounded-md bg-danger px-3 text-sm font-medium text-on-danger outline-none hover:opacity-90 focus-visible:ring-2 focus-visible:ring-focus" @click="answerConfirm(true)">{{ confirmState.label }}</button>
        </div>
      </AlertDialogContent>
    </AlertDialogPortal>
  </AlertDialogRoot>
</template>
