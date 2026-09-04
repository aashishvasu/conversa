<script setup>
import { ref } from 'vue'
import { createTransfer, retrieveTransfer } from '../api/client.js'
import { exportData, importData, restoreData, snapshotInfo } from '../state/store.js'
import { locale, restorePrefs } from '../utils/prefs.js'
import { restoreTheme } from '../utils/theme.js'
import { confirmDelete } from '../utils/confirm.js'
import { normalizePhrase } from '../utils/phrase.js'
import { tr } from '../i18n.js'
import UiButton from './ui/UiButton.vue'

const props = defineProps({
  scope: { type: String, required: true }, // 'conversation' | 'snapshot'
  convoId: { type: String, default: null }, // conversation export source
  showRetrieve: { type: Boolean, default: true },
})

const phrase = ref('')
const expiry = ref('')
const phraseInput = ref('')
const phraseInputId = 'transfer-phrase-' + Math.random().toString(36).slice(2)
const msg = ref('')
const busy = ref(false)
const copied = ref(false)

async function onCreate() {
  busy.value = true
  msg.value = ''
  phrase.value = ''
  try {
    const data = props.scope === 'conversation' ? exportData(props.convoId) : exportData()
    const result = await createTransfer(props.scope, data)
    phrase.value = result.phrase
    expiry.value = new Date(result.expires_at).toLocaleString(locale.value)
  } catch (err) {
    msg.value = tr('transfer.createFailed', { error: err.message })
  } finally {
    busy.value = false
  }
}

async function onRetrieve() {
  const key = normalizePhrase(phraseInput.value)
  if (!key) {
    msg.value = tr('transfer.badPhrase')
    return
  }
  busy.value = true
  msg.value = ''
  try {
    const result = await retrieveTransfer(key)
    if (result.scope === 'snapshot') {
      const info = snapshotInfo(result.data)
      if (!info) throw new Error(tr('transfer.notSnapshot'))
      const date = info.exportedAt ? new Date(info.exportedAt).toLocaleString(locale.value) : tr('import.unknownDate')
      if (!await confirmDelete(tr('confirm.restore', { ...info, date }), tr('common.restore'))) return
      const prefs = await restoreData(result.data)
      restorePrefs(prefs)
      restoreTheme(prefs.theme)
      msg.value = tr('import.snapshotRestored')
    } else {
      const added = await importData(result.data)
      msg.value = added ? tr('import.imported', added, { count: added }) : tr('import.nothing')
    }
  } catch (err) {
    msg.value = tr('transfer.retrieveFailed', { error: err.message })
  } finally {
    busy.value = false
  }
}

async function copyPhrase() {
  try {
    await navigator.clipboard.writeText(phrase.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch { /* clipboard unavailable; the phrase stays selectable */ }
}
</script>

<template>
  <div class="space-y-3">
    <p class="text-xs text-muted">
      {{ scope === 'snapshot' ? $t('transfer.helpSnapshot') : $t('transfer.helpConversation') }}
    </p>

    <UiButton class="w-full" :disabled="busy" @click="onCreate">
      {{ scope === 'snapshot' ? $t('transfer.createSnapshot') : $t('transfer.createConversation') }}
    </UiButton>

    <div v-if="phrase" class="rounded bg-surface2 p-3">
      <div class="flex items-center justify-between gap-2">
        <code class="min-w-0 break-all text-sm">{{ phrase }}</code>
        <UiButton size="compact" variant="ghost" @click="copyPhrase">
          {{ copied ? $t('transfer.copied') : $t('transfer.copy') }}
        </UiButton>
      </div>
      <p class="mt-2 text-xs text-muted">{{ $t('transfer.expires', { date: expiry }) }}</p>
    </div>

    <template v-if="showRetrieve">
      <p class="pt-2 text-xs text-muted">{{ $t('transfer.retrieveHelp') }}</p>
      <div class="flex gap-2">
        <label :for="phraseInputId" class="sr-only">{{ $t('transfer.retrieveLabel') }}</label>
        <input
          :id="phraseInputId"
          v-model="phraseInput"
          class="min-w-0 flex-1 rounded bg-surface2 px-2 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-focus"
          :placeholder="$t('transfer.retrievePlaceholder')"
          @keydown.enter="onRetrieve"
        />
        <UiButton :disabled="busy || !phraseInput.trim()" @click="onRetrieve">{{ $t('transfer.retrieve') }}</UiButton>
      </div>
    </template>

    <p v-if="msg" class="text-xs text-muted">{{ msg }}</p>
  </div>
</template>
