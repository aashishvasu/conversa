<script setup>
import { computed } from 'vue'
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import { tr } from '../i18n.js'
import { effectiveSettings, EFFORT_LEVELS } from '../state/settings.js'
import {
  createFromTemplate,
  deleteConversation,
  downloadExport,
  globalSettings,
  modelSupportsCache,
  saveAsTemplate,
  workspaces,
} from '../state/store.js'
import { confirmDelete } from '../utils/confirm.js'
import { notify } from '../utils/notify.js'
import { showThinkingAndSearch } from '../utils/prefs.js'
import ModelSelect from './ModelSelect.vue'
import OverrideReset from './settings/OverrideReset.vue'
import TransferControls from './TransferControls.vue'
import UiButton from './ui/UiButton.vue'
import UiDisclosure from './ui/UiDisclosure.vue'
import UiNumberField from './ui/UiNumberField.vue'
import UiSelect from './ui/UiSelect.vue'
import UiSlider from './ui/UiSlider.vue'
import UiSwitch from './ui/UiSwitch.vue'

const props = defineProps({ convo: Object })
const emit = defineEmits(['close'])

const eff = (k) => props.convo.settings[k] ?? globalSettings.value[k]
const cacheSupported = computed(() => modelSupportsCache(eff('model')))
const showTrace = computed(() => props.convo.showThinkingAndSearch ?? showThinkingAndSearch.value)
const overridden = (k) => props.convo.settings[k] !== undefined
const setOv = (k, v) => {
  if (v === null || v === '') delete props.convo.settings[k]
  else props.convo.settings[k] = v
}
const reset = (k) => delete props.convo.settings[k]
const setShowTrace = (value) => { props.convo.showThinkingAndSearch = value }
const resetShowTrace = () => delete props.convo.showThinkingAndSearch

function saveTemplate() {
  saveAsTemplate(props.convo)
  notify({ key: 'template', severity: 'success', foreground: true, text: tr('settings.templateCreated') })
}

function newFromTemplate() {
  createFromTemplate(props.convo)
  emit('close')
}

async function remove() {
  const message = tr(props.convo.isTemplate ? 'confirm.deleteTemplate' : 'confirm.deleteConversation')
  if (await confirmDelete(message)) {
    deleteConversation(props.convo.id)
    emit('close')
  }
}
</script>

