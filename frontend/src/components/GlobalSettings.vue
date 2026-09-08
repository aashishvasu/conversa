<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger, TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import { EFFORT_LEVELS } from '../state/settings.js'
import { downloadExport, globalSettings, importData, modelSupportsCache, models, persistGlobal, resetGlobalSettings, restoreData, snapshotInfo } from '../state/store.js'
import { convertImport } from '../state/importers.js'
import { enterToSend, fontScale, locale, restorePrefs, showThinkingAndSearch } from '../utils/prefs.js'
import { needRefresh, applyUpdate } from '../utils/pwa.js'
import { locales, setLocale, tr } from '../i18n.js'
import { restoreTheme } from '../utils/theme.js'
import { confirmDelete } from '../utils/confirm.js'
import ModelSelect from './ModelSelect.vue'
import TransferControls from './TransferControls.vue'
import UiButton from './ui/UiButton.vue'
import UiDisclosure from './ui/UiDisclosure.vue'
import UiNumberField from './ui/UiNumberField.vue'
import UiSelect from './ui/UiSelect.vue'
import UiSlider from './ui/UiSlider.vue'
import UiSwitch from './ui/UiSwitch.vue'

const g = globalSettings
const cacheSupported = computed(() => modelSupportsCache(g.value.model))
const importInput = ref(null)
const restoreInput = ref(null)

const setGlobal = (k, v) => {
  g.value[k] = v
  persistGlobal()
}

const importMsg = ref('')
const resetOpen = ref(false)
const resetTrigger = ref(null)
const resetConfirm = ref(null)

function focusButton(button) {
  const el = button?.$el || button
  el?.focus?.()
}

watch(resetOpen, async (open, wasOpen) => {
  if (open && !wasOpen) {
    await nextTick()
    if (resetOpen.value) focusButton(resetConfirm.value)
  }
  if (!open && wasOpen) {
    await nextTick()
    if (!resetOpen.value) focusButton(resetTrigger.value)
  }
})

function nextChatReport(report) {
  const parts = []
  if (report.conversations) parts.push(`${tr('import.imported', report.conversations, { count: report.conversations })}.`)
  if (report.templates) parts.push(tr('import.templatesImported', report.templates, { count: report.templates }))
  if (report.sessionsSkipped) parts.push(tr('import.emptySessionsSkipped', report.sessionsSkipped, { count: report.sessionsSkipped }))
  if (report.messagesSkipped) parts.push(tr('import.partialMessagesSkipped', report.messagesSkipped, { count: report.messagesSkipped }))
  if (report.toolsDropped) parts.push(tr('import.toolRecordsDropped', report.toolsDropped, { count: report.toolsDropped }))
  return parts.join(' ')
}

function openImportPicker() {
  importInput.value?.click()
}

function openRestorePicker() {
  restoreInput.value?.click()
}

