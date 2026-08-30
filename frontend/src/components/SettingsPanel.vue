<script setup>
import { RotateCcw } from '@lucide/vue'
import { computed, ref } from 'vue'
import { effectiveSettings, EFFORT_LEVELS } from '../state/settings.js'
import { globalSettings, modelSupportsCache, saveAsTemplate, workspaces } from '../state/store.js'
import { confirmDelete } from '../utils/confirm.js'
import { tr } from '../i18n.js'
import { showThinkingAndSearch } from '../utils/prefs.js'
import ModelSelect from './ModelSelect.vue'
import UiButton from './ui/UiButton.vue'
import UiIconButton from './ui/UiIconButton.vue'
import UiNumberField from './ui/UiNumberField.vue'
import UiSelect from './ui/UiSelect.vue'
import UiSlider from './ui/UiSlider.vue'
import UiSwitch from './ui/UiSwitch.vue'

const props = defineProps({ convo: Object })

// Override helpers: an empty override inherits the global default.
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

const templateSaved = ref(false)
function makeTemplate() {
  saveAsTemplate(props.convo)
  templateSaved.value = true
  setTimeout(() => (templateSaved.value = false), 1500)
}

async function clearMemory() {
  if (!(await confirmDelete(tr('confirm.clearMemory'), tr('common.clear')))) return
  props.convo.memory = ''
  props.convo.memoryCount = 0
}
</script>

