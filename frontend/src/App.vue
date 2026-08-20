<script setup>
import { onMounted, ref } from 'vue'
import { authed, fetchModels, fetchSettings, getToken, logout } from './api.js'
import { cacheModels, currentRunId, initStore, setGlobalSettings } from './store.js'
import ChatPane from './components/ChatPane.vue'
import ConfirmModal from './components/ConfirmModal.vue'
import Login from './components/Login.vue'
import ResearchPane from './components/ResearchPane.vue'
import Sidebar from './components/Sidebar.vue'

const ready = ref(false)
// Server-side config problems (missing provider key, unusable DEFAULT_MODEL).
// Shown once, dismissible.
// It is the only place the user learns why a model vanished from the dropdown, or why a utility model stopped producing titles and memory.
const configErrors = ref([])

onMounted(async () => {
  await initStore()
  if (getToken()) {
    try {
      await onAuthed(await fetchSettings()) // saved token still valid, so skip login
    } catch {
      logout()
    }
  }
  ready.value = true
})

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
  <div v-if="!ready" class="flex h-dvh items-center justify-center bg-app text-muted">
    Loading…
  </div>
  <Login v-else-if="!authed" @authenticated="onAuthed" />
  <div v-else class="flex h-dvh flex-col">
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
