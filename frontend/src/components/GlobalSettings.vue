<script setup>
import { computed, ref } from 'vue'
import { EFFORT_LEVELS } from '../state/settings.js'
import { downloadExport, globalSettings, importData, modelSupportsCache, models, persistGlobal, restoreData, snapshotInfo } from '../state/store.js'
import { convertImport } from '../state/importers.js'
import { enterToSend, fontScale, locale, restorePrefs, showThinkingAndSearch } from '../utils/prefs.js'
import { locales, setLocale, tr } from '../i18n.js'
import { restoreTheme } from '../utils/theme.js'
import { confirmDelete } from '../utils/confirm.js'
import ModelSelect from './ModelSelect.vue'
import UiButton from './ui/UiButton.vue'
import UiNumberField from './ui/UiNumberField.vue'
import UiSelect from './ui/UiSelect.vue'
import UiSlider from './ui/UiSlider.vue'
import UiSwitch from './ui/UiSwitch.vue'

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

function nextChatReport(report) {
  const parts = []
  if (report.conversations) parts.push(`${tr('import.imported', report.conversations, { count: report.conversations })}.`)
  if (report.templates) parts.push(tr('import.templatesImported', report.templates, { count: report.templates }))
  if (report.sessionsSkipped) parts.push(tr('import.emptySessionsSkipped', report.sessionsSkipped, { count: report.sessionsSkipped }))
  if (report.messagesSkipped) parts.push(tr('import.partialMessagesSkipped', report.messagesSkipped, { count: report.messagesSkipped }))
  if (report.toolsDropped) parts.push(tr('import.toolRecordsDropped', report.toolsDropped, { count: report.toolsDropped }))
  return parts.join(' ')
}

async function onImportFile(e) {
  const file = e.target.files[0]
  e.target.value = '' // so picking the same file again re-fires @change
  if (!file) return
  try {
    const data = JSON.parse(await file.text())
    const converted = convertImport(data, models.value.map((model) => model.id))
    const n = await importData(converted?.data || data)
    importMsg.value = converted ? nextChatReport(converted.report) : n ? tr('import.imported', n, { count: n }) : tr('import.nothing')
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
      <UiSelect :model-value="locale" :aria-label="$t('common.language')" :options="Object.entries(locales).map(([value, label]) => ({ value, label }))" @update:model-value="setLocale" />
    </div>

    <p class="text-muted">{{ $t('settings.intro') }}</p>

    <div>
      <label class="mb-1 block text-muted">{{ $t('common.model') }}</label>
      <ModelSelect :model-value="g.model" :label="$t('common.model')" @update:model-value="setGlobal('model', $event)" />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.utilityModel') }}</label>
      <ModelSelect :model-value="g.utility_model" :label="$t('settings.utilityModel')" @update:model-value="setGlobal('utility_model', $event)" />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.temperature', { value: g.temperature }) }}</label>
      <UiSlider v-model="g.temperature" :label="$t('settings.temperature', { value: g.temperature })" :min="0" :max="1" :step="0.1" @value-commit="persistGlobal" />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.messagesToSend') }}</label>
      <UiNumberField :model-value="g.num_messages_to_send" :label="$t('settings.messagesToSend')" :min="1" @update:model-value="setGlobal('num_messages_to_send', $event)" />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.maxTokens') }}</label>
      <UiNumberField :model-value="g.max_tokens" :label="$t('settings.maxTokens')" :min="1" @update:model-value="setGlobal('max_tokens', $event)" />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.thinkingEffort') }}</label>
      <UiSelect
        :model-value="g.effort"
        :aria-label="$t('settings.thinkingEffort')"
        :options="EFFORT_LEVELS.map(value => ({ value, label: $t(`effort.${value || 'off'}`) }))"
        @update:model-value="setGlobal('effort', $event)"
      />
    </div>

    <UiSwitch v-model="g.send_system_prompt" :label="$t('settings.sendSystem')" @update:model-value="persistGlobal" />

    <UiSwitch v-model="g.use_memory" :label="$t('settings.compressHistory')" @update:model-value="persistGlobal" />

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.messagesToSummarise') }}</label>
      <UiNumberField :model-value="g.summarize_n" :label="$t('settings.messagesToSummarise')" :min="1" @update:model-value="setGlobal('summarize_n', $event)" />
    </div>

    <UiSwitch v-model="g.use_recall" :label="$t('settings.recall')" @update:model-value="persistGlobal" />

    <UiSwitch
      v-model="g.use_cache"
      :label="$t('settings.cache')"
      :help="cacheSupported ? '' : $t('settings.cacheUnsupported', { model: g.model })"
      :disabled="!cacheSupported"
      @update:model-value="persistGlobal"
    />

    <hr class="border-edge" />
    <p class="text-muted">{{ $t('settings.appearance') }}</p>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.fontSize', { size: Math.round(fontScale * 100) }) }}</label>
      <UiSlider v-model="fontScale" :label="$t('settings.fontSize', { size: Math.round(fontScale * 100) })" :min="0.8" :max="1.4" :step="0.05" />
    </div>

    <UiSwitch v-model="enterToSend" :label="$t('settings.enterSends')" />

    <UiSwitch v-model="showThinkingAndSearch" :label="$t('settings.showThinkingAndSearch')" />

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.backup') }}</label>
      <div class="flex gap-2">
        <UiButton class="flex-1" @click="downloadExport()">{{ $t('common.export') }}</UiButton>
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
      <p class="mt-1 text-xs text-muted">{{ $t('import.nextChatWarning') }}</p>
      <p v-if="importMsg" class="mt-1 text-xs text-muted">{{ importMsg }}</p>
    </div>
  </div>
</template>
