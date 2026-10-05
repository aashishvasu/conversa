import { computed } from 'vue'
import { state } from './persistence.js'
import { gcDocs } from './docs.js'
import { tr } from '../i18n/index.js'

export const workspaces = computed(() => state.workspaces)

export function createWorkspace(name = tr('sidebar.newWorkspace')) {
  const w = { id: crypto.randomUUID(), name, systemPrompt: '', cards: [], docIds: [] }
  state.workspaces.push(w)
  return w
}

export function deleteWorkspace(id) {
  const gone = state.workspaces.find((w) => w.id === id)
  state.workspaces = state.workspaces.filter((w) => w.id !== id)
  for (const c of state.conversations) if (c.workspaceId === id) c.workspaceId = null
  gcDocs(gone?.docIds)
}

// null when the convo has no workspace, or its workspace was deleted or not imported; callers degrade to plain-convo behavior.
export function workspaceOf(convo) {
  return state.workspaces.find((w) => w.id === convo?.workspaceId) || null
}
