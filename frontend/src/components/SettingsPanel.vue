<script setup>
import { ref } from 'vue'
import { effectiveSettings, globalSettings, models, saveAsTemplate } from '../store.js'

const props = defineProps({ convo: Object })

// Override helpers: an empty override inherits the global default.
const eff = (k) => props.convo.settings[k] ?? globalSettings.value[k]
const overridden = (k) => props.convo.settings[k] !== undefined
const setOv = (k, v) => {
  if (v === null || v === '') delete props.convo.settings[k]
  else props.convo.settings[k] = v
}
const reset = (k) => delete props.convo.settings[k]

const templateSaved = ref(false)
function makeTemplate() {
  saveAsTemplate(props.convo)
  templateSaved.value = true
  setTimeout(() => (templateSaved.value = false), 1500)
}

function clearMemory() {
  props.convo.memory = ''
  props.convo.memoryCount = 0
}
</script>

<template>
  <div class="space-y-4 text-sm">
    <div>
      <label class="mb-1 block text-muted">Model</label>
      <select :value="eff('model')" class="w-full rounded bg-surface2 px-2 py-1" @change="setOv('model', $event.target.value)">
        <option v-for="m in models" :key="m.id" :value="m.id">{{ m.label }}</option>
      </select>
    </div>

    <div>
      <label class="mb-1 block text-muted">Utility model (titles &amp; compression)</label>
      <select :value="eff('utility_model')" class="w-full rounded bg-surface2 px-2 py-1" @change="setOv('utility_model', $event.target.value)">
        <option v-for="m in models" :key="m.id" :value="m.id">{{ m.label }}</option>
      </select>
    </div>

    <div>
      <label class="mb-1 block text-muted">
        Temperature: {{ eff('temperature') }}
        <button v-if="overridden('temperature')" class="ml-1 text-indigo-500" @click="reset('temperature')">↺</button>
      </label>
      <input type="range" min="0" max="1" step="0.1" :value="eff('temperature')" class="w-full" @input="setOv('temperature', Number($event.target.value))" />
    </div>

    <div>
      <label class="mb-1 block text-muted">
        Messages to send: {{ eff('num_messages_to_send') }}
        <button v-if="overridden('num_messages_to_send')" class="ml-1 text-indigo-500" @click="reset('num_messages_to_send')">↺</button>
      </label>
      <input type="number" min="1" :value="eff('num_messages_to_send')" class="w-full rounded bg-surface2 px-2 py-1" @input="setOv('num_messages_to_send', Number($event.target.value))" />
    </div>

    <div>
      <label class="mb-1 block text-muted">
        Max tokens: {{ eff('max_tokens') }}
        <button v-if="overridden('max_tokens')" class="ml-1 text-indigo-500" @click="reset('max_tokens')">↺</button>
      </label>
      <input type="number" min="1" :value="eff('max_tokens')" class="w-full rounded bg-surface2 px-2 py-1" @input="setOv('max_tokens', Number($event.target.value))" />
    </div>

    <label class="flex items-center gap-2">
      <input type="checkbox" :checked="eff('send_system_prompt')" @change="setOv('send_system_prompt', $event.target.checked)" />
      Send system prompt
      <button v-if="overridden('send_system_prompt')" class="text-indigo-500" @click="reset('send_system_prompt')">↺</button>
    </label>

    <hr class="border-edge" />

    <label class="flex items-center gap-2">
      <input type="checkbox" :checked="eff('use_memory')" @change="setOv('use_memory', $event.target.checked)" />
      Compress history into memory
      <button v-if="overridden('use_memory')" class="text-indigo-500" @click="reset('use_memory')">↺</button>
    </label>

    <div>
      <label class="mb-1 block text-muted">
        Compression threshold (chars): {{ eff('compression_threshold') }}
        <button v-if="overridden('compression_threshold')" class="ml-1 text-indigo-500" @click="reset('compression_threshold')">↺</button>
      </label>
      <input type="number" min="500" step="500" :value="eff('compression_threshold')" class="w-full rounded bg-surface2 px-2 py-1" @input="setOv('compression_threshold', Number($event.target.value))" />
    </div>

    <div v-if="eff('use_memory')">
      <label class="mb-1 flex items-center justify-between text-muted">
        <span>Memory ({{ convo.memoryCount || 0 }} msgs folded)</span>
        <button class="text-indigo-500" @click="clearMemory">Clear</button>
      </label>
      <textarea v-model="convo.memory" rows="4" placeholder="(empty — builds automatically as the conversation grows)" class="w-full rounded bg-surface2 px-2 py-1 text-xs"></textarea>
    </div>

    <hr class="border-edge" />

    <label class="flex items-center gap-2">
      <input type="checkbox" v-model="convo.scanAssistant" />
      Scan assistant messages for card triggers
    </label>

    <button class="w-full rounded bg-surface2 py-2 hover:opacity-80" @click="makeTemplate">
      {{ templateSaved ? '✓ Template created' : 'Save as template (copy)' }}
    </button>
  </div>
</template>
