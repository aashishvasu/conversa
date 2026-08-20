<script setup>
import { ref } from 'vue'
import { downloadExport, EFFORT_LEVELS, globalSettings, importData, persistGlobal } from '../store.js'
import { enterToSend, fontScale } from '../prefs.js'
import ModelSelect from './ModelSelect.vue'

// Edits the global defaults (absolute values, no inherit).
// New conversations copy these.
const g = globalSettings // ref auto-unwraps in template

// The model selects emit a value instead of firing a native change event, so assign and persist in one step rather than pairing v-model with a separate @change.
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
      <ModelSelect :model-value="g.model" class="w-full rounded bg-surface2 px-2 py-1" @update:model-value="setGlobal('model', $event)" />
    </div>

    <div>
      <label class="mb-1 block text-muted">Utility model (titles &amp; compression)</label>
      <ModelSelect :model-value="g.utility_model" class="w-full rounded bg-surface2 px-2 py-1" @update:model-value="setGlobal('utility_model', $event)" />
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
      <label class="mb-1 block text-muted">Messages to summarize (above send window)</label>
      <input v-model.number="g.summarize_n" type="number" min="1" step="1" class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal" />
    </div>

    <label class="flex items-center gap-2">
      <input v-model="g.use_recall" type="checkbox" @change="persistGlobal" />
      Recall relevant old messages
    </label>

    <label class="flex items-center gap-2">
      <input v-model="g.use_cache" type="checkbox" @change="persistGlobal" />
      Cache the workspace prompt &amp; docs
    </label>

    <hr class="border-edge" />
    <p class="text-muted">Research runs. A run can override any of these for itself.</p>

    <div>
      <label class="mb-1 block text-muted">Search model</label>
      <ModelSelect :model-value="g.research_search_model" class="w-full rounded bg-surface2 px-2 py-1" @update:model-value="setGlobal('research_search_model', $event)" />
    </div>

    <div>
      <label class="mb-1 block text-muted">Note-taking model</label>
      <ModelSelect :model-value="g.research_note_model" class="w-full rounded bg-surface2 px-2 py-1" @update:model-value="setGlobal('research_note_model', $event)" />
      <p class="mt-1 text-xs text-muted">Around 78% of a run's input tokens go through this one, so a cheap model belongs here.</p>
    </div>

    <div>
      <label class="mb-1 block text-muted">Plan &amp; report model</label>
      <ModelSelect :model-value="g.research_report_model" class="w-full rounded bg-surface2 px-2 py-1" @update:model-value="setGlobal('research_report_model', $event)" />
      <p class="mt-1 text-xs text-muted">Plans the subquestions and writes the report. Bad subquestions cannot be recovered later, so this is the tier worth paying for.</p>
    </div>

    <div>
      <label class="mb-1 block text-muted">Sources per subquestion</label>
      <input v-model.number="g.research_depth" type="number" min="1" max="12" class="w-full rounded bg-surface2 px-2 py-1" @change="persistGlobal" />
    </div>

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
