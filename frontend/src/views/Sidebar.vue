<script setup>
import { Boxes, CopyPlus, LogOut, MessageSquarePlus, Moon, Plus, SlidersHorizontal, Sun, X } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { DrawerContent, DrawerOverlay, DrawerPortal, DrawerRoot, DrawerTitle } from 'reka-ui'
import { logout } from '../api/client.js'
import { confirmDelete } from '../utils/confirm.js'
import { notify } from '../utils/notify.js'
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
  saveAsTemplate,
  selectConversation,
  sidebarOpen,
  templates,
  workspaceOf,
  workspaces,
} from '../state/store.js'
import { isDark, restoreTheme } from '../utils/theme.js'
import { tr } from '../i18n/index.js'
import ConversationRow from '../components/ConversationRow.vue'
import GlobalSettings from '../components/GlobalSettings.vue'
import Modal from '../components/Modal.vue'
import RowActionsMenu from '../components/RowActionsMenu.vue'
import TransferControls from '../components/TransferControls.vue'
import PaneTabs from '../components/shell/PaneTabs.vue'
import WorkspacePanel from '../components/WorkspacePanel.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiIconButton from '../components/ui/UiIconButton.vue'
import UiScrollArea from '../components/ui/UiScrollArea.vue'
import UiSwitch from '../components/ui/UiSwitch.vue'
import UiTooltip from '../components/ui/UiTooltip.vue'

const showGlobal = ref(false)
const editingWs = ref(null) // workspace being edited in the modal, or null
const transferConvo = ref(null) // conversation being transferred, or null
const desktop = ref(false)
const drawerOpen = computed(() => desktop.value || sidebarOpen.value)
let desktopQuery

function syncDesktop(event) {
  desktop.value = event.matches
  if (desktop.value) sidebarOpen.value = false
}
onMounted(() => {
  desktopQuery = window.matchMedia('(min-width: 768px)')
  syncDesktop(desktopQuery)
  desktopQuery.addEventListener('change', syncDesktop)
})
onBeforeUnmount(() => desktopQuery?.removeEventListener('change', syncDesktop))

function setDrawerOpen(open) {
  if (!desktop.value) sidebarOpen.value = open
}

function addWorkspace() {
  editingWs.value = createWorkspace()
  sidebarOpen.value = false
}
function editWorkspace(workspace) {
  editingWs.value = workspace
  sidebarOpen.value = false
}
function openGlobalSettings() {
  showGlobal.value = true
  sidebarOpen.value = false
}
function openTransfer(convo) {
  transferConvo.value = convo
  sidebarOpen.value = false
}
async function removeWorkspace(w) {
  if (await confirmDelete(tr('confirm.deleteWorkspace', { name: w.name }))) {
    deleteWorkspace(w.id)
  }
}

function saveTemplate(convo) {
  saveAsTemplate(convo)
  notify({ key: 'template', severity: 'success', foreground: true, text: tr('settings.templateCreated') })
}

const version = __APP_VERSION__ // injected by Vite at build time (package.json version)

// Chat lists chat-mode convos outside any workspace; Research filters by mode; each workspace lists its members on the Workspaces tab.
// The tabs are views over one conversation list, so a workspace-member research convo shows under both its workspace and Research.
// A workspaceId pointing at a deleted or unimported workspace resolves to null, so that convo lands back under Chat.
const unassigned = computed(() => conversations.value.filter((c) => !workspaceOf(c) && c.mode !== 'research'))
const researchConvos = computed(() => conversations.value.filter((c) => c.mode === 'research'))
const membersOf = (w) => conversations.value.filter((c) => c.workspaceId === w.id)

function pick(id) {
  selectConversation(id)
  sidebarOpen.value = false
}
// Selecting from the Workspaces or Research list keeps that tab active; the main pane shows the conversation either way.
function pickInPlace(id) {
  currentId.value = id
  sidebarOpen.value = false
}
function newConversation() {
  createConversation()
  sidebarOpen.value = false
}
function newResearchConversation() {
  createConversation().mode = 'research'
  sidebarOpen.value = false
}
function newWorkspaceConversation(w) {
  createConversation().workspaceId = w.id
  sidebarOpen.value = false
}
async function remove(id, message) {
  if (await confirmDelete(message)) deleteConversation(id)
}
</script>

