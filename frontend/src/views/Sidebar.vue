<script setup>
import { Boxes, CopyPlus, Download, LogOut, MessageSquarePlus, Moon, Plus, SlidersHorizontal, Sun, Telescope, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import { logout } from '../api.js'
import { confirmDelete } from '../confirm.js'
import { formatShort } from '../format.js'
import {
  conversations,
  createConversation,
  createFromTemplate,
  createRun,
  createWorkspace,
  currentId,
  currentRunId,
  deleteConversation,
  deleteRun,
  deleteWorkspace,
  downloadExport,
  persistNow,
  runs,
  selectConversation,
  selectRun,
  sidebarOpen,
  templates,
  workspaceOf,
  workspaces,
} from '../store.js'
import { isDark, toggleTheme } from '../theme.js'
import GlobalSettings from './GlobalSettings.vue'
import Modal from './Modal.vue'
import WorkspacePanel from './WorkspacePanel.vue'

const showGlobal = ref(false)
const editingWs = ref(null) // workspace being edited in the modal, or null

function addWorkspace() {
  editingWs.value = createWorkspace()
}
async function removeWorkspace(w) {
  if (await confirmDelete(`Delete workspace "${w.name}"? Its conversations are kept and just leave the workspace.`)) {
    deleteWorkspace(w.id)
  }
}

// Conversation list, flattened to workspace rows + convo rows.
// The workspace row is the single place its name appears: it heads the group, opens the editor on click, and carries the delete button.
// Every workspace shows, member convos or none.
// A workspaceId pointing at a deleted or unimported workspace lands under "Conversations" (workspaceOf resolves it to null).
const rows = computed(() => {
  const out = []
  for (const w of workspaces.value) {
    out.push({ key: `h:${w.id}`, ws: w })
    for (const c of conversations.value.filter((c) => c.workspaceId === w.id)) {
      out.push({ key: c.id, convo: c, grouped: true })
    }
  }
  const rest = conversations.value.filter((c) => !workspaceOf(c))
  if (rest.length) out.push({ key: 'h:rest', label: 'Conversations' })
  for (const c of rest) out.push({ key: c.id, convo: c })
  return out
})
const version = __APP_VERSION__ // injected by Vite at build time (package.json version)

function pick(id) {
  selectConversation(id)
  sidebarOpen.value = false
}
function pickRun(id) {
  selectRun(id)
  sidebarOpen.value = false
}
function newRun() {
  createRun()
  sidebarOpen.value = false
}
async function removeRun(r) {
  const warning = r.status === 'running' ? ' It is still running, and stopping it here will lose the result.' : ''
  if (await confirmDelete(`Delete "${r.title}"?${warning}`)) deleteRun(r.id)
}
// A finished run is worth a glance in the list: what it cost, and whether it reached a workspace.
const runSummary = (r) => [
  r.status === 'draft' ? 'not started' : r.status,
  r.spend?.usd ? `$${r.spend.usd.toFixed(2)}` : null,
].filter(Boolean).join(' · ')
async function remove(id, message) {
  if (await confirmDelete(message)) deleteConversation(id)
}
const lastTs = (c) => c.messages.at(-1)?.createdAt
</script>

<template>
  <!-- Backdrop (mobile only, when open) -->
  <div v-if="sidebarOpen" class="fixed inset-0 z-10 bg-black/50 md:hidden" @click="sidebarOpen = false"></div>

  <aside
    class="fixed inset-y-0 left-0 z-20 flex w-64 flex-col border-r border-edge bg-surface text-base transition-transform md:static md:translate-x-0"
    :class="sidebarOpen ? 'translate-x-0' : '-translate-x-full'"
  >
    <!-- A conversation and a research run are the two things you can start, so they sit side by side. -->
    <div class="flex gap-2 p-3">
      <button class="flex flex-1 items-center justify-center gap-1.5 rounded bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-500" title="New conversation" @click="createConversation()">
        <MessageSquarePlus :size="16" /> Chat
      </button>
      <button class="flex flex-1 items-center justify-center gap-1.5 rounded bg-surface2 py-2 text-sm font-medium hover:opacity-80" title="New research run" @click="newRun">
        <Telescope :size="16" /> Research
      </button>
    </div>

    <div v-if="runs.length" class="border-b border-edge p-2">
      <p class="px-1 pb-1 text-xs uppercase text-muted">Research</p>
      <div
        v-for="r in runs"
        :key="r.id"
        class="group relative rounded hover:bg-surface2"
        :class="r.id === currentRunId && 'bg-surface2'"
      >
        <button class="w-full px-2 py-2 text-left" @click="pickRun(r.id)">
          <div class="flex items-center gap-1.5 truncate pr-8 text-sm">
            <Telescope :size="13" class="shrink-0 text-muted" :class="r.status === 'running' && 'text-indigo-500'" />
            <span class="truncate">{{ r.title }}</span>
          </div>
          <div class="mt-0.5 text-[10px] text-muted">{{ runSummary(r) }}</div>
        </button>
        <div class="absolute right-1 top-1.5 hidden opacity-40 pointer-coarse:flex group-hover:flex">
          <button class="rounded p-1 text-muted hover:text-red-500" title="Delete run" @click="removeRun(r)"><X :size="14" /></button>
        </div>
      </div>
    </div>

    <!-- Templates: click to edit in the chat window; copy to start a conversation; delete -->
    <div v-if="templates.length" class="border-b border-edge p-2">
      <p class="px-1 pb-1 text-xs uppercase text-muted">Templates</p>
      <div
        v-for="t in templates"
        :key="t.id"
        class="group relative rounded hover:bg-surface2"
        :class="t.id === currentId && !currentRunId && 'bg-surface2'"
      >
        <button class="w-full truncate px-2 py-1.5 pr-14 text-left text-sm" @click="pick(t.id)">{{ t.title }}</button>
        <div class="absolute right-1 top-1.5 hidden gap-0.5 opacity-40 pointer-coarse:flex group-hover:flex">
          <button class="rounded p-1 text-muted hover:text-base" title="New conversation from template" @click="createFromTemplate(t)"><CopyPlus :size="14" /></button>
          <button class="rounded p-1 text-muted hover:text-red-500" title="Delete template" @click="remove(t.id, 'Delete this template?')"><X :size="14" /></button>
        </div>
      </div>
    </div>

    <!-- Workspace rows head their convo groups and are the management surface:
         click to edit (name, shared prompt, docs, cards), X to delete (clears
         membership only). Convos join a workspace via their settings panel. -->
    <div class="flex-1 overflow-y-auto p-2">
      <p class="flex items-center justify-between px-1 pb-1 text-xs uppercase text-muted">
        Workspaces
        <button class="rounded p-0.5 hover:bg-surface2 hover:text-base" title="New workspace" @click="addWorkspace"><Plus :size="14" /></button>
      </p>
      <template v-for="row in rows" :key="row.key">
        <div v-if="row.ws" class="group relative rounded hover:bg-surface2">
          <button class="flex w-full items-center gap-1.5 truncate px-2 py-1.5 pr-8 text-left text-sm font-medium" title="Edit workspace" @click="editingWs = row.ws">
            <Boxes :size="14" class="shrink-0 text-muted" />{{ row.ws.name }}
          </button>
          <div class="absolute right-1 top-1.5 hidden opacity-40 pointer-coarse:flex group-hover:flex">
            <button class="rounded p-1 text-muted hover:text-red-500" title="Delete workspace" @click="removeWorkspace(row.ws)"><X :size="14" /></button>
          </div>
        </div>
        <p v-else-if="row.label" class="flex items-center px-1 pb-1 pt-2 text-xs uppercase text-muted">{{ row.label }}</p>
        <div
          v-else
          class="group relative rounded hover:bg-surface2"
          :class="[row.convo.id === currentId && 'bg-surface2', row.grouped && 'ml-2']"
        >
          <button class="w-full px-2 py-2 text-left" @click="pick(row.convo.id)">
            <div class="truncate pr-12 text-sm">{{ row.convo.title }}</div>
            <div class="mt-0.5 flex justify-between text-[10px] text-muted">
              <span>{{ row.convo.messages.length }} msgs</span>
              <span>{{ formatShort(lastTs(row.convo)) }}</span>
            </div>
          </button>
          <div class="absolute right-1 top-1.5 hidden gap-0.5 opacity-40 pointer-coarse:flex group-hover:flex">
            <button class="rounded p-1 text-muted hover:text-base" title="Export conversation" @click="downloadExport(row.convo.id)"><Download :size="14" /></button>
            <button class="rounded p-1 text-muted hover:text-red-500" title="Delete" @click="remove(row.convo.id, 'Delete this conversation? This cannot be undone.')"><X :size="14" /></button>
          </div>
        </div>
      </template>
    </div>

    <div class="flex items-center gap-1 border-t border-edge p-2">
      <button class="flex flex-1 items-center gap-2 rounded px-2 py-2 text-left text-sm hover:bg-surface2" @click="showGlobal = true">
        <SlidersHorizontal :size="16" /> Global settings
      </button>
      <button class="rounded p-2 hover:bg-surface2" :title="isDark ? 'Switch to light' : 'Switch to dark'" @click="toggleTheme">
        <Sun v-if="isDark" :size="16" />
        <Moon v-else :size="16" />
      </button>
      <button class="rounded p-2 hover:bg-surface2 hover:text-red-500" title="Log out" @click="logout">
        <LogOut :size="16" />
      </button>
    </div>

    <a
      href="https://github.com/aashishvasu/conversa"
      target="_blank"
      rel="noopener noreferrer"
      class="block border-t border-edge px-3 py-1.5 text-center text-[10px] text-muted hover:text-base"
    >conversa{{ version ? ` ${version}` : '' }}</a>

    <Modal v-if="showGlobal" title="Global settings" @close="showGlobal = false">
      <GlobalSettings />
    </Modal>
    <!-- Flush on close so quitting right after an edit can't outrun the debounce. -->
    <Modal v-if="editingWs" title="Workspace" @close="editingWs = null; persistNow()">
      <WorkspacePanel :workspace="editingWs" />
    </Modal>
  </aside>
</template>
