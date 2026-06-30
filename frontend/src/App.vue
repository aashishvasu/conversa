<script setup>
import { onMounted, ref } from 'vue'
import { authed, fetchModels, fetchSettings, getToken, logout } from './api.js'
import { cacheModels, initStore, setGlobalSettings } from './store.js'
import ChatPane from './components/ChatPane.vue'
import ConfirmModal from './components/ConfirmModal.vue'
import Login from './components/Login.vue'
import Sidebar from './components/Sidebar.vue'

const ready = ref(false)

onMounted(async () => {
  await initStore()
  if (getToken()) {
    try {
      await onAuthed(await fetchSettings()) // saved token still valid → skip login
    } catch {
      logout()
    }
  }
  ready.value = true
})

async function onAuthed(settings) {
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
  <div v-else class="flex h-dvh">
    <Sidebar />
    <ChatPane />
  </div>
  <ConfirmModal />
</template>