async function onImportFile(e) {
  const file = e.target.files[0]
  e.target.value = ''
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

function closeReset() {
  resetOpen.value = false
}

function resetDefaults() {
  resetGlobalSettings()
  resetOpen.value = false
}
</script>

<template>
  <div class="space-y-4 text-sm">
    <p class="text-muted">{{ $t('settings.intro') }}</p>

    <TabsRoot default-value="chat" class="space-y-3">
      <TabsList class="flex gap-0.5 overflow-x-auto border-b border-edge py-2">
        <TabsTrigger
          v-for="tab in ['chat', 'context', 'research', 'interface', 'data']"
          :key="tab"
          :value="tab"
          class="shrink-0 rounded-md px-3 py-1.5 text-sm text-muted outline-none transition-colors hover:bg-surface2 focus-visible:ring-2 focus-visible:ring-focus data-[state=active]:bg-accent/10 data-[state=active]:text-base"
        >
          {{ $t(`settings.tab${tab.charAt(0).toUpperCase() + tab.slice(1)}`) }}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="chat" class="space-y-3 outline-none">
        <div>
          <label class="mb-1 block text-muted">{{ $t('common.model') }}</label>
          <ModelSelect :model-value="g.model" :label="$t('common.model')" @update:model-value="setGlobal('model', $event)" />
        </div>

        <div>
          <label class="mb-1 block text-muted">{{ $t('settings.utilityModel') }}</label>
          <ModelSelect :model-value="g.utility_model" :label="$t('settings.utilityModel')" @update:model-value="setGlobal('utility_model', $event)" />
          <p class="mt-0.5 text-xs text-muted">{{ $t('settings.utilityModelHelp') }}</p>
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

        <UiDisclosure>
          <template #title><span class="text-muted">{{ $t('settings.advanced') }}</span></template>
          <div class="space-y-3">
            <div>
              <label class="mb-1 block text-muted">{{ $t('settings.temperature', { value: g.temperature }) }}</label>
              <UiSlider v-model="g.temperature" :label="$t('settings.temperature', { value: g.temperature })" :min="0" :max="1" :step="0.1" @value-commit="persistGlobal" />
            </div>
            <div>
              <label class="mb-1 block text-muted">{{ $t('settings.maxTokens') }}</label>
              <UiNumberField :model-value="g.max_tokens" :label="$t('settings.maxTokens')" :min="1" @update:model-value="setGlobal('max_tokens', $event)" />
            </div>
          </div>
        </UiDisclosure>
      </TabsContent>

      <TabsContent value="context" class="space-y-3 outline-none">
        <div>
          <label class="mb-1 block text-muted">{{ $t('settings.messagesToSend') }}</label>
          <UiNumberField :model-value="g.num_messages_to_send" :label="$t('settings.messagesToSend')" :min="1" @update:model-value="setGlobal('num_messages_to_send', $event)" />
        </div>

        <UiSwitch v-model="g.send_system_prompt" :label="$t('settings.sendSystem')" @update:model-value="persistGlobal" />

        <UiSwitch v-model="g.use_memory" :label="$t('settings.compressHistory')" @update:model-value="persistGlobal" />

        <div v-if="g.use_memory">
          <label class="mb-1 block text-muted">{{ $t('settings.messagesToSummarise') }}</label>
          <UiNumberField :model-value="g.summarize_n" :label="$t('settings.messagesToSummarise')" :min="1" @update:model-value="setGlobal('summarize_n', $event)" />
        </div>

        <UiSwitch v-model="g.use_recall" :label="$t('settings.recall')" @update:model-value="persistGlobal" />

        <UiDisclosure>
          <template #title><span class="text-muted">{{ $t('settings.advanced') }}</span></template>
          <UiSwitch
            v-model="g.use_cache"
            :label="$t('settings.cache')"
            :help="cacheSupported ? '' : $t('settings.cacheUnsupported', { model: g.model })"
            :disabled="!cacheSupported"
            @update:model-value="persistGlobal"
          />
        </UiDisclosure>
      </TabsContent>

      <TabsContent value="research" class="space-y-3 outline-none">
        <div v-for="field in [
          { key: 'research_search_model', label: $t('research.searchModel') },
          { key: 'research_note_model', label: $t('research.notesModel') },
          { key: 'research_report_model', label: $t('research.reportModel') },
        ]" :key="field.key">
          <label class="mb-1 block text-muted">{{ field.label }}</label>
          <ModelSelect :model-value="g[field.key]" :label="field.label" @update:model-value="setGlobal(field.key, $event)" />
        </div>

        <div>
          <label class="mb-1 block text-muted">{{ $t('research.sourcesPerQuestion') }}</label>
          <UiNumberField :model-value="g.research_depth" :label="$t('research.sourcesPerQuestion')" :min="1" :max="12" @update:model-value="setGlobal('research_depth', $event)" />
        </div>
      </TabsContent>

      <TabsContent value="interface" class="space-y-3 outline-none">
        <div>
          <label class="mb-1 block text-muted">{{ $t('common.language') }}</label>
          <UiSelect :model-value="locale" :aria-label="$t('common.language')" :options="Object.entries(locales).map(([value, label]) => ({ value, label }))" @update:model-value="setLocale" />
        </div>

        <div>
          <label class="mb-1 block text-muted">{{ $t('settings.fontSize', { size: Math.round(fontScale * 100) }) }}</label>
          <UiSlider v-model="fontScale" :label="$t('settings.fontSize', { size: Math.round(fontScale * 100) })" :min="0.8" :max="1.4" :step="0.05" />
        </div>

        <UiSwitch v-model="enterToSend" :label="$t('settings.enterSends')" :help="$t('settings.enterSendsHelp')" />

        <UiSwitch v-model="showThinkingAndSearch" :label="$t('settings.showThinkingAndSearch')" />

        <label class="mb-1 block text-muted">{{ $t('settings.uiRefreshLabel') }}</label>
        <UiButton variant="primary" class="flex-1" :disabled="!needRefresh" @click="applyUpdate">{{ $t('settings.uiRefresh') }}</UiButton>
      </TabsContent>

      <TabsContent value="data" class="space-y-3 outline-none">
        <div>
          <label class="mb-1 block text-muted">{{ $t('settings.backup') }}</label>
          <div class="flex gap-2">
            <UiButton class="flex-1" @click="downloadExport()">{{ $t('common.export') }}</UiButton>
            <UiButton class="flex-1" @click="openImportPicker">{{ $t('common.import') }}</UiButton>
            <UiButton class="flex-1" @click="openRestorePicker">{{ $t('common.restore') }}</UiButton>
          </div>
          <input ref="importInput" type="file" accept=".json,application/json" class="sr-only" @change="onImportFile" />
          <input ref="restoreInput" type="file" accept=".json,application/json" class="sr-only" @change="onRestoreFile" />
          <p class="mt-1 text-xs text-muted">{{ $t('import.nextChatWarning') }}</p>
          <p v-if="importMsg" class="mt-1 text-xs text-muted">{{ importMsg }}</p>
        </div>

        <div>
          <label class="mb-1 block text-muted">{{ $t('transfer.heading') }}</label>
          <TransferControls scope="snapshot" />
        </div>

        <div>
          <CollapsibleRoot v-model:open="resetOpen" class="space-y-2">
            <CollapsibleTrigger as-child>
              <UiButton ref="resetTrigger">{{ $t('settings.reset') }}</UiButton>
            </CollapsibleTrigger>
            <CollapsibleContent class="space-y-3 rounded-md border border-edge bg-surface p-3">
              <p class="text-xs text-muted">{{ $t('settings.resetHelp') }}</p>
              <div class="flex gap-2">
                <UiButton variant="secondary" @click="closeReset">{{ $t('common.cancel') }}</UiButton>
                <UiButton ref="resetConfirm" variant="danger" @click="resetDefaults">{{ $t('settings.reset') }}</UiButton>
              </div>
            </CollapsibleContent>
          </CollapsibleRoot>
        </div>
      </TabsContent>
    </TabsRoot>
  </div>
</template>