<template>
  <div class="space-y-4 text-sm">
    <!-- Joining or leaving sets only this pointer; the conversation's own cards, messages, and settings stay as they are. -->
    <div v-if="workspaces.length">
      <label class="mb-1 block text-muted">{{ $t('settings.workspaceHelp') }}</label>
      <UiSelect
        :model-value="convo.workspaceId || ''"
        :aria-label="$t('settings.workspaceHelp')"
        :options="[{ value: '', label: $t('common.none') }, ...workspaces.map(w => ({ value: w.id, label: w.name }))]"
        @update:model-value="convo.workspaceId = $event || null"
      />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('common.model') }}</label>
      <ModelSelect :model-value="eff('model')" :label="$t('common.model')" @update:model-value="setOv('model', $event)" />
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('settings.utilityModel') }}</label>
      <ModelSelect :model-value="eff('utility_model')" :label="$t('settings.utilityModel')" @update:model-value="setOv('utility_model', $event)" />
    </div>

    <div>
      <div class="mb-1 flex items-center justify-between text-muted">
        <span>{{ $t('settings.temperature', { value: eff('temperature') }) }}</span>
        <UiIconButton v-if="overridden('temperature')" class="!size-6" :label="$t('settings.inheritGlobal')" @click="reset('temperature')"><RotateCcw :size="12" /></UiIconButton>
      </div>
      <UiSlider :model-value="eff('temperature')" :label="$t('settings.temperature', { value: eff('temperature') })" :min="0" :max="1" :step="0.1" @update:model-value="setOv('temperature', $event)" />
    </div>

    <div>
      <div class="mb-1 flex items-center justify-between text-muted">
        <span>{{ $t('settings.messagesToSendValue', { value: eff('num_messages_to_send') }) }}</span>
        <UiIconButton v-if="overridden('num_messages_to_send')" class="!size-6" :label="$t('settings.inheritGlobal')" @click="reset('num_messages_to_send')"><RotateCcw :size="12" /></UiIconButton>
      </div>
      <UiNumberField :model-value="eff('num_messages_to_send')" :label="$t('settings.messagesToSend')" :min="1" @update:model-value="setOv('num_messages_to_send', $event)" />
    </div>

    <div>
      <div class="mb-1 flex items-center justify-between text-muted">
        <span>{{ $t('settings.maxTokensValue', { value: eff('max_tokens') }) }}</span>
        <UiIconButton v-if="overridden('max_tokens')" class="!size-6" :label="$t('settings.inheritGlobal')" @click="reset('max_tokens')"><RotateCcw :size="12" /></UiIconButton>
      </div>
      <UiNumberField :model-value="eff('max_tokens')" :label="$t('settings.maxTokens')" :min="1" @update:model-value="setOv('max_tokens', $event)" />
    </div>

    <div>
      <div class="mb-1 flex items-center justify-between text-muted">
        <span>{{ $t('settings.thinkingEffort') }}</span>
        <UiIconButton v-if="overridden('effort')" class="!size-6" :label="$t('settings.inheritGlobal')" @click="reset('effort')"><RotateCcw :size="12" /></UiIconButton>
      </div>
      <UiSelect
        :model-value="eff('effort') || ''"
        :aria-label="$t('settings.thinkingEffort')"
        :options="EFFORT_LEVELS.map(value => ({ value, label: $t(`effort.${value || 'off'}`) }))"
        @update:model-value="setOv('effort', $event)"
      />
    </div>

    <UiSwitch :model-value="eff('send_system_prompt')" :label="$t('settings.sendSystem')" @update:model-value="setOv('send_system_prompt', $event)">
      <template v-if="overridden('send_system_prompt')" #action><UiIconButton class="!size-6" :label="$t('settings.inheritGlobal')" @click="reset('send_system_prompt')"><RotateCcw :size="12" /></UiIconButton></template>
    </UiSwitch>

    <hr class="border-edge" />

    <UiSwitch :model-value="eff('use_memory')" :label="$t('settings.compressHistory')" @update:model-value="setOv('use_memory', $event)">
      <template v-if="overridden('use_memory')" #action><UiIconButton class="!size-6" :label="$t('settings.inheritGlobal')" @click="reset('use_memory')"><RotateCcw :size="12" /></UiIconButton></template>
    </UiSwitch>

    <div>
      <div class="mb-1 flex items-center justify-between text-muted">
        <span>{{ $t('settings.messagesToSummariseValue', { value: eff('summarize_n') }) }}</span>
        <UiIconButton v-if="overridden('summarize_n')" class="!size-6" :label="$t('settings.inheritGlobal')" @click="reset('summarize_n')"><RotateCcw :size="12" /></UiIconButton>
      </div>
      <UiNumberField :model-value="eff('summarize_n')" :label="$t('settings.messagesToSummarise')" :min="1" @update:model-value="setOv('summarize_n', $event)" />
    </div>

    <UiSwitch :model-value="eff('use_recall')" :label="$t('settings.recall')" @update:model-value="setOv('use_recall', $event)">
      <template v-if="overridden('use_recall')" #action><UiIconButton class="!size-6" :label="$t('settings.inheritGlobal')" @click="reset('use_recall')"><RotateCcw :size="12" /></UiIconButton></template>
    </UiSwitch>

    <UiSwitch
      :model-value="eff('use_cache')"
      :label="$t('settings.cache')"
      :help="cacheSupported ? $t('settings.cacheHelp') : $t('settings.cacheUnsupported', { model: eff('model') })"
      :disabled="!cacheSupported"
      @update:model-value="setOv('use_cache', $event)"
    >
      <template v-if="overridden('use_cache')" #action><UiIconButton class="!size-6" :label="$t('settings.inheritGlobal')" @click="reset('use_cache')"><RotateCcw :size="12" /></UiIconButton></template>
    </UiSwitch>

    <div v-if="eff('use_memory')">
      <div class="mb-1 flex items-center justify-between text-muted">
        <span>{{ $t('settings.memory') }}</span>
        <UiButton size="compact" variant="ghost" @click="clearMemory">{{ $t('common.clear') }}</UiButton>
      </div>
      <textarea v-model="convo.memory" rows="4" :placeholder="$t('settings.memoryEmpty')" class="w-full rounded bg-surface2 px-2 py-1 text-xs"></textarea>
    </div>

    <hr class="border-edge" />

    <UiSwitch :model-value="showTrace" :label="$t('settings.showThinkingAndSearch')" @update:model-value="setShowTrace">
      <template v-if="convo.showThinkingAndSearch !== undefined" #action><UiIconButton class="!size-6" :label="$t('settings.inheritGlobal')" @click="resetShowTrace"><RotateCcw :size="12" /></UiIconButton></template>
    </UiSwitch>

    <UiSwitch v-model="convo.scanAssistant" :label="$t('settings.scanAssistant')" />

    <UiButton class="w-full" @click="makeTemplate">
      {{ templateSaved ? `✓ ${$t('settings.templateCreated')}` : $t('settings.saveTemplate') }}
    </UiButton>
  </div>
</template>
