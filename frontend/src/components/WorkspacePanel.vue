<script setup>
import { computed } from 'vue'
import { createDoc, docsOf, removeDocRef } from '../state/store.js'
import { confirmDelete } from '../utils/confirm.js'
import CardsPanel from './CardsPanel.vue'
import DocRow from './DocRow.vue'

const props = defineProps({ workspace: Object })

const docs = computed(() => docsOf(props.workspace))

// Plain-text docs only (.txt/.md), sent whole with every request in the workspace.
// PDF needs pdf.js; add if it's ever wanted.
async function addDocs(e) {
  for (const f of e.target.files) {
    props.workspace.docIds.push(createDoc({ name: f.name, text: await f.text(), source: { kind: 'upload' } }).id)
  }
  e.target.value = '' // re-selecting the same file should fire change again
}

async function removeDoc(id) {
  if (await confirmDelete('Remove this document from the workspace?', 'Remove')) {
    removeDocRef(props.workspace, id)
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
      <DocRow v-for="d in docs" :key="d.id" :doc="d" :owner="workspace" @remove="removeDoc(d.id)" />
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
