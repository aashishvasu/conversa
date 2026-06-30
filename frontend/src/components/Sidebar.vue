<script setup>
import { CopyPlus, LogOut, Moon, Plus, SlidersHorizontal, Sun, X } from 'lucide-vue-next'
import { ref } from 'vue'
import { logout } from '../api.js'
import { confirmDelete } from '../confirm.js'
import { formatShort } from '../format.js'
import {
  conversations,
  createConversation,
  createFromTemplate,
  currentId,
  deleteConversation,
  selectConversation,
  sidebarOpen,
  templates,
} from '../store.js'
import { isDark, toggleTheme } from '../theme.js'
import GlobalSettings from './GlobalSettings.vue'
import Modal from './Modal.vue'

const showGlobal = ref(false)

function pick(id) {
  selectConversation(id)
  sidebarOpen.value = false
}
async function removeConversation(id) {
  if (await confirmDelete('Delete this conversation? This cannot be undone.')) deleteConversation(id)
}
async function removeTemplate(id) {
  if (await confirmDelete('Delete this template?')) deleteConversation(id)
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
    <div class="p-3">
      <button class="flex w-full items-center justify-center gap-1 rounded bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-500" @click="createConversation()">
        <Plus :size="16" /> New
      </button>
    </div>

    <!-- Templates: click to edit in the chat window; copy to start a conversation; delete -->
    <div v-if="templates.length" class="border-b border-edge p-2">
      <p class="px-1 pb-1 text-xs uppercase text-muted">Templates</p>
      <div
        v-for="t in templates"
        :key="t.id"
        class="group relative rounded hover:bg-surface2"
        :class="t.id === currentId && 'bg-surface2'"
      >
        <button class="w-full truncate px-2 py-1.5 pr-14 text-left text-sm" @click="pick(t.id)">{{ t.title }}</button>
        <div class="absolute right-1 top-1.5 hidden gap-0.5 group-hover:flex">
          <button class="rounded p-1 text-muted hover:text-base" title="New conversation from template" @click="createFromTemplate(t)"><CopyPlus :size="14" /></button>
          <button class="rounded p-1 text-muted hover:text-red-500" title="Delete template" @click="removeTemplate(t.id)"><X :size="14" /></button>
        </div>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto p-2">
      <div
        v-for="c in conversations"
        :key="c.id"
        class="group relative rounded hover:bg-surface2"
        :class="c.id === currentId && 'bg-surface2'"
      >
        <button class="w-full px-2 py-2 text-left" @click="pick(c.id)">
          <div class="truncate pr-5 text-sm">{{ c.title }}</div>
          <div class="mt-0.5 flex justify-between text-[10px] text-muted">
            <span>{{ c.messages.length }} msgs</span>
            <span>{{ formatShort(lastTs(c)) }}</span>
          </div>
        </button>
        <button
          class="absolute right-1 top-1.5 rounded p-1 text-muted opacity-0 hover:text-red-500 group-hover:opacity-100"
          title="Delete"
          @click="removeConversation(c.id)"
        >
          <X :size="14" />
        </button>
      </div>
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

    <Modal v-if="showGlobal" title="Global settings" @close="showGlobal = false">
      <GlobalSettings />
    </Modal>
  </aside>
</template>
