<script setup>
import { Boxes, CopyPlus, Download, LogOut, Moon, Plus, SlidersHorizontal, Sun, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import { logout } from '../api.js'
import { confirmDelete } from '../utils/confirm.js'
import { formatShort } from '../utils/format.js'
import {
  activePane,
  conversations,
  createConversation,
  createFromTemplate,
  createWorkspace,
  currentId,
  deleteConversation,
  deleteWorkspace,
  downloadExport,
  persistNow,
  selectConversation,
  sidebarOpen,
  templates,
  workspaceOf,
  workspaces,
} from '../store.js'
import { isDark, toggleTheme } from '../utils/theme.js'
import GlobalSettings from '../components/GlobalSettings.vue'
import Modal from '../components/Modal.vue'
import RowActionsMenu from '../components/RowActionsMenu.vue'
import PaneTabs from '../components/shell/PaneTabs.vue'
import WorkspacePanel from '../components/WorkspacePanel.vue'

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

const version = __APP_VERSION__ // injected by Vite at build time (package.json version)

// Chat lists convos outside any workspace; each workspace lists its members on the Workspaces tab.
// A workspaceId pointing at a deleted or unimported workspace resolves to null, so that convo lands back under Chat.
const unassigned = computed(() => conversations.value.filter((c) => !workspaceOf(c)))
const membersOf = (w) => conversations.value.filter((c) => c.workspaceId === w.id)

function pick(id) {
  selectConversation(id)
  sidebarOpen.value = false
}
// Selecting a member convo keeps the Workspaces tab active; the main pane shows the conversation either way.
function pickMember(id) {
  currentId.value = id
  sidebarOpen.value = false
}
function newConversation() {
  createConversation()
  sidebarOpen.value = false
}
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
    <PaneTabs class="m-3" />
    <div class="mx-3 border-t border-edge"></div>

    <!-- Chat tab: templates, then conversations -->
    <div v-if="activePane === 'chat'" class="flex-1 overflow-y-auto p-2">
      <!-- Templates: click to edit in the chat window; copy to start a conversation; delete -->
      <template v-if="templates.length">
        <p class="px-1 pb-1 text-xs uppercase text-muted">Templates</p>
        <div
          v-for="t in templates"
          :key="t.id"
          class="group relative rounded hover:bg-surface2"
          :class="t.id === currentId && 'bg-surface2'"
        >
          <button class="w-full truncate px-2 py-1.5 pr-8 text-left text-sm" @click="pick(t.id)">{{ t.title }}</button>
          <div class="absolute right-1 top-1.5">
            <RowActionsMenu :actions="[
              { label: 'New conversation from template', icon: CopyPlus, onSelect: () => createFromTemplate(t) },
              { label: 'Delete template', icon: X, danger: true, onSelect: () => remove(t.id, 'Delete this template?') },
            ]" />
          </div>
        </div>
      </template>

      <p class="flex items-center justify-between px-1 pb-1 text-xs uppercase text-muted" :class="templates.length && 'pt-2'">
        Conversations
        <button class="rounded p-0.5 hover:bg-surface2 hover:text-base" title="New conversation" @click="newConversation"><Plus :size="14" /></button>
      </p>
      <div
        v-for="c in unassigned"
        :key="c.id"
        class="group relative rounded hover:bg-surface2"
        :class="c.id === currentId && 'bg-surface2'"
      >
        <button class="w-full px-2 py-2 text-left" @click="pick(c.id)">
          <div class="truncate pr-8 text-sm">{{ c.title }}</div>
          <div class="mt-0.5 flex justify-between text-[10px] text-muted">
            <span>{{ c.messages.length }} msgs</span>
            <span>{{ formatShort(lastTs(c)) }}</span>
          </div>
        </button>
        <div class="absolute right-1 top-1.5">
          <RowActionsMenu :actions="[
            { label: 'Export conversation', icon: Download, onSelect: () => downloadExport(c.id) },
            { label: 'Delete', icon: X, danger: true, onSelect: () => remove(c.id, 'Delete this conversation? This cannot be undone.') },
          ]" />
        </div>
      </div>
    </div>

    <!-- Workspaces tab: each row is the management surface, click to edit (name, shared prompt, docs, cards).
         Convos join a workspace via their settings panel. -->
    <div v-else-if="activePane === 'workspaces'" class="flex-1 overflow-y-auto p-2">
      <p class="flex items-center justify-between px-1 pb-1 text-xs uppercase text-muted">
        Workspaces
        <button class="rounded p-0.5 hover:bg-surface2 hover:text-base" title="New workspace" @click="addWorkspace"><Plus :size="14" /></button>
      </p>
      <template v-for="w in workspaces" :key="w.id">
        <div class="group relative rounded hover:bg-surface2">
          <button class="flex w-full items-center gap-1.5 truncate px-2 py-1.5 pr-8 text-left text-sm font-medium" title="Edit workspace" @click="editingWs = w">
            <Boxes :size="14" class="shrink-0 text-muted" />{{ w.name }}
          </button>
          <div class="absolute right-1 top-1.5">
            <RowActionsMenu :actions="[{ label: 'Delete workspace', icon: X, danger: true, onSelect: () => removeWorkspace(w) }]" />
          </div>
        </div>
        <div
          v-for="c in membersOf(w)"
          :key="c.id"
          class="group relative ml-2 rounded hover:bg-surface2"
          :class="c.id === currentId && 'bg-surface2'"
        >
          <button class="w-full px-2 py-2 text-left" @click="pickMember(c.id)">
            <div class="truncate pr-8 text-sm">{{ c.title }}</div>
            <div class="mt-0.5 flex justify-between text-[10px] text-muted">
              <span>{{ c.messages.length }} msgs</span>
              <span>{{ formatShort(lastTs(c)) }}</span>
            </div>
          </button>
          <div class="absolute right-1 top-1.5">
            <RowActionsMenu :actions="[
              { label: 'Export conversation', icon: Download, onSelect: () => downloadExport(c.id) },
              { label: 'Delete', icon: X, danger: true, onSelect: () => remove(c.id, 'Delete this conversation? This cannot be undone.') },
            ]" />
          </div>
        </div>
      </template>
      <p v-if="!workspaces.length" class="px-1 text-xs italic text-muted">No workspaces yet.</p>
    </div>

    <div v-else class="flex-1"></div>

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
