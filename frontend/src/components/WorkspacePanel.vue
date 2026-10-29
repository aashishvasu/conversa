<script setup>
import { X } from '@lucide/vue'
import { computed } from 'vue'
import { createDoc, docsOf, removeDocRef } from '../state/store.js'
import { confirmDelete } from '../utils/confirm.js'
import { tr } from '../i18n/index.js'
import CardsPanel from './CardsPanel.vue'
import DocRow from './DocRow.vue'
import UiButton from './ui/UiButton.vue'
import UiDisclosure from './ui/UiDisclosure.vue'
import UiIconButton from './ui/UiIconButton.vue'

const props = defineProps({ workspace: Object })

const docs = computed(() => docsOf(props.workspace))

// Shared system prompts, sent in list order ahead of each conversation's own.
const prompts = computed(() => props.workspace.messages.filter((m) => m.role === 'system'))

function addPrompt() {
  props.workspace.messages.unshift({ id: crypto.randomUUID(), role: 'system', content: '', createdAt: Date.now() })
}

async function removePrompt(m) {
  if (!(await confirmDelete(tr('confirm.deleteSystem')))) return
  props.workspace.messages = props.workspace.messages.filter((x) => x.id !== m.id)
}

// Plain-text docs only (.txt/.md), sent whole with every chat request in the workspace.
// PDF needs pdf.js; add if it's ever wanted.
async function addDocs(e) {
  for (const f of e.target.files) {
    props.workspace.docIds.push(createDoc({ name: f.name, text: await f.text(), source: { kind: 'upload' } }).id)
  }
  e.target.value = '' // re-selecting the same file should fire change again
}

async function removeDoc(id) {
  if (await confirmDelete(tr('confirm.removeWorkspaceDoc'), tr('common.remove'))) {
    removeDocRef(props.workspace, id)
  }
}
</script>

<template>
  <div class="space-y-4 text-sm">
    <div>
      <label class="mb-1 block text-muted">{{ $t('common.name') }}</label>
      <input v-model="workspace.name" class="w-full rounded bg-surface2 px-2 py-1" />
    </div>

    <div class="space-y-2">
      <label class="mb-1 block text-muted">{{ $t('workspace.sharedPrompt') }}</label>
      <UiDisclosure v-for="m in prompts" :key="m.id" :padded="false">
        <template #title>
          <span class="shrink-0 text-xs uppercase tracking-wide text-muted">{{ m.role }}</span>
          <span class="truncate text-muted">{{ m.content.trim() }}</span>
        </template>
        <template #actions>
          <UiIconButton :label="$t('common.delete')" variant="danger" @click="removePrompt(m)"><X :size="14" /></UiIconButton>
        </template>
        <textarea v-model="m.content" rows="4" :placeholder="$t('workspace.promptPlaceholder')" class="w-full bg-surface2 px-2 py-2 outline-none focus-visible:ring-2 focus-visible:ring-focus"></textarea>
      </UiDisclosure>
      <UiButton class="w-full" @click="addPrompt">{{ $t('workspace.addPrompt') }}</UiButton>
    </div>

    <div>
      <label class="mb-1 block text-muted">{{ $t('workspace.documents') }}</label>
      <DocRow v-for="d in docs" :key="d.id" :doc="d" :owner="workspace" @remove="removeDoc(d.id)" />
      <label class="mt-1 block w-full cursor-pointer rounded bg-surface2 py-2 text-center hover:opacity-80">
        {{ $t('workspace.addDocuments') }}
        <input type="file" multiple accept=".txt,.md,text/*" class="hidden" @change="addDocs" />
      </label>
    </div>

    <hr class="border-edge" />

    <p class="text-xs uppercase text-muted">{{ $t('workspace.sharedCards') }}</p>
    <CardsPanel :convo="workspace" is-workspace />
  </div>
</template>
