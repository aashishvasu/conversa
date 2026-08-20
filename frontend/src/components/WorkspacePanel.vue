<script setup>
import { Download, X } from '@lucide/vue'
import { confirmDelete } from '../confirm.js'
import { renderMarkdown } from '../md.js'
import { downloadText } from '../store.js'
import CardsPanel from './CardsPanel.vue'

const props = defineProps({ workspace: Object })

// Plain-text docs only (.txt/.md), stored inline in IndexedDB and sent whole with every request in the workspace.
// PDF needs pdf.js; add if it's ever wanted.
async function addDocs(e) {
  for (const f of e.target.files) {
    props.workspace.docs.push({ id: crypto.randomUUID(), name: f.name, text: await f.text() })
  }
  e.target.value = '' // re-selecting the same file should fire change again
}

async function removeDoc(id) {
  if (await confirmDelete('Remove this document from the workspace?', 'Remove')) {
    props.workspace.docs = props.workspace.docs.filter((d) => d.id !== id)
  }
}
</script>

<template>
  <div class="space-y-4 text-sm">
    <div>
      <label class="mb-1 block text-muted">Name</label>
      <input v-model="workspace.name" class="w-full rounded bg-surface2 px-2 py-1" />
    </div>

    <div>
      <label class="mb-1 block text-muted">Shared system prompt (leads every conversation's system prompt)</label>
      <textarea v-model="workspace.systemPrompt" rows="4" placeholder="(empty: conversations use only their own system prompt)" class="w-full rounded bg-surface2 px-2 py-1"></textarea>
    </div>

    <div>
      <label class="mb-1 block text-muted">Documents (plain text / markdown, sent whole with every request)</label>
      <!-- A research report arrives here as a doc, so a doc has to be readable and savable, not just deletable. -->
      <details v-for="d in workspace.docs" :key="d.id" class="rounded border border-edge">
        <summary class="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 [&::-webkit-details-marker]:hidden">
          <span class="min-w-0 flex-1 truncate">{{ d.name }}</span>
          <span class="shrink-0 text-xs text-muted">{{ (d.text.length / 1000).toFixed(1) }}k chars</span>
          <button class="shrink-0 text-muted hover:text-base" title="Download" @click.stop.prevent="downloadText(d.name, d.text)"><Download :size="14" /></button>
          <button class="shrink-0 text-muted hover:text-red-500" title="Remove document" @click.stop.prevent="removeDoc(d.id)"><X :size="14" /></button>
        </summary>
        <div class="md max-h-96 overflow-y-auto border-t border-edge p-2 [overflow-wrap:anywhere]" v-html="renderMarkdown(d.text)"></div>
      </details>
      <label class="mt-1 block w-full cursor-pointer rounded bg-surface2 py-2 text-center hover:opacity-80">
        + Add documents
        <input type="file" multiple accept=".txt,.md,text/*" class="hidden" @change="addDocs" />
      </label>
    </div>

    <hr class="border-edge" />

    <p class="text-xs uppercase text-muted">Shared cards</p>
    <CardsPanel :convo="workspace" />
  </div>
</template>
