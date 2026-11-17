import { computed, ref } from 'vue'
import { state } from './persistence.js'
import { docsOf, gcDocs, gcImages } from './docs.js'
import { workspaceOf } from './workspaces.js'
import { db } from './db.js'
import { tr } from '../i18n/index.js'
export const currentId = ref(null)
// The selected sidebar tab: 'chat' | 'workspaces' | 'usage'.
// It scopes the sidebar sublist and picks the main pane (UsagePane for 'chat', ChatPane otherwise), as a Reka Tabs value shared through the TabsRoot App.vue wraps around Sidebar and the panes.
export const activePane = ref('chat')
export const sidebarOpen = ref(false) // mobile drawer toggle; desktop ignores it
export const conversations = computed(() => state.conversations.filter((c) => !c.isTemplate))
export const templates = computed(() => state.conversations.filter((c) => c.isTemplate))
export const currentConversation = computed(() =>
  state.conversations.find((c) => c.id === currentId.value) || null,
)
function blank(overrides = {}) {
  const systemId = crypto.randomUUID()
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
    // A new conversation is born loaded: its system message has a row as soon as the first flush writes.
    messages: [{ id: systemId, role: 'system', content: '', createdAt: Date.now() }],
    messageIds: [systemId],
    createdAt: Date.now(),
    ...overrides,
  }
}
// Deep copy with fresh ids throughout (conversation, messages, cards); messageIds follows the new message ids.
export function cloneWithNewIds(convo) {
  const c = JSON.parse(JSON.stringify(convo))
  c.id = crypto.randomUUID()
  c.messages = c.messages.map((m) => ({ ...m, id: crypto.randomUUID() }))
  c.messageIds = c.messages.map((m) => m.id)
  // A copy never claims the original's pending turn.
  for (const m of c.messages) delete m.turnId
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
  c.createdAt = Date.now()
  c.usage = null
  state.conversations.unshift(c)
  currentId.value = c.id
  return c
}
// Copy the current conversation into a new template (does not move/modify the original).
export function saveAsTemplate(convo) {
  const t = cloneWithNewIds(convo)
  t.isTemplate = true
  t.createdAt = Date.now()
  state.conversations.unshift(t)
  return t
}
// Gather ids up front: a summary conversation holds no in-memory messages, and the rows survive until the freeing flush.
export async function deleteConversation(id) {
  const gone = state.conversations.find((c) => c.id === id)
  const memImageIds = gone?.messages ? gone.messages.flatMap((m) => m.imageIds || []) : []
  state.conversations = state.conversations.filter((c) => c.id !== id)
  state.runs = state.runs.filter((r) => r.convoId !== id)
  if (currentId.value === id) currentId.value = state.conversations[0]?.id || null
  gcDocs(gone?.docIds)
  const rowImageIds = gone?.messages
    ? []
    : (await db.messages.where('convoId').equals(id).toArray()).flatMap((m) => m.imageIds || [])
  const imageIds = [...new Set([...memImageIds, ...rowImageIds])]
  if (imageIds.length) await gcImages(imageIds)
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
