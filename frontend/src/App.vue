<script setup>
import { onMounted, ref } from 'vue'
import { TabsContent, TabsRoot } from 'reka-ui'
import { authed, fetchModels, fetchSettings, getToken, logout } from './api.js'
import { activePane, cacheModels, initStore, setGlobalSettings } from './store.js'
import { initUsage } from './usage.js'
import { dismiss, notify } from './utils/notify.js'
import ConfirmModal from './components/ConfirmModal.vue'
import Notifications from './components/Notifications.vue'
import ChatPane from './views/ChatPane.vue'
import Login from './views/Login.vue'
import ResearchPane from './views/ResearchPane.vue'
import Sidebar from './views/Sidebar.vue'

// One state for the boot pipeline, not the three independent flags (ready/bootError/serverError)
// this used to be: they only ever combined into one of four sequential stages, so nothing prevented
// a future edit from setting two of them at once. `authed` (from api.js) stays separate: unlike this
// pipeline, it flips at any point in the session (a 401 logs it out again), not just once at boot.
const bootState = ref('loading') // 'loading' | 'bootError' | 'serverError' | 'ready'
// initStore() failing means IndexedDB could not be read (blocked, corrupt), so there is nothing to show and nothing to export. The raw error is the page.
const bootErrorMessage = ref('')
const serverErrorMessage = ref('')

onMounted(async () => {
  try {
    await Promise.all([initStore(), initUsage()])
  } catch (e) {
    bootErrorMessage.value = String(e?.stack || e)
    bootState.value = 'bootError'
    return
  }
  if (getToken()) await loadSettings()
  else bootState.value = 'ready'
})

async function loadSettings() {
  try {
    await onAuthed(await fetchSettings())
    bootState.value = 'ready'
  } catch (e) {
    // No token means a 401 already logged us out mid-request: that is Login's job, not an error page.
    if (getToken()) {
      serverErrorMessage.value = e.message
      bootState.value = 'serverError'
    } else {
      bootState.value = 'ready'
    }
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
  <div v-if="bootState === 'bootError'" class="flex h-dvh flex-col items-center justify-center gap-3 bg-app p-6 text-base">
    <p class="text-sm">Stored conversations could not be read from this browser.</p>
    <pre class="max-h-[50vh] w-full max-w-2xl overflow-auto rounded-lg border border-edge bg-surface p-3 text-xs">{{ bootErrorMessage }}</pre>
    <button class="rounded bg-surface2 px-3 py-1.5 text-sm hover:opacity-80" @click="reload">Retry</button>
  </div>
  <div v-else-if="bootState === 'serverError'" class="flex h-dvh flex-col items-center justify-center gap-3 bg-app p-6 text-base">
    <p class="text-sm">Could not reach the server.</p>
    <pre class="max-h-[50vh] w-full max-w-2xl overflow-auto rounded-lg border border-edge bg-surface p-3 text-xs">{{ serverErrorMessage }}</pre>
    <button class="rounded bg-surface2 px-3 py-1.5 text-sm hover:opacity-80" @click="loadSettings">Retry</button>
  </div>
  <div v-else-if="bootState === 'loading'" class="flex h-dvh items-center justify-center bg-app text-muted">
    Loading…
  </div>
  <Login v-else-if="!authed" @authenticated="onAuthed" />
  <div v-else class="flex h-dvh flex-col">
    <Notifications />
    <!-- TabsRoot is the shared ancestor for Sidebar's PaneTabs triggers and the TabsContent panes below;
         manual activation keeps arrow-key nav from switching away from a streaming chat. -->
    <TabsRoot v-model="activePane" activation-mode="manual" class="flex min-h-0 flex-1">
      <Sidebar />
      <TabsContent value="chat" class="min-w-0 flex-1 data-[state=inactive]:hidden data-[state=active]:flex">
        <ChatPane />
      </TabsContent>
      <TabsContent value="research" class="min-w-0 flex-1 data-[state=inactive]:hidden data-[state=active]:flex">
        <ResearchPane />
      </TabsContent>
    </TabsRoot>
  </div>
  <ConfirmModal />
</template>
