<script setup>
import { ref } from 'vue'
import { fetchSettings, login } from '../api.js'

const emit = defineEmits(['authenticated'])
const pw = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  busy.value = true
  error.value = ''
  try {
    await login(pw.value)
    emit('authenticated', await fetchSettings())
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex h-dvh items-center justify-center bg-app text-base">
    <form class="w-80 space-y-4 rounded-lg bg-surface p-6 shadow-lg" @submit.prevent="submit">
      <div class="flex flex-col items-center gap-2">
        <img src="/logo.png" alt="conversa" class="h-16 w-16" />
        <h1 class="text-xl font-semibold">conversa</h1>
      </div>
      <input
        v-model="pw"
        type="password"
        placeholder="Password"
        autofocus
        class="w-full rounded bg-surface2 px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500"
      />
      <p v-if="error" class="text-sm text-red-500">{{ error }}</p>
      <button
        type="submit"
        :disabled="busy"
        class="w-full rounded bg-indigo-600 py-2 font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
      >
        {{ busy ? 'Checking…' : 'Unlock' }}
      </button>
    </form>
  </div>
</template>
