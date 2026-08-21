<script setup>
import { Ban, ChevronDown, CircleCheck, GripVertical, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import { streamChat } from '../api.js'
import { CARDGEN_SYSTEM, effectiveCards, matchedCardIds, parseGeneratedCards } from '../cards.js'
import { confirmDelete } from '../confirm.js'
import { effectiveSettings, workspaceOf } from '../store.js'

// Also reused by WorkspacePanel with a workspace as `convo`; workspaces have cards but no messages, settings, or workspaceId, so those reads are guarded below.
const props = defineProps({ convo: Object })

const ws = computed(() => workspaceOf(props.convo))

// Live preview: which cards would fire against the current send window.
// Includes workspace cards so the read-only section below gets active dots too.
const active = computed(() => {
  const n = effectiveSettings(props.convo).num_messages_to_send
  const turns = (props.convo.messages || []).filter((m) => m.role !== 'system').slice(-n)
  return matchedCardIds(effectiveCards(props.convo, ws.value), turns, props.convo.scanAssistant)
})

// Per-convo override of a shared workspace card: same tri-state as force, stored on the convo (cardOverrides), so it applies to this conversation alone.
function overrideOf(id) {
  return props.convo.cardOverrides?.[id] || null
}
function toggleOverride(e, id, mode) {
  const ov = (props.convo.cardOverrides ||= {})
  ov[id] === mode ? delete ov[id] : (ov[id] = mode)
  e.currentTarget.blur()
}

// Cards grouped by their (display-only) folder path.
// Named folders first in first-appearance order, ungrouped cards last.
// Matching ignores path entirely.
const groups = computed(() => {
  const byPath = new Map()
  for (const card of props.convo.cards) {
    const key = (card.path || '').trim()
    if (!byPath.has(key)) byPath.set(key, [])
    byPath.get(key).push(card)
  }
  const entries = [...byPath.entries()]
  return [...entries.filter(([k]) => k), ...entries.filter(([k]) => !k)]
})

// Flattened to header + card rows so every <details> shares one parent.
// Editing a card's folder then moves its node instead of recreating it, which keeps it open and focused mid-edit.
const rows = computed(() => {
  const out = []
  for (const [path, cards] of groups.value) {
    if (path) out.push({ key: `h:${path}`, header: path })
    for (const card of cards) out.push({ key: card.id, card, path })
  }
  return out
})

// Folder-name autocomplete: reactivity is the cache.
const paths = computed(() => [...new Set(props.convo.cards.map((c) => c.path).filter(Boolean))])

// Collapsed folders are session-only; persist in prefs.js if it ever matters.
const collapsed = ref(new Set())
function toggleFolder(path) {
  const s = new Set(collapsed.value)
  s.has(path) ? s.delete(path) : s.add(path)
  collapsed.value = s
}

// Drag-to-reorder.
// Dropping onto a card moves the dragged card next to it and adopts its folder, so one gesture both reorders and re-files across groups.
// Pointer events (not native HTML5 DnD, which never fires on touch): pointer capture routes move/up to the grip; elementFromPoint finds the card under the finger.
const dragId = ref(null)
const overId = ref(null)
function onPointerDown(e, id) {
  dragId.value = id
  e.target.setPointerCapture?.(e.pointerId)
}
function onPointerMove(e) {
  if (!dragId.value) return
  const el = document.elementFromPoint(e.clientX, e.clientY)?.closest('[data-card-id]')
  overId.value = el?.dataset.cardId ?? null
}
function onPointerUp() {
  const id = dragId.value
  const target = overId.value
  dragId.value = overId.value = null
  if (!id || !target || id === target) return
  const cards = props.convo.cards
  const moved = cards.splice(cards.findIndex((c) => c.id === id), 1)[0]
  moved.path = cards.find((c) => c.id === target)?.path || ''
  cards.splice(cards.findIndex((c) => c.id === target), 0, moved)
}

// Tri-state override: click to set, click again to clear back to trigger matching.
// Blur so the tapped button drops its highlight immediately (touch leaves :focus/:hover stuck).
function toggleForce(e, card, mode) {
  card.force = card.force === mode ? null : mode
  e.currentTarget.blur()
}

function addCard() {
  props.convo.cards.push({ id: crypto.randomUUID(), triggers: '', content: '' })
}

// Card builder: utility model decomposes pasted text into trigger cards, appended here for review.
// Works in both scopes because cards land on whatever owner this panel got.
const genText = ref('')
const genBusy = ref(false)
const genError = ref('')
async function generate() {
  if (!genText.value.trim() || genBusy.value) return
  genBusy.value = true
  genError.value = ''
  try {
    // A few real cards anchor granularity and trigger style better than the syntax spec alone.
    // One per folder when folders exist, since folders are where style diverges; else the first few.
    const usable = effectiveCards(props.convo, ws.value).filter((c) => c.triggers.trim() && c.content.trim())
    const byFolder = new Map()
    for (const c of usable) {
      const key = (c.path || '').trim()
      if (!byFolder.has(key)) byFolder.set(key, c)
    }
    const picks = byFolder.size > 1 ? [...byFolder.values()] : usable.slice(0, 3)
    const examples = picks.map((c) => JSON.stringify({ triggers: c.triggers, content: c.content.slice(0, 300) })).join('\n')
    const content = examples
      ? `Existing cards, match their granularity and trigger style:\n${examples}\n\nText to convert:\n${genText.value}`
      : genText.value
    let out = ''
    await streamChat(
      {
        model: effectiveSettings(props.convo).utility_model,
        max_tokens: 4096,
        temperature: 0.2,
        system: CARDGEN_SYSTEM,
        messages: [{ role: 'user', content }],
      },
      (t) => (out += t),
    )
    for (const c of parseGeneratedCards(out)) {
      props.convo.cards.push({ id: crypto.randomUUID(), ...c })
    }
    genText.value = ''
  } catch (e) {
    genError.value = String(e?.message || e)
  } finally {
    genBusy.value = false
  }
}
async function removeCard(id) {
  if (await confirmDelete('Delete this card?')) {
    props.convo.cards = props.convo.cards.filter((c) => c.id !== id)
  }
}
</script>

<template>
  <div class="space-y-2 text-sm">
    <p class="text-muted">
      Trigger phrases: comma = OR, &amp; = AND ("dragon &amp; red, wyrm" fires on wyrm, or on
      dragon and red together). When a clause matches the last messages sent, the card's
      text is added to the system prompt. Click a card to expand.
    </p>

    <!-- Shared cards, read-only here: editing one affects every conversation in the
         workspace, so edits go through the workspace editor in the sidebar. -->
    <template v-if="ws">
      <p class="px-1 text-xs uppercase text-muted">Workspace cards · {{ ws.name }} (edit in workspace; include/exclude is per-conversation)</p>
      <p v-if="!ws.cards.length" class="px-1 text-xs italic text-muted">No workspace cards.</p>
      <details v-for="c in ws.cards" :key="c.id" class="rounded border" :class="overrideOf(c.id) === 'skip' ? 'border-yellow-500' : active.has(c.id) ? 'border-green-500' : 'border-edge'">
        <summary class="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 [&::-webkit-details-marker]:hidden">
          <span class="h-2 w-2 shrink-0 rounded-full" :class="active.has(c.id) ? 'bg-green-500' : 'bg-muted'" :title="active.has(c.id) ? 'Active for next send' : 'Inactive'"></span>
          <span class="flex-1 truncate text-muted">{{ c.triggers || 'No triggers' }}</span>
          <button class="shrink-0" :class="overrideOf(c.id) === 'include' ? 'text-green-500' : 'text-muted hover:text-green-500'" title="Include in this conversation: always send" @click.stop.prevent="toggleOverride($event, c.id, 'include')"><CircleCheck :size="14" /></button>
          <button class="shrink-0" :class="overrideOf(c.id) === 'skip' ? 'text-yellow-500' : 'text-muted hover:text-yellow-500'" title="Exclude from this conversation: never send" @click.stop.prevent="toggleOverride($event, c.id, 'skip')"><Ban :size="14" /></button>
        </summary>
        <div class="whitespace-pre-wrap border-t border-edge p-2 text-muted">{{ c.content }}</div>
      </details>
      <hr class="border-edge" />
    </template>

    <template v-for="row in rows" :key="row.key">
      <p v-if="row.header" class="flex cursor-pointer select-none items-center gap-1 px-1 pt-1 text-xs text-muted" @click="toggleFolder(row.header)">
        <ChevronDown :size="12" class="shrink-0 transition-transform" :class="collapsed.has(row.header) ? '-rotate-90' : ''" />{{ row.header }}
      </p>
      <details
        v-else-if="!collapsed.has(row.path)"
        class="rounded border"
        :data-card-id="row.card.id"
        :class="[row.card.force === 'skip' ? 'border-yellow-500' : active.has(row.card.id) ? 'border-green-500' : 'border-edge', dragId === row.card.id ? 'opacity-50' : '', dragId && dragId !== row.card.id && overId === row.card.id ? 'border-t-2 border-t-blue-500' : '']"
      >
        <summary class="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 [&::-webkit-details-marker]:hidden">
          <span class="shrink-0 cursor-grab touch-none text-muted active:cursor-grabbing" title="Drag to reorder or move folder" @click.stop.prevent @pointerdown="onPointerDown($event, row.card.id)" @pointermove="onPointerMove" @pointerup="onPointerUp"><GripVertical :size="14" /></span>
          <span class="h-2 w-2 shrink-0 rounded-full" :class="active.has(row.card.id) ? 'bg-green-500' : 'bg-muted'" :title="active.has(row.card.id) ? 'Active for next send' : 'Inactive'"></span>
          <span class="flex-1 truncate text-muted">{{ row.card.triggers || 'No triggers' }}</span>
          <button class="shrink-0" :class="row.card.force === 'include' ? 'text-green-500' : 'text-muted hover:text-green-500'" title="Force include: always send this card" @click.stop.prevent="toggleForce($event, row.card, 'include')"><CircleCheck :size="14" /></button>
          <button class="shrink-0" :class="row.card.force === 'skip' ? 'text-yellow-500' : 'text-muted hover:text-yellow-500'" title="Force skip: never send this card" @click.stop.prevent="toggleForce($event, row.card, 'skip')"><Ban :size="14" /></button>
          <button class="shrink-0 border-l border-edge pl-2 text-muted hover:text-red-500" title="Delete card" @click.stop.prevent="removeCard(row.card.id)"><X :size="14" /></button>
        </summary>
        <div class="space-y-2 border-t border-edge p-2">
          <input v-model="row.card.path" list="folder-paths" placeholder="Folder (optional)" class="w-full rounded bg-surface2 px-2 py-1 text-xs text-muted" />
          <input v-model="row.card.triggers" placeholder="dragon &amp; red, wyrm, ancient lizard" class="w-full rounded bg-surface2 px-2 py-1" />
          <textarea v-model="row.card.content" rows="4" placeholder="What this card adds when triggered…" class="w-full rounded bg-surface2 px-2 py-1"></textarea>
        </div>
      </details>
    </template>

    <button class="w-full rounded bg-surface2 py-2 hover:opacity-80" @click="addCard()">+ Add card</button>

    <details class="rounded border border-edge">
      <summary class="cursor-pointer list-none px-2 py-1.5 text-muted [&::-webkit-details-marker]:hidden">Generate cards from text</summary>
      <div class="space-y-2 border-t border-edge p-2">
        <textarea v-model="genText" rows="5" placeholder="Paste text (a large system prompt, lore, notes…); the utility model splits it into trigger cards you can edit above." class="w-full rounded bg-surface2 px-2 py-1"></textarea>
        <button class="w-full rounded bg-surface2 py-2 hover:opacity-80 disabled:opacity-50" :disabled="genBusy || !genText.trim()" @click="generate()">{{ genBusy ? 'Generating…' : 'Generate' }}</button>
        <p v-if="genError" class="text-xs text-red-500">{{ genError }}</p>
      </div>
    </details>
    <datalist id="folder-paths"><option v-for="p in paths" :key="p" :value="p" /></datalist>
  </div>
</template>
