<script setup>
import { globalSettings, models, persistGlobal } from '../store.js'

// Edits the global defaults (absolute values, no inherit). New conversations copy these.
const g = globalSettings // ref auto-unwraps in template
</script>

<template>
  <div class="space-y-4 text-sm">
    <p class="text-muted">Defaults applied to new conversations. Saved in this browser.</p>

    <div>
      <label class="mb-1 block text-muted">Model</label>
      <select v-model="g.model" class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal">
        <option v-for="m in models" :key="m.id" :value="m.id">{{ m.label }}</option>
      </select>
    </div>

    <div>
      <label class="mb-1 block text-muted">Utility model (titles &amp; compression)</label>
      <select v-model="g.utility_model" class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal">
        <option v-for="m in models" :key="m.id" :value="m.id">{{ m.label }}</option>
      </select>
    </div>

    <div>
      <label class="mb-1 block text-muted">Temperature: {{ g.temperature }}</label>
      <input
        v-model.number="g.temperature" type="range" min="0" max="1" step="0.1"
        class="w-full" @change="persistGlobal"
      />
    </div>

    <div>
      <label class="mb-1 block text-muted">Messages to send</label>
      <input
        v-model.number="g.num_messages_to_send" type="number" min="1"
        class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal"
      />
    </div>

    <div>
      <label class="mb-1 block text-muted">Max tokens</label>
      <input
        v-model.number="g.max_tokens" type="number" min="1"
        class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal"
      />
    </div>

    <label class="flex items-center gap-2">
      <input v-model="g.send_system_prompt" type="checkbox" @change="persistGlobal" />
      Send system prompt
    </label>

    <label class="flex items-center gap-2">
      <input v-model="g.use_memory" type="checkbox" @change="persistGlobal" />
      Compress history into memory
    </label>

    <div>
      <label class="mb-1 block text-muted">Compression threshold (chars)</label>
      <input v-model.number="g.compression_threshold" type="number" min="500" step="500" class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal" />
    </div>
  </div>
</template>
