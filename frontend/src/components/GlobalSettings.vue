<script setup>
import { ref } from 'vue'
import { downloadExport, EFFORT_LEVELS, globalSettings, importData, models, persistGlobal } from '../store.js'
import { enterToSend, fontScale } from '../prefs.js'

// Edits the global defaults (absolute values, no inherit). New conversations copy these.
const g = globalSettings // ref auto-unwraps in template
// fontScale / enterToSend are frontend-only prefs; their own watchers persist on change.

const importMsg = ref('')

async function onImportFile(e) {
  const file = e.target.files[0]
  e.target.value = '' // so picking the same file again re-fires @change
  if (!file) return
  try {
    const n = importData(JSON.parse(await file.text()))
    importMsg.value = n ? `Imported ${n} conversation${n === 1 ? '' : 's'}` : 'Nothing new to import'
  } catch (err) {
    importMsg.value = `Import failed: ${err.message}`
  }
}
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

    <div>
      <label class="mb-1 block text-muted">Thinking effort</label>
      <select v-model="g.effort" class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal">
        <option v-for="l in EFFORT_LEVELS" :key="l.value" :value="l.value">{{ l.label }}</option>
      </select>
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

    <label class="flex items-center gap-2">
      <input v-model="g.use_recall" type="checkbox" @change="persistGlobal" />
      Recall relevant old messages
    </label>

    <hr class="border-edge" />
    <p class="text-muted">Appearance &amp; input. Applies to this browser only.</p>

    <div>
      <label class="mb-1 block text-muted">Font size: {{ Math.round(fontScale * 100) }}%</label>
      <input v-model.number="fontScale" type="range" min="0.8" max="1.4" step="0.05" class="w-full" />
    </div>

    <label class="flex items-center gap-2">
      <input v-model="enterToSend" type="checkbox" />
      Enter sends message (off: Shift+Enter sends, Enter makes a newline)
    </label>

    <div>
      <label class="mb-1 block text-muted">Backup (conversations, templates &amp; cards)</label>
      <div class="flex gap-2">
        <button class="flex-1 rounded bg-surface2 py-2 hover:opacity-80" @click="downloadExport()">Export</button>
        <!-- native file input, hidden inside the label so the button triggers the picker -->
        <label class="flex-1 cursor-pointer rounded bg-surface2 py-2 text-center hover:opacity-80">
          Import
          <input type="file" accept=".json,application/json" class="hidden" @change="onImportFile" />
        </label>
      </div>
      <p v-if="importMsg" class="mt-1 text-xs text-muted">{{ importMsg }}</p>
    </div>
  </div>
</template>
