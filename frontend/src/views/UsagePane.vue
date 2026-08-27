<script setup>
import { Menu } from '@lucide/vue'
import { computed, ref } from 'vue'
import SpendBadge from '../components/SpendBadge.vue'
import { sidebarOpen } from '../state/store.js'
import { usageDays, usageRows } from '../state/usage.js'

const start = ref('')
const end = ref('')
const rangeError = computed(() => start.value && end.value && start.value > end.value)
const rows = computed(() => rangeError.value ? [] : usageRows(usageDays(), start.value, end.value))

function clearRange() {
  start.value = end.value = ''
}
</script>

<template>
  <main class="flex min-w-0 flex-1 flex-col bg-app">
    <header class="flex items-center gap-2 border-b border-edge px-3 py-2">
      <button class="rounded p-1.5 hover:bg-surface2 md:hidden" :title="$t('sidebar.menu')" @click="sidebarOpen = true"><Menu :size="16" /></button>
      <div>
        <p class="text-sm font-medium">{{ $t('usage.title') }}</p>
        <p class="text-xs text-muted">{{ $t('usage.subtitle') }}</p>
      </div>
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto p-4">
      <div class="mx-auto max-w-5xl space-y-4">
        <div class="flex flex-wrap items-end gap-3 text-sm">
          <label class="grid gap-1 text-xs text-muted">{{ $t('usage.from') }}
            <input v-model="start" :max="end || undefined" type="date" class="rounded bg-surface2 px-2 py-1.5 text-sm text-base outline-none" />
          </label>
          <label class="grid gap-1 text-xs text-muted">{{ $t('usage.to') }}
            <input v-model="end" :min="start || undefined" type="date" class="rounded bg-surface2 px-2 py-1.5 text-sm text-base outline-none" />
          </label>
          <button v-if="start || end" class="rounded px-2 py-1.5 text-sm text-muted hover:bg-surface2 hover:text-base" @click="clearRange">{{ $t('usage.allTime') }}</button>
        </div>

        <p v-if="rangeError" class="text-sm text-red-500" role="alert">{{ $t('usage.badRange') }}</p>
        <p v-else-if="!rows.length" class="py-12 text-center text-sm text-muted">{{ $t('usage.empty') }}</p>
        <div v-else class="overflow-x-auto rounded border border-edge">
          <table class="w-full text-left text-sm">
            <thead class="border-b border-edge bg-surface2 text-xs uppercase tracking-wide text-muted">
              <tr><th scope="col" class="px-3 py-2 font-medium">{{ $t('common.model') }}</th><th scope="col" class="px-3 py-2 font-medium">{{ $t('usage.kind') }}</th><th scope="col" class="px-3 py-2 font-medium">{{ $t('usage.usage') }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="`${row.model}:${row.kind}`" class="border-b border-edge last:border-0">
                <td class="px-3 py-2 font-mono text-xs">{{ row.model }}</td>
                <td class="px-3 py-2 capitalize">{{ row.kind }}</td>
                <td class="whitespace-nowrap px-3 py-2"><SpendBadge :spend="row" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </main>
</template>