<template>
  <div class="space-y-4 text-sm">
    <div v-if="workspaces.length">
      <label class="mb-1 block text-muted">{{ $t('settings.workspaceHelp') }}</label>
      <UiSelect
        :model-value="convo.workspaceId || ''"
        :aria-label="$t('settings.workspaceHelp')"
        :options="[{ value: '', label: $t('common.none') }, ...workspaces.map(w => ({ value: w.id, label: w.name }))]"
        @update:model-value="convo.workspaceId = $event || null"
      />
    </div>

    <TabsRoot default-value="chat" class="space-y-3">
      <TabsList class="flex gap-0.5 overflow-x-auto border-b border-edge py-2">
        <TabsTrigger
          v-for="tab in ['chat', 'context', 'research', 'data']"
          :key="tab"
          :value="tab"
          class="shrink-0 rounded-md px-3 py-1.5 text-sm text-muted outline-none transition-colors hover:bg-surface2 focus-visible:ring-2 focus-visible:ring-focus data-[state=active]:bg-accent/10 data-[state=active]:text-base"
        >
          {{ $t(`settings.tab${tab.charAt(0).toUpperCase() + tab.slice(1)}`) }}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="chat" class="space-y-3 outline-none">
        <div>
          <div class="mb-1 flex items-center justify-between text-muted">
            <span>{{ $t('common.model') }}</span>
            <OverrideReset :overridden="overridden('model')" @use-global="reset('model')" />
          </div>
          <ModelSelect :model-value="eff('model')" :label="$t('common.model')" @update:model-value="setOv('model', $event)" />
        </div>

        <div>
          <div class="mb-1 flex items-center justify-between text-muted">
            <span>{{ $t('settings.utilityModel') }}</span>
            <OverrideReset :overridden="overridden('utility_model')" @use-global="reset('utility_model')" />
          </div>
          <ModelSelect :model-value="eff('utility_model')" :label="$t('settings.utilityModel')" @update:model-value="setOv('utility_model', $event)" />
        </div>

        <div>
          <div class="mb-1 flex items-center justify-between text-muted">
            <span>{{ $t('settings.thinkingEffort') }}</span>
            <OverrideReset :overridden="overridden('effort')" @use-global="reset('effort')" />
          </div>
          <UiSelect
            :model-value="eff('effort') || ''"
            :aria-label="$t('settings.thinkingEffort')"
            :options="EFFORT_LEVELS.map(value => ({ value, label: $t(`effort.${value || 'off'}`) }))"
            @update:model-value="setOv('effort', $event)"
          />
        </div>

        <UiSwitch :model-value="showTrace" :label="$t('settings.showThinkingAndSearch')" @update:model-value="setShowTrace">
          <template #action>
            <OverrideReset :overridden="convo.showThinkingAndSearch !== undefined" @use-global="resetShowTrace" />
          </template>
        </UiSwitch>

        <UiDisclosure>
          <template #title><span class="text-muted">{{ $t('settings.advanced') }}</span></template>
          <div class="space-y-3">
            <div>
              <div class="mb-1 flex items-center justify-between text-muted">
                <span>{{ $t('settings.temperature', { value: eff('temperature') }) }}</span>
                <OverrideReset :overridden="overridden('temperature')" @use-global="reset('temperature')" />
              </div>
              <UiSlider :model-value="eff('temperature')" :label="$t('settings.temperature', { value: eff('temperature') })" :min="0" :max="1" :step="0.1" @update:model-value="setOv('temperature', $event)" />
            </div>
            <div>
              <div class="mb-1 flex items-center justify-between text-muted">
                <span>{{ $t('settings.maxTokens') }}</span>
                <OverrideReset :overridden="overridden('max_tokens')" @use-global="reset('max_tokens')" />
              </div>
              <UiNumberField :model-value="eff('max_tokens')" :label="$t('settings.maxTokens')" :min="1" @update:model-value="setOv('max_tokens', $event)" />
            </div>
          </div>
        </UiDisclosure>
      </TabsContent>

      <TabsContent value="context" class="space-y-3 outline-none">
        <div>
          <div class="mb-1 flex items-center justify-between text-muted">
            <span>{{ $t('settings.messagesToSend') }}</span>
            <OverrideReset :overridden="overridden('num_messages_to_send')" @use-global="reset('num_messages_to_send')" />
          </div>
          <UiNumberField :model-value="eff('num_messages_to_send')" :label="$t('settings.messagesToSend')" :min="1" @update:model-value="setOv('num_messages_to_send', $event)" />
        </div>

        <UiSwitch :model-value="eff('send_system_prompt')" :label="$t('settings.sendSystem')" @update:model-value="setOv('send_system_prompt', $event)">
          <template #action>
            <OverrideReset :overridden="overridden('send_system_prompt')" @use-global="reset('send_system_prompt')" />
          </template>
        </UiSwitch>

        <UiSwitch :model-value="eff('use_memory')" :label="$t('settings.compressHistory')" @update:model-value="setOv('use_memory', $event)">
          <template #action>
            <OverrideReset :overridden="overridden('use_memory')" @use-global="reset('use_memory')" />
          </template>
        </UiSwitch>

        <div v-if="eff('use_memory')">
          <div class="mb-1 flex items-center justify-between text-muted">
            <span>{{ $t('settings.messagesToSummarise') }}</span>
            <OverrideReset :overridden="overridden('summarize_n')" @use-global="reset('summarize_n')" />
          </div>
          <UiNumberField :model-value="eff('summarize_n')" :label="$t('settings.messagesToSummarise')" :min="1" @update:model-value="setOv('summarize_n', $event)" />
        </div>

        <UiSwitch :model-value="eff('use_recall')" :label="$t('settings.recall')" @update:model-value="setOv('use_recall', $event)">
          <template #action>
            <OverrideReset :overridden="overridden('use_recall')" @use-global="reset('use_recall')" />
          </template>
        </UiSwitch>

        <UiDisclosure>
          <template #title><span class="text-muted">{{ $t('settings.advanced') }}</span></template>
          <UiSwitch
            :model-value="eff('use_cache')"
            :label="$t('settings.cache')"
            :help="cacheSupported ? $t('settings.cacheHelp') : $t('settings.cacheUnsupported', { model: eff('model') })"
            :disabled="!cacheSupported"
            @update:model-value="setOv('use_cache', $event)"
          >
            <template #action>
              <OverrideReset :overridden="overridden('use_cache')" @use-global="reset('use_cache')" />
            </template>
          </UiSwitch>
        </UiDisclosure>
      </TabsContent>

      <TabsContent value="research" class="space-y-3 outline-none">
        <div v-for="field in [
          { key: 'research_search_model', label: $t('research.searchModel') },
          { key: 'research_note_model', label: $t('research.notesModel') },
          { key: 'research_report_model', label: $t('research.reportModel') },
        ]" :key="field.key">
          <div class="mb-1 flex items-center justify-between text-muted">
            <span>{{ field.label }}</span>
            <OverrideReset :overridden="overridden(field.key)" @use-global="reset(field.key)" />
          </div>
          <ModelSelect :model-value="eff(field.key)" :label="field.label" @update:model-value="setOv(field.key, $event)" />
        </div>

        <div>
          <div class="mb-1 flex items-center justify-between text-muted">
            <span>{{ $t('research.sourcesPerQuestion') }}</span>
            <OverrideReset :overridden="overridden('research_depth')" @use-global="reset('research_depth')" />
          </div>
          <UiNumberField :model-value="eff('research_depth')" :label="$t('research.sourcesPerQuestion')" :min="1" :max="12" @update:model-value="setOv('research_depth', $event)" />
        </div>
      </TabsContent>

      <TabsContent value="data" class="space-y-3 outline-none">
        <div class="flex gap-2">
          <UiButton class="flex-1" @click="downloadExport(convo.id)">{{ $t('sidebar.exportConversation') }}</UiButton>
          <UiButton v-if="convo.isTemplate" class="flex-1" @click="newFromTemplate">{{ $t('sidebar.newFromTemplate') }}</UiButton>
          <UiButton v-else class="flex-1" @click="saveTemplate">{{ $t('settings.saveTemplate') }}</UiButton>
        </div>

        <div>
          <label class="mb-1 block text-muted">{{ $t('transfer.heading') }}</label>
          <TransferControls scope="conversation" :convo-id="convo.id" :show-retrieve="false" />
        </div>

        <div class="border-t border-edge pt-3">
          <UiButton variant="danger" @click="remove">
            {{ convo.isTemplate ? $t('sidebar.deleteTemplate') : $t('common.delete') }}
          </UiButton>
        </div>
      </TabsContent>
    </TabsRoot>
  </div>
</template>