<template>
  <DrawerRoot :open="drawerOpen" :modal="!desktop" swipe-direction="left" @update:open="setDrawerOpen">
    <DrawerPortal :disabled="desktop">
      <DrawerOverlay v-if="!desktop" class="fixed inset-0 z-40 bg-black/50" />
      <DrawerContent
        as="aside"
        :role="desktop ? 'complementary' : 'dialog'"
        class="sidebar-drawer fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-edge bg-surface text-base shadow-xl outline-none transition-transform data-[state=closed]:-translate-x-full data-[state=open]:translate-x-0 md:static md:z-auto md:translate-x-0 md:shadow-none"
      >
        <DrawerTitle class="sr-only">{{ $t('sidebar.navigation') }}</DrawerTitle>
    <PaneTabs class="m-3" />
    <div class="mx-3 border-t border-edge"></div>

    <!-- Chat tab: templates, then conversations -->
    <UiScrollArea v-if="activePane === 'chat'" class="flex-1">
      <div class="p-2">
      <!-- Templates: click to edit in the chat window; copy to start a conversation; delete -->
      <template v-if="templates.length">
        <p class="px-1 pb-1 text-xs uppercase text-muted">{{ $t('sidebar.templates') }}</p>
        <div
          v-for="t in templates"
          :key="t.id"
          class="group relative rounded hover:bg-surface2"
          :class="t.id === currentId && 'bg-surface2'"
        >
          <button class="w-full truncate rounded-md px-2 py-1.5 pr-8 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-focus" @click="pick(t.id)">{{ t.title }}</button>
          <div class="absolute right-1 top-1.5">
            <RowActionsMenu :actions="[
              { label: tr('sidebar.newFromTemplate'), icon: CopyPlus, onSelect: () => createFromTemplate(t) },
              { label: tr('sidebar.deleteTemplate'), icon: X, danger: true, onSelect: () => remove(t.id, tr('confirm.deleteTemplate')) },
            ]" />
          </div>
        </div>
      </template>

      <p class="flex items-center justify-between px-1 pb-1 text-xs uppercase text-muted" :class="templates.length && 'pt-2'">
        {{ $t('sidebar.conversations') }}
        <UiIconButton class="!size-7" :label="$t('sidebar.newConversation')" @click="newConversation"><Plus :size="14" /></UiIconButton>
      </p>
      <ConversationRow
        v-for="c in unassigned"
        :key="c.id"
        :convo="c"
        :active="c.id === currentId"
        @select="pick(c.id)"
        @transfer="openTransfer(c)"
        @export="downloadExport(c.id)"
        @save-template="saveTemplate(c)"
        @delete="remove(c.id, tr('confirm.deleteConversation'))"
      />
      </div>
    </UiScrollArea>

    <!-- Research tab: conversations whose composer defaults to research, wherever they live -->
    <UiScrollArea v-else-if="activePane === 'research'" class="flex-1">
      <div class="p-2">
      <p class="flex items-center justify-between px-1 pb-1 text-xs uppercase text-muted">
        {{ $t('sidebar.research') }}
        <UiIconButton class="!size-7" :label="$t('sidebar.newResearch')" @click="newResearchConversation"><Plus :size="14" /></UiIconButton>
      </p>
      <ConversationRow
        v-for="c in researchConvos"
        :key="c.id"
        :convo="c"
        :active="c.id === currentId"
        @select="pickInPlace(c.id)"
        @transfer="openTransfer(c)"
        @export="downloadExport(c.id)"
        @save-template="saveTemplate(c)"
        @delete="remove(c.id, tr('confirm.deleteConversation'))"
      />
      <p v-if="!researchConvos.length" class="px-1 text-xs italic text-muted">{{ $t('sidebar.noResearch') }}</p>
      </div>
    </UiScrollArea>

    <!-- Workspaces tab: each row is the management surface, click to edit (name, shared prompt, docs, cards).
         Convos join a workspace via their settings panel. -->
    <UiScrollArea v-else-if="activePane === 'workspaces'" class="flex-1">
      <div class="p-2">
      <p class="flex items-center justify-between px-1 pb-1 text-xs uppercase text-muted">
        {{ $t('sidebar.workspaces') }}
        <UiIconButton class="!size-7" :label="$t('sidebar.newWorkspace')" @click="addWorkspace"><Plus :size="14" /></UiIconButton>
      </p>
      <template v-for="w in workspaces" :key="w.id">
        <div class="group relative rounded hover:bg-surface2">
          <UiTooltip :content="$t('sidebar.editWorkspace')">
            <button class="flex w-full items-center gap-1.5 truncate rounded-md px-2 py-1.5 pr-8 text-left text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-focus" @click="editWorkspace(w)">
              <Boxes :size="14" class="shrink-0 text-muted" />{{ w.name }}
            </button>
          </UiTooltip>
          <div class="absolute right-1 top-1.5">
            <RowActionsMenu :actions="[
              { label: tr('sidebar.newHere'), icon: MessageSquarePlus, onSelect: () => newWorkspaceConversation(w) },
              { label: tr('sidebar.deleteWorkspace'), icon: X, danger: true, onSelect: () => removeWorkspace(w) },
            ]" />
          </div>
        </div>
        <ConversationRow
          v-for="c in membersOf(w)"
          :key="c.id"
          :convo="c"
          :active="c.id === currentId"
          indent
          @select="pickInPlace(c.id)"
          @transfer="openTransfer(c)"
          @export="downloadExport(c.id)"
          @save-template="saveTemplate(c)"
          @delete="remove(c.id, tr('confirm.deleteConversation'))"
        />
      </template>
      <p v-if="!workspaces.length" class="px-1 text-xs italic text-muted">{{ $t('sidebar.noWorkspaces') }}</p>
      </div>
    </UiScrollArea>

    <div v-else class="flex-1"></div>

    <div class="flex items-center gap-1 border-t border-edge p-2">
      <UiButton class="flex-1 !justify-start" variant="ghost" @click="openGlobalSettings">
        <SlidersHorizontal :size="18" /> {{ $t('common.settings') }}
      </UiButton>
      <div class="flex items-center gap-1.5 px-1 text-muted">
        <Sun :size="14" />
        <UiSwitch
          :model-value="isDark"
          :label="$t('sidebar.dark')"
          compact
          @update:model-value="restoreTheme($event ? 'dark' : 'light')"
        />
        <Moon :size="14" />
      </div>
      <UiIconButton :label="$t('sidebar.logOut')" variant="danger" @click="logout">
        <LogOut :size="16" />
      </UiIconButton>
    </div>

    <a
      href="https://github.com/aashishvasu/conversa"
      target="_blank"
      rel="noopener noreferrer"
      class="block border-t border-edge px-3 py-1.5 text-center text-[10px] text-muted hover:text-base"
    >conversa{{ version ? ` ${version}` : '' }}</a>

      </DrawerContent>
    </DrawerPortal>

    <Modal v-if="showGlobal" :title="$t('sidebar.globalSettings')" @close="showGlobal = false">
      <GlobalSettings />
    </Modal>
    <!-- Flush on close so quitting right after an edit can't outrun the debounce. -->
    <Modal v-if="editingWs" :title="$t('common.workspace')" @close="editingWs = null; persistNow()">
      <WorkspacePanel :workspace="editingWs" />
    </Modal>
    <Modal v-if="transferConvo" :title="$t('sidebar.transferConversation')" @close="transferConvo = null">
      <TransferControls scope="conversation" :convo-id="transferConvo.id" :show-retrieve="false" />
    </Modal>
  </DrawerRoot>
</template>
