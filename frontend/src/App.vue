<script setup>
import { onMounted, ref } from 'vue'
import { authed, fetchModels, fetchSettings, getToken, logout } from './api.js'
import { cacheModels, currentRunId, downloadExport, initStore, setGlobalSettings, storageError } from './store.js'
import ChatPane from './components/ChatPane.vue'
import ConfirmModal from './components/ConfirmModal.vue'
import Login from './components/Login.vue'
import ResearchPane from './components/ResearchPane.vue'
import Sidebar from './components/Sidebar.vue'

const ready = ref(false)
// initStore() failing means IndexedDB could not be read (blocked, corrupt), so there is nothing to show and nothing to export. The raw error is the page.
const bootError = ref(null)
// Server-side config problems (missing provider key, unusable DEFAULT_MODEL).
// Shown once, dismissible.
// It is the only place the user learns why a model vanished from the dropdown, or why a utility model stopped producing titles and memory.
const configErrors = ref([])

onMounted(async () => {
  try {
    await initStore()
  } catch (e) {
    bootError.value = String(e?.stack || e)
    return
  }
  if (getToken()) {
    try {
      await onAuthed(await fetchSettings()) // saved token still valid, so skip login
    } catch {
      logout()
    }
  }
  ready.value = true
})

function reload() {
  location.reload()
}

async function onAuthed({ config_errors: errors, ...settings }) {
  configErrors.value = errors || []
  setGlobalSettings(settings)
  authed.value = true
  try {
    cacheModels(await fetchModels())
  } catch { /* keep whatever's cached */ }
}
</script>

<template>
  <div v-if="bootError" class="flex h-dvh flex-col items-center justify-center gap-3 bg-app p-6 text-base">
    <p class="text-sm">Stored conversations could not be read from this browser.</p>
    <pre class="max-h-[50vh] w-full max-w-2xl overflow-auto rounded-lg border border-edge bg-surface p-3 text-xs">{{ bootError }}</pre>
    <button class="rounded bg-surface2 px-3 py-1.5 text-sm hover:opacity-80" @click="reload">Retry</button>
  </div>
  <div v-else-if="!ready" class="flex h-dvh items-center justify-center bg-app text-muted">
    Loading…
  </div>
  <Login v-else-if="!authed" @authenticated="onAuthed" />
  <div v-else class="flex h-dvh flex-col">
    <div
      v-if="storageError"
      class="border-b border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-700 dark:text-red-300"
    >
      <div class="flex items-center justify-between gap-2">
        <p>Saving to browser storage is failing. Changes exist only in memory until it recovers, so download a backup now.</p>
        <button class="shrink-0 rounded bg-red-600 px-2 py-1 text-white hover:bg-red-500" @click="downloadExport()">Download backup</button>
      </div>
      <pre class="mt-1.5 overflow-x-auto rounded bg-surface p-2">{{ storageError }}</pre>
    </div>
    <div
      v-if="configErrors.length"
      class="flex items-start gap-2 border-b border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300"
    >
      <div class="flex-1 space-y-0.5">
        <p v-for="e in configErrors" :key="e">{{ e }}</p>
      </div>
      <button class="shrink-0 px-1 opacity-70 hover:opacity-100" title="Dismiss" @click="configErrors = []">✕</button>
    </div>
    <div class="flex min-h-0 flex-1">
      <Sidebar />
      <!-- A run and a conversation are siblings, so selecting one is what swaps the pane. -->
      <ResearchPane v-if="currentRunId" />
      <ChatPane v-else />
    </div>
  </div>
  <ConfirmModal />
</template>
