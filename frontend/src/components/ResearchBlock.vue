<script setup>
import { Ban, ChevronRight, Play, Telescope } from '@lucide/vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger, ProgressIndicator, ProgressRoot } from 'reka-ui'
import { discardResearch, startResearch, streamResearch } from '../api/client.js'
import { applyCancel, applyFailure, applyStart, prepareReplacement } from '../research/lifecycle.js'
import { docs, finishRun, persistNow, runById } from '../state/store.js'
import { renderMarkdown } from '../utils/md.js'
import SpendBadge from './SpendBadge.vue'
import UiButton from './ui/UiButton.vue'
import UiTooltip from './ui/UiTooltip.vue'

// The research turn is only a durable lifecycle view. Preparation and all user replies stay normal messages.
const props = defineProps({ message: Object, convo: Object })
const run = computed(() => runById(props.message.runId))
const reportDoc = computed(() => docs.value.find((d) => d.id === props.message.docId) || null)
const running = computed(() => run.value?.status === 'running')
const subquestions = computed(() => run.value?.events?.find((event) => event.kind === 'plan')?.questions || [])
const sources = computed(() => run.value?.events?.filter((event) => event.kind === 'source') || [])
const read = computed(() => sources.value.filter((source) => !source.error).length)
const spend = computed(() => run.value?.spend || { calls: 0, input: 0, output: 0, usd: 0, unpriced: 0 })
const responseText = computed(() => props.message.content || '')
const traceOpen = ref(false)
const error = ref('')
const MAX_STREAM_RETRIES = 5
let abort = null

function requestBody(current) {
  return {
    id: current.serverId,
    goal: current.prepared.goal,
    title: current.prepared.goal,
    depth: current.settings.research_depth,
    models: {
      search: current.settings.research_search_model,
      note: current.settings.research_note_model,
      report: current.settings.research_report_model,
    },
  }
}

