import { computed } from 'vue'
import { state } from './persistence.js'
import { gcDocs } from './docs.js'
import { tr } from '../i18n/index.js'

export const workspaces = computed(() => state.workspaces)

export function createWorkspace(name = tr('sidebar.newWorkspace')) {
  const w = { id: crypto.randomUUID(), name, messages: [], cards: [], docIds: [] }
  state.workspaces.push(w)
  return w
}

export function deleteWorkspace(id) {
  const gone = state.workspaces.find((w) => w.id === id)
  state.workspaces = state.workspaces.filter((w) => w.id !== id)
  for (const c of state.conversations) if (c.workspaceId === id) c.workspaceId = null
  gcDocs(gone?.docIds)
}

// A workspace holds shared system prompts as message-shaped entries, the same shape a conversation uses.
// Pre-v5 workspaces held one `systemPrompt` string; it becomes the first entry so old archives and current ones assemble identically.
// Runs on every entry path (initStore, importData, restoreData), the hoistInlineDocs arrangement.
export function migrateWorkspacePrompts(workspaces) {
  for (const w of workspaces) {
    w.messages ??= w.systemPrompt?.trim() ? [{ id: crypto.randomUUID(), role: 'system', content: w.systemPrompt, createdAt: Date.now() }] : []
    delete w.systemPrompt
  }
}

// null when the convo has no workspace, or its workspace was deleted or not imported; callers degrade to plain-convo behavior.
export function workspaceOf(convo) {
  return state.workspaces.find((w) => w.id === convo?.workspaceId) || null
}
