<script setup>
import { Download, RotateCcw, X } from '@lucide/vue'
import { ref } from 'vue'
import { utilityCall } from '../jobs/utility.js'
import { effectiveSettings } from '../state/settings.js'
import { downloadText, undoDocRevision, updateDocText } from '../state/store.js'
import { renderMarkdown } from '../utils/md.js'
import { tr } from '../i18n.js'

// One document row: name and size collapsed; markdown preview, download, and the revise action expanded.
// `owner` is the convo or workspace the row renders under; it supplies the utility model and takes the usage charge, the CardsPanel arrangement.
const props = defineProps({ doc: Object, owner: Object })
defineEmits(['remove'])

// Revise is card-builder shaped: one utility-model call, full replacement text out, no stream parsing.
// The old text goes onto doc.versions, so undo is a pop.
const REVISE_SYSTEM = 'You revise documents. Apply the requested change and return the complete revised document and nothing else: no preamble, no commentary, no code fence around the whole document.'

const instruction = ref('')
const busy = ref(false)
const error = ref('')
async function revise() {
  if (!instruction.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const out = await utilityCall(props.owner, {
      model: effectiveSettings(props.owner).utility_model,
      // Output is the whole document; a research report runs to ~16k tokens (the report cap in runs.py).
      max_tokens: 16384,
      temperature: 0.2,
      system: REVISE_SYSTEM,
      messages: [{ role: 'user', content: `Document "${props.doc.name}":\n\n${props.doc.text}\n\nRequested change: ${instruction.value}` }],
    })
    if (!out) throw new Error(tr('doc.modelEmpty'))
    updateDocText(props.doc, out)
    instruction.value = ''
  } catch (e) {
    error.value = String(e?.message || e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <details class="rounded border border-edge">
    <summary class="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 [&::-webkit-details-marker]:hidden">
      <span class="min-w-0 flex-1 truncate">{{ doc.name }}</span>
      <span class="shrink-0 text-xs text-muted">{{ $t('common.charCount', { count: (doc.text.length / 1000).toFixed(1) }) }}</span>
      <button class="shrink-0 text-muted hover:text-base" :title="$t('common.download')" @click.stop.prevent="downloadText(doc.name, doc.text)"><Download :size="14" /></button>
      <button class="shrink-0 text-muted hover:text-red-500" :title="$t('doc.remove')" @click.stop.prevent="$emit('remove')"><X :size="14" /></button>
    </summary>
    <div class="md max-h-96 overflow-y-auto border-t border-edge p-2 [overflow-wrap:anywhere]" v-html="renderMarkdown(doc.text)"></div>
    <div class="space-y-2 border-t border-edge p-2">
      <div class="flex gap-2">
        <input v-model="instruction" :placeholder="$t('doc.revisePlaceholder')" class="min-w-0 flex-1 rounded bg-surface2 px-2 py-1 outline-none" @keydown.enter.prevent="revise" />
        <button class="shrink-0 rounded bg-surface2 px-3 py-1 hover:opacity-80 disabled:opacity-50" :disabled="busy || !instruction.trim()" @click="revise">{{ busy ? $t('doc.revising') : $t('doc.revise') }}</button>
        <button v-if="doc.versions?.length" class="shrink-0 rounded bg-surface2 px-2 py-1 text-muted hover:opacity-80" :title="$t('doc.undo', { count: doc.versions.length })" @click="undoDocRevision(doc)"><RotateCcw :size="14" /></button>
      </div>
      <p v-if="error" class="text-xs text-red-500">{{ error }}</p>
    </div>
  </details>
</template>
