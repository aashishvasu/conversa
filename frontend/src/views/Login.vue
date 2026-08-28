<script setup>
import { ref } from 'vue'
import { fetchSettings, login } from '../api/client.js'
import UiButton from '../components/ui/UiButton.vue'

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
    <form class="w-80 space-y-4 rounded-xl border border-edge bg-surface p-6 shadow-xl" @submit.prevent="submit">
      <div class="flex flex-col items-center gap-2">
        <img src="/logo.png" alt="conversa" class="h-16 w-16" />
        <h1 class="text-xl font-semibold">conversa</h1>
      </div>
      <input
        v-model="pw"
        type="password"
        :placeholder="$t('login.password')"
        autofocus
        class="h-10 w-full rounded-md border border-edge bg-surface2 px-3 outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-app"
      />
      <p v-if="error" class="text-sm text-danger">{{ error }}</p>
      <UiButton type="submit" variant="primary" class="w-full" :loading="busy">
        {{ busy ? $t('login.checking') : $t('login.unlock') }}
      </UiButton>
    </form>
  </div>
</template>