// Starting is safe to repeat: the backend keys retained work by this persisted browser id.
async function start(tailAfter = true) {
  const current = run.value
  if (!current?.serverId || !['starting', 'error'].includes(current.status)) return false
  Object.assign(current, { status: 'starting', error: null, updatedAt: Date.now() })
  error.value = ''
  await persistNow()
  try {
    applyStart(current, await startResearch(requestBody(current)))
    await persistNow()
    if (tailAfter) void tail(true)
    return true
  } catch (err) {
    applyFailure(current, err)
    await persistNow()
    return false
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function tail(allowTerminal = false) {
  if (!run.value?.serverId || (!allowTerminal && !running.value)) return
  abort?.abort()
  const controller = new AbortController()
  abort = controller
  let failures = 0
  while (!controller.signal.aborted && (allowTerminal || run.value?.status === 'running')) {
    try {
      await streamResearch(run.value.serverId, run.value.events.length, onEvent, controller.signal)
      if (run.value?.status !== 'running') return
      error.value = 'research stream ended unexpectedly'
    } catch (err) {
      if (controller.signal.aborted) return
      if (prepareReplacement(run.value, err)) {
        await persistNow()
        if (!await start(false)) return
        allowTerminal = true
        failures = 0
        continue
      }
      error.value = err.message
    }
    failures++
    if (failures >= MAX_STREAM_RETRIES) {
      // A stream that cannot be observed is no longer an active browser run. Cancel best-effort, then unlock the conversation.
      try {
        await discardResearch(run.value.serverId)
      } catch { /* the backend may be the failed hop */ }
      applyFailure(run.value, new Error(error.value || 'research stream failed'))
      await persistNow()
      return
    }
    await wait(500 * 2 ** (failures - 1))
  }
}

async function onEvent(data) {
  const current = run.value
  if (!current) return
  if (data.spend) current.spend = data.spend
  if (data.kind === 'tick') {
    current.phase = data.phase
    return
  }
  if (data.kind === 'final') {
    finishRun(current, data)
    if (data.error) error.value = data.error
    await persistNow()
    try {
      await discardResearch(current.serverId)
    } catch { /* eviction clears an already-finished backend run */ }
    return
  }
  current.events.push(data)
  if (data.kind === 'phase') current.phase = data.phase
}

async function stopRun() {
  const current = run.value
  if (!current?.serverId) return
  try {
    await discardResearch(current.serverId)
    applyCancel(current)
    await persistNow()
  } catch (err) {
    error.value = err.message
  }
}

function retry() {
  if (run.value?.status === 'running') void tail()
  else void start()
}

onMounted(() => {
  if (run.value?.status === 'starting') void start()
  else if (run.value?.status === 'running') void tail()
})
onUnmounted(() => abort?.abort())
</script>

<template>
  <div v-if="run" class="max-w-2xl rounded-lg border border-edge bg-surface px-4 py-3 text-sm">
    <div class="flex items-center gap-2">
      <Telescope :size="14" class="shrink-0" :class="running ? 'text-accent' : 'text-muted'" />
      <span class="min-w-0 flex-1 truncate text-xs uppercase tracking-wide text-muted">
        {{ running || run.status === 'starting' ? run.phase || $t('research.statusStarting') : $t(`research.status.${run.status}`) }}
        <template v-if="spend.calls">· <SpendBadge :spend="spend" /></template>
      </span>
      <UiButton v-if="running" size="compact" @click="stopRun"><Ban :size="12" /> {{ $t('common.stop') }}</UiButton>
    </div>
    <ProgressRoot v-if="running" :model-value="null" class="mt-2 h-1 overflow-hidden rounded-full bg-edge" :aria-label="$t('research.statusStarting')">
      <ProgressIndicator class="research-progress h-full w-1/3 rounded-full bg-accent" />
    </ProgressRoot>

    <CollapsibleRoot v-if="subquestions.length" v-model:open="traceOpen" class="mt-2">
      <CollapsibleTrigger class="flex w-full items-center gap-1 rounded-sm text-xs uppercase tracking-wide text-muted outline-none hover:text-base focus-visible:ring-2 focus-visible:ring-focus">
        <ChevronRight :size="12" class="transition-transform" :class="traceOpen && 'rotate-90'" />
        {{ $t('research.subquestions', subquestions.length, { count: subquestions.length }) }} · {{ $t('research.sourcesRead', { read, total: sources.length }) }}
      </CollapsibleTrigger>
      <CollapsibleContent class="mt-1 space-y-2 border-l-2 border-accent/40 pl-2">
        <div v-for="(question, index) in subquestions" :key="question" class="flex gap-2 text-xs"><span class="shrink-0 text-muted">q{{ index + 1 }}</span><span>{{ question }}</span></div>
        <div v-if="sources.length" class="max-h-48 space-y-0.5 overflow-y-auto">
          <UiTooltip v-for="(source, index) in sources" :key="index" :content="source.error || source.url"><p class="truncate text-xs text-muted" :class="source.error && 'line-through'">{{ source.url || source.error }}</p></UiTooltip>
        </div>
      </CollapsibleContent>
    </CollapsibleRoot>

    <div v-if="responseText" class="md mt-3 [overflow-wrap:anywhere]" v-html="renderMarkdown(responseText)"></div>
    <p v-if="reportDoc" class="mt-2 text-xs text-muted">{{ $t('research.attached', { name: reportDoc.name }) }}</p>
    <p v-if="error || run.error" class="mt-2 text-xs text-danger">{{ error || run.error }}</p>
    <UiButton v-if="run.status === 'error' || (error && running)" class="mt-2" size="compact" @click="retry"><Play :size="12" /> {{ $t('research.runAgain') }}</UiButton>
  </div>
  <div v-else class="max-w-2xl rounded-lg border border-edge bg-surface px-4 py-3 text-xs text-muted">
    <Telescope :size="12" class="mr-1 inline" /> {{ $t('research.missingRun') }}
  </div>
</template>
