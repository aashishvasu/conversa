<script setup>
import { Ban, ChevronDown, CircleCheck, GripVertical, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import { ToggleGroupItem, ToggleGroupRoot } from 'reka-ui'
import { utilityCall } from '../jobs/utility.js'
import { CARDGEN_SYSTEM, effectiveCards, matchedCardIds, parseGeneratedCards } from '../prompt/cards.js'
import { effectiveSettings } from '../state/settings.js'
import { workspaceOf } from '../state/store.js'
import { confirmDelete } from '../utils/confirm.js'
import { tr } from '../i18n.js'
import UiButton from './ui/UiButton.vue'
import UiDisclosure from './ui/UiDisclosure.vue'
import UiIconButton from './ui/UiIconButton.vue'
import UiTooltip from './ui/UiTooltip.vue'

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
function setOverride(id, mode) {
  const overrides = (props.convo.cardOverrides ||= {})
  if (mode) overrides[id] = mode
  else delete overrides[id]
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

// WHY: one flat keyed list lets folder edits move a disclosure without losing its open or focus state.
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

function setForce(card, mode) {
  card.force = mode || null
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
    const out = await utilityCall(props.convo, {
      model: effectiveSettings(props.convo).utility_model,
      max_tokens: 4096,
      temperature: 0.2,
      system: CARDGEN_SYSTEM,
      messages: [{ role: 'user', content }],
    })
    for (const c of parseGeneratedCards(out)) {
      props.convo.cards.push({ id: crypto.randomUUID(), ...c })
    }
    genText.value = ''
  } catch (e) {
    const key = { card_list_missing: 'cards.errorNoList', cards_unusable: 'cards.errorNoUsable' }[e?.message]
    genError.value = key ? tr(key) : String(e?.message || e)
  } finally {
    genBusy.value = false
  }
}
async function removeCard(id) {
  if (await confirmDelete(tr('confirm.deleteCard'))) {
    props.convo.cards = props.convo.cards.filter((c) => c.id !== id)
  }
}
</script>

<template>
  <div class="space-y-2 text-sm">
    <p class="text-muted">{{ $t('cards.help') }}</p>

    <!-- Shared cards, read-only here: editing one affects every conversation in the workspace, so edits go through the workspace editor in the sidebar. -->
    <template v-if="ws">
      <p class="px-1 text-xs uppercase text-muted">{{ $t('cards.workspaceCards', { name: ws.name }) }}</p>
      <p v-if="!ws.cards.length" class="px-1 text-xs italic text-muted">{{ $t('cards.noWorkspaceCards') }}</p>
      <UiDisclosure v-for="c in ws.cards" :key="c.id" :class="overrideOf(c.id) === 'skip' ? '!border-warning' : active.has(c.id) ? '!border-success' : ''">
        <template #title>
          <UiTooltip :content="active.has(c.id) ? $t('cards.active') : $t('common.inactive')"><span class="size-2 shrink-0 rounded-full" :class="active.has(c.id) ? 'bg-success' : 'bg-muted'"></span></UiTooltip>
          <span class="truncate text-muted">{{ c.triggers || $t('cards.noTriggers') }}</span>
        </template>
        <template #actions>
          <ToggleGroupRoot type="single" :model-value="overrideOf(c.id) || ''" class="flex" @update:model-value="setOverride(c.id, $event)">
            <UiTooltip :content="$t('cards.alwaysConversation')"><ToggleGroupItem value="include" class="rounded p-1.5 text-muted outline-none hover:bg-surface2 hover:text-success data-[state=on]:text-success focus-visible:ring-2 focus-visible:ring-focus" :aria-label="$t('cards.alwaysConversation')"><CircleCheck :size="14" /></ToggleGroupItem></UiTooltip>
            <UiTooltip :content="$t('cards.excludeConversation')"><ToggleGroupItem value="skip" class="rounded p-1.5 text-muted outline-none hover:bg-surface2 hover:text-warning data-[state=on]:text-warning focus-visible:ring-2 focus-visible:ring-focus" :aria-label="$t('cards.excludeConversation')"><Ban :size="14" /></ToggleGroupItem></UiTooltip>
          </ToggleGroupRoot>
        </template>
        <div class="whitespace-pre-wrap text-muted">{{ c.content }}</div>
      </UiDisclosure>
      <hr class="border-edge" />
    </template>

    <template v-for="row in rows" :key="row.key">
      <p v-if="row.header" class="flex cursor-pointer select-none items-center gap-1 px-1 pt-1 text-xs text-muted" @click="toggleFolder(row.header)">
        <ChevronDown :size="12" class="shrink-0 transition-transform" :class="collapsed.has(row.header) ? '-rotate-90' : ''" />{{ row.header }}
      </p>
      <UiDisclosure
        v-else-if="!collapsed.has(row.path)"
        :data-card-id="row.card.id"
        :class="[row.card.force === 'skip' ? '!border-warning' : active.has(row.card.id) ? '!border-success' : '', dragId === row.card.id ? 'opacity-50' : '', dragId && dragId !== row.card.id && overId === row.card.id ? '!border-t-2 !border-t-accent' : '']"
      >
        <template #title>
          <UiTooltip :content="$t('cards.drag')"><span class="shrink-0 cursor-grab touch-none text-muted active:cursor-grabbing" @click.stop.prevent @pointerdown="onPointerDown($event, row.card.id)" @pointermove="onPointerMove" @pointerup="onPointerUp"><GripVertical :size="14" /></span></UiTooltip>
          <UiTooltip :content="active.has(row.card.id) ? $t('cards.active') : $t('common.inactive')"><span class="size-2 shrink-0 rounded-full" :class="active.has(row.card.id) ? 'bg-success' : 'bg-muted'"></span></UiTooltip>
          <span class="truncate text-muted">{{ row.card.triggers || $t('cards.noTriggers') }}</span>
        </template>
        <template #actions>
          <ToggleGroupRoot type="single" :model-value="row.card.force || ''" class="flex" @update:model-value="setForce(row.card, $event)">
            <UiTooltip :content="$t('cards.always')"><ToggleGroupItem value="include" class="rounded p-1.5 text-muted outline-none hover:bg-surface2 hover:text-success data-[state=on]:text-success focus-visible:ring-2 focus-visible:ring-focus" :aria-label="$t('cards.always')"><CircleCheck :size="14" /></ToggleGroupItem></UiTooltip>
            <UiTooltip :content="$t('cards.exclude')"><ToggleGroupItem value="skip" class="rounded p-1.5 text-muted outline-none hover:bg-surface2 hover:text-warning data-[state=on]:text-warning focus-visible:ring-2 focus-visible:ring-focus" :aria-label="$t('cards.exclude')"><Ban :size="14" /></ToggleGroupItem></UiTooltip>
          </ToggleGroupRoot>
          <UiIconButton :label="$t('cards.delete')" variant="danger" @click="removeCard(row.card.id)"><X :size="14" /></UiIconButton>
        </template>
        <div class="space-y-2">
          <input v-model="row.card.path" list="folder-paths" :placeholder="$t('cards.folder')" class="w-full rounded-md border border-edge bg-surface2 px-2 py-1 text-xs text-muted outline-none focus-visible:ring-2 focus-visible:ring-focus" />
          <input v-model="row.card.triggers" :placeholder="$t('cards.triggerExample')" class="w-full rounded-md border border-edge bg-surface2 px-2 py-1 outline-none focus-visible:ring-2 focus-visible:ring-focus" />
          <textarea v-model="row.card.content" rows="4" :placeholder="$t('cards.contentPlaceholder')" class="w-full rounded-md border border-edge bg-surface2 px-2 py-1 outline-none focus-visible:ring-2 focus-visible:ring-focus"></textarea>
        </div>
      </UiDisclosure>
    </template>

    <UiButton class="w-full" @click="addCard()">{{ $t('cards.add') }}</UiButton>

    <UiDisclosure>
      <template #title><span class="text-muted">{{ $t('cards.generateHeading') }}</span></template>
      <div class="space-y-2">
        <textarea v-model="genText" rows="5" :placeholder="$t('cards.generatePlaceholder')" class="w-full rounded-md border border-edge bg-surface2 px-2 py-1 outline-none focus-visible:ring-2 focus-visible:ring-focus"></textarea>
        <UiButton class="w-full" :disabled="genBusy || !genText.trim()" @click="generate()">{{ genBusy ? $t('cards.generating') : $t('cards.generate') }}</UiButton>
        <p v-if="genError" class="text-xs text-danger">{{ genError }}</p>
      </div>
    </UiDisclosure>
    <datalist id="folder-paths"><option v-for="p in paths" :key="p" :value="p" /></datalist>
  </div>
</template>
