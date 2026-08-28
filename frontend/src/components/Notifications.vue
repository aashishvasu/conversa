<script setup>
import { X } from '@lucide/vue'
import { computed } from 'vue'
// WHY: Reka Toast owns focus, announcements, timers, and swipe dismissal; a local stack would reimplement them.
import { ToastAction, ToastClose, ToastDescription, ToastProvider, ToastRoot, ToastTitle, ToastViewport } from 'reka-ui'
import { dismiss, notifications } from '../utils/notify.js'
import UiButton from './ui/UiButton.vue'
import UiIconButton from './ui/UiIconButton.vue'

const sticky = computed(() => notifications.value.filter((n) => n.sticky))
const transient = computed(() => notifications.value.filter((n) => !n.sticky))

function classes(n) {
  return n.severity === 'warning'
    ? 'border-warning/40 bg-warning/10 text-warning'
    : 'border-danger/40 bg-danger/10 text-danger'
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
        <UiButton v-if="n.action" class="shrink-0" size="compact" @click="n.action.fn">{{ n.action.label }}</UiButton>
        <UiIconButton class="shrink-0" :label="$t('common.dismiss')" @click="dismiss(n.id)"><X :size="14" /></UiIconButton>
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
      <ToastAction v-if="n.action" :alt-text="n.action.label" class="mt-2 mr-2 inline-flex h-8 items-center rounded-md border border-edge bg-surface2 px-2 text-xs font-medium outline-none hover:bg-edge focus-visible:ring-2 focus-visible:ring-focus" @click="n.action.fn">{{ n.action.label }}</ToastAction>
      <ToastClose class="mt-2 inline-flex h-8 items-center rounded-md px-2 text-xs outline-none hover:bg-surface2 focus-visible:ring-2 focus-visible:ring-focus">{{ $t('common.dismiss') }}</ToastClose>
    </ToastRoot>
    <ToastViewport class="fixed right-3 bottom-3 z-50 flex w-[min(24rem,calc(100vw-1.5rem))] flex-col-reverse gap-2 outline-none" />
  </ToastProvider>
</template>
