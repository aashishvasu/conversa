<script setup>
import { onMounted, ref } from 'vue'
import { authed, fetchModels, fetchSettings, getToken, logout } from './api.js'
import { cacheModels, currentRunId, initStore, setGlobalSettings } from './store.js'
import { initUsage } from './usage.js'
import { dismiss, notify } from './utils/notify.js'
import ConfirmModal from './components/ConfirmModal.vue'
import Notifications from './components/Notifications.vue'
import ChatPane from './views/ChatPane.vue'
import Login from './views/Login.vue'
import ResearchPane from './views/ResearchPane.vue'
import Sidebar from './views/Sidebar.vue'

const ready = ref(false)
// initStore() failing means IndexedDB could not be read (blocked, corrupt), so there is nothing to show and nothing to export. The raw error is the page.
const bootError = ref(null)
const serverError = ref('')

onMounted(async () => {
  try {
    await Promise.all([initStore(), initUsage()])
  } catch (e) {
    bootError.value = String(e?.stack || e)
    return
  }
  if (getToken()) await loadSettings()
  ready.value = true
})

async function loadSettings() {
  serverError.value = ''
  try {
    await onAuthed(await fetchSettings())
  } catch (e) {
    if (getToken()) serverError.value = e.message
  }
}

function reload() {
  location.reload()
}

async function onAuthed({ config_errors: errors, ...settings }) {
  if (errors?.length) notify({ key: 'config', severity: 'warning', sticky: true, text: errors.join(' ') })
  else dismiss('config')
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
  <div v-else-if="serverError" class="flex h-dvh flex-col items-center justify-center gap-3 bg-app p-6 text-base">
    <p class="text-sm">Could not reach the server.</p>
    <pre class="max-h-[50vh] w-full max-w-2xl overflow-auto rounded-lg border border-edge bg-surface p-3 text-xs">{{ serverError }}</pre>
    <button class="rounded bg-surface2 px-3 py-1.5 text-sm hover:opacity-80" @click="loadSettings">Retry</button>
  </div>
  <div v-else-if="!ready" class="flex h-dvh items-center justify-center bg-app text-muted">
    Loading…
  </div>
  <Login v-else-if="!authed" @authenticated="onAuthed" />
  <div v-else class="flex h-dvh flex-col">
    <Notifications />
    <div class="flex min-h-0 flex-1">
      <Sidebar />
      <!-- A run and a conversation are siblings, so selecting one is what swaps the pane. -->
      <ResearchPane v-if="currentRunId" />
      <ChatPane v-else />
    </div>
  </div>
  <ConfirmModal />
</template>
