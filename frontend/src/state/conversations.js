import { computed, ref } from 'vue'
import { state } from './persistence.js'
import { docsOf, gcDocs, gcImages } from './docs.js'
import { workspaceOf } from './workspaces.js'
import { tr } from '../i18n/index.js'

export const currentId = ref(null)
// The selected sidebar tab: 'chat' | 'workspaces' | 'usage'.
// It scopes the sidebar sublist and picks the main pane (UsagePane for 'usage', ChatPane otherwise), as a Reka Tabs value shared through the TabsRoot App.vue wraps around Sidebar and the panes.
export const activePane = ref('chat')
export const sidebarOpen = ref(false) // mobile drawer toggle; desktop ignores it

export const conversations = computed(() => state.conversations.filter((c) => !c.isTemplate))
export const templates = computed(() => state.conversations.filter((c) => c.isTemplate))
export const currentConversation = computed(() =>
  state.conversations.find((c) => c.id === currentId.value) || null,
)

function blank(overrides = {}) {
  return {
    id: crypto.randomUUID(),
    title: tr('sidebar.newConversation'),
    isTemplate: false,
    scanAssistant: false,
    workspaceId: null,
    docIds: [],
    mode: 'chat',
    settings: {},
    cards: [],
    cardOverrides: {},
    memory: '',
    memoryCount: 0,
    usage: null,
    messages: [{ id: crypto.randomUUID(), role: 'system', content: '', createdAt: Date.now() }],
    createdAt: Date.now(),
    updatedAt: Date.now(),
    ...overrides,
  }
}

// Deep copy with fresh ids throughout (conversation, messages, cards).
export function cloneWithNewIds(convo) {
  const c = JSON.parse(JSON.stringify(convo))
  c.id = crypto.randomUUID()
  c.messages = c.messages.map((m) => ({ ...m, id: crypto.randomUUID() }))
  c.cards = (c.cards || []).map((cd) => ({ ...cd, id: crypto.randomUUID() }))
  return c
}

export function createConversation() {
  const c = blank()
  state.conversations.unshift(c)
  currentId.value = c.id
  return c
}

export function createFromTemplate(template) {
  const c = cloneWithNewIds(template)
  c.isTemplate = false
  c.createdAt = c.updatedAt = Date.now()
  state.conversations.unshift(c)
  currentId.value = c.id
  return c
}

// Copy the current conversation into a new template (does not move/modify the original).
export function saveAsTemplate(convo) {
  const t = cloneWithNewIds(convo)
  t.isTemplate = true
  t.createdAt = t.updatedAt = Date.now()
  state.conversations.unshift(t)
  return t
}

export function deleteConversation(id) {
  const gone = state.conversations.find((c) => c.id === id)
  state.conversations = state.conversations.filter((c) => c.id !== id)
  state.runs = state.runs.filter((r) => r.convoId !== id)
  if (currentId.value === id) currentId.value = state.conversations[0]?.id || null
  gcDocs(gone?.docIds)
  gcImages(gone?.messages.flatMap((m) => m.imageIds || []))
}

export function selectConversation(id) {
  currentId.value = id
  activePane.value = 'chat'
}

// The docs a conversation sends: workspace docs first, then its own attachments, deduped by id.
// The order is load-bearing: docs sit in the cached stable half of the system prompt, so it must not shift between turns.
export function attachedDocs(convo) {
  const seen = new Set()
  return [...docsOf(workspaceOf(convo)), ...docsOf(convo)].filter((d) => !seen.has(d.id) && seen.add(d.id))
}
