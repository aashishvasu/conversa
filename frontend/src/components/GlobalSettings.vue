<script setup>
import { computed, ref } from 'vue'
import { EFFORT_LEVELS } from '../state/settings.js'
import { downloadExport, globalSettings, importData, modelSupportsCache, persistGlobal, restoreData, snapshotInfo } from '../state/store.js'
import { enterToSend, fontScale, locale, restorePrefs } from '../utils/prefs.js'
import { locales, setLocale, tr } from '../i18n.js'
import { restoreTheme } from '../utils/theme.js'
import { confirmDelete } from '../utils/confirm.js'
import ModelSelect from './ModelSelect.vue'

// Edits the global defaults inherited by conversations without an override.
const g = globalSettings // ref auto-unwraps in template
const cacheSupported = computed(() => modelSupportsCache(g.value.model))

// Model selects emit their value; assign and persist it in one handler.
const setGlobal = (k, v) => {
  g.value[k] = v
  persistGlobal()
}
// fontScale / enterToSend are frontend-only prefs; their own watchers persist on change.

const importMsg = ref('')

async function onImportFile(e) {
  const file = e.target.files[0]
  e.target.value = '' // so picking the same file again re-fires @change
  if (!file) return
  try {
    const n = await importData(JSON.parse(await file.text()))
    importMsg.value = n ? tr('import.imported', n, { count: n }) : tr('import.nothing')
  } catch (err) {
    importMsg.value = tr('import.importFailed', { error: err.message })
  }
}

async function onRestoreFile(e) {
  const file = e.target.files[0]
  e.target.value = ''
  if (!file) return
  try {
    const data = JSON.parse(await file.text())
    const info = snapshotInfo(data)
    if (!info) throw new Error(tr('import.chooseSnapshot'))
    const date = info.exportedAt ? new Date(info.exportedAt).toLocaleString(locale.value) : tr('import.unknownDate')
    if (!await confirmDelete(tr('confirm.restore', { ...info, date }), tr('common.restore'))) return
    const prefs = await restoreData(data)
    restorePrefs(prefs)
    restoreTheme(prefs.theme)
    importMsg.value = tr('import.snapshotRestored')
  } catch (err) {
    importMsg.value = tr('import.restoreFailed', { error: err.message })
  }
}
</script>

<template>
  <div class="space-y-4 text-sm">
    <div>
      <label class="mb-1 block text-muted">{{ $t('common.language') }}</label>
      <select :value="locale" class="w-full rounded bg-surface2 px-2 py-1" @change="setLocale($event.target.value)">
        <option v-for="(label, id) in locales" :key="id" :value="id">{{ label }}</option>
      </select>
    </div>

    <p class="text-muted">{{ $t('settings.intro') }}</p>

    <div>
      <label class="mb-1 block text-muted">{{ $t('common.model') }}</label>
      <ModelSelect :model-value="g.model" class="w-full rounded bg-surface2 px-2 py-1" @update:model-value="setGlobal('model', $event)" />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.utilityModel') }}</label>
      <ModelSelect :model-value="g.utility_model" class="w-full rounded bg-surface2 px-2 py-1" @update:model-value="setGlobal('utility_model', $event)" />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.temperature', { value: g.temperature }) }}</label>
      <input
        v-model.number="g.temperature" type="range" min="0" max="1" step="0.1"
        class="w-full" @change="persistGlobal"
      />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.messagesToSend') }}</label>
      <input
        v-model.number="g.num_messages_to_send" type="number" min="1"
        class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal"
      />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.maxTokens') }}</label>
      <input
        v-model.number="g.max_tokens" type="number" min="1"
        class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal"
      />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.thinkingEffort') }}</label>
      <select v-model="g.effort" class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal">
        <option v-for="level in EFFORT_LEVELS" :key="level" :value="level">{{ $t(`effort.${level || 'off'}`) }}</option>
      </select>
    </div>

    <label class="flex items-center gap-2">
      <input v-model="g.send_system_prompt" type="checkbox" @change="persistGlobal" />
      {{ $t('settings.sendSystem') }}
    </label>

    <label class="flex items-center gap-2">
      <input v-model="g.use_memory" type="checkbox" @change="persistGlobal" />
      {{ $t('settings.compressHistory') }}
    </label>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.messagesToSummarise') }}</label>
      <input v-model.number="g.summarize_n" type="number" min="1" step="1" class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal" />
    </div>

    <label class="flex items-center gap-2">
      <input v-model="g.use_recall" type="checkbox" @change="persistGlobal" />
      {{ $t('settings.recall') }}
    </label>

    <label class="flex items-center gap-2" :class="!cacheSupported && 'opacity-50'" :title="cacheSupported ? '' : $t('settings.cacheUnsupported', { model: g.model })">
      <input v-model="g.use_cache" type="checkbox" :disabled="!cacheSupported" @change="persistGlobal" />
      {{ $t('settings.cache') }}
    </label>

    <hr class="border-edge" />
    <p class="text-muted">{{ $t('settings.appearance') }}</p>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.fontSize', { size: Math.round(fontScale * 100) }) }}</label>
      <input v-model.number="fontScale" type="range" min="0.8" max="1.4" step="0.05" class="w-full" />
    </div>

    <label class="flex items-center gap-2">
      <input v-model="enterToSend" type="checkbox" />
      {{ $t('settings.enterSends') }}
    </label>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.backup') }}</label>
      <div class="flex gap-2">
        <button class="flex-1 rounded bg-surface2 py-2 hover:opacity-80" @click="downloadExport()">{{ $t('common.export') }}</button>
        <!-- native file input, hidden inside the label so the button triggers the picker -->
        <label class="flex-1 cursor-pointer rounded bg-surface2 py-2 text-center hover:opacity-80">
          {{ $t('common.import') }}
          <input type="file" accept=".json,application/json" class="hidden" @change="onImportFile" />
        </label>
        <label class="flex-1 cursor-pointer rounded bg-surface2 py-2 text-center hover:opacity-80">
          {{ $t('common.restore') }}
          <input type="file" accept=".json,application/json" class="hidden" @change="onRestoreFile" />
        </label>
      </div>
      <p v-if="importMsg" class="mt-1 text-xs text-muted">{{ importMsg }}</p>
    </div>
  </div>
</template>
