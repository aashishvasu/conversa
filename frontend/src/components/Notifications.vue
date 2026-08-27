<script setup>
import { computed } from 'vue'
// WHY: Reka Toast owns focus, announcements, timers, and swipe dismissal; a local stack would reimplement them.
import { ToastAction, ToastClose, ToastDescription, ToastProvider, ToastRoot, ToastTitle, ToastViewport } from 'reka-ui'
import { dismiss, notifications } from '../utils/notify.js'

const sticky = computed(() => notifications.value.filter((n) => n.sticky))
const transient = computed(() => notifications.value.filter((n) => !n.sticky))

function classes(n) {
  return n.severity === 'warning'
    ? 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300'
    : 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300'
}
</script>

<template>
  <ToastProvider :duration="5000">
    <div v-if="sticky.length" class="border-b border-edge">
      <div v-for="n in sticky" :key="n.id" class="flex items-start gap-2 border-b px-3 py-2 text-xs last:border-b-0" :class="classes(n)">
        <div class="min-w-0 flex-1 space-y-1">
          <p>{{ n.text }}<span v-if="n.count > 1"> ({{ n.count }})</span></p>
          <pre v-if="n.detail" class="overflow-x-auto rounded bg-surface p-2">{{ n.detail }}</pre>
        </div>
        <button v-if="n.action" class="shrink-0 rounded bg-surface2 px-2 py-1 hover:opacity-80" @click="n.action.fn">{{ n.action.label }}</button>
        <button class="shrink-0 px-1 opacity-70 hover:opacity-100" :title="$t('common.dismiss')" @click="dismiss(n.id)">✕</button>
      </div>
    </div>

    <ToastRoot
      v-for="n in transient"
      :key="n.id"
      :open="true"
      :type="n.foreground ? 'foreground' : 'background'"
      :class="['rounded-lg border p-3 text-sm shadow-lg', classes(n)]"
      @update:open="(open) => !open && dismiss(n.id)"
    >
      <ToastTitle class="font-medium">{{ n.severity === 'warning' ? $t('notification.warning') : $t('notification.error') }}</ToastTitle>
      <ToastDescription class="mt-1">{{ n.text }}<span v-if="n.count > 1"> ({{ n.count }})</span></ToastDescription>
      <ToastAction v-if="n.action" :alt-text="n.action.label" class="mt-2 mr-2 rounded bg-surface2 px-2 py-1 text-xs hover:opacity-80" @click="n.action.fn">{{ n.action.label }}</ToastAction>
      <ToastClose class="mt-2 rounded px-2 py-1 text-xs hover:bg-surface2">{{ $t('common.dismiss') }}</ToastClose>
    </ToastRoot>
    <ToastViewport class="fixed right-3 bottom-3 z-50 flex w-[min(24rem,calc(100vw-1.5rem))] flex-col-reverse gap-2 outline-none" />
  </ToastProvider>
</template>
