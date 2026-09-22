<script setup>
import { Ban, ChevronRight, Play, Telescope } from '@lucide/vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger, ProgressIndicator, ProgressRoot } from 'reka-ui'
import { discardResearch, prepareResearch, startResearch, streamResearch } from '../api/client.js'
import { applyCancel, applyFailure, applyPrepared, applyStart, buildResearchStartBody, prepareReplacement, resumeWithCurrentModels } from '../research/lifecycle.js'
import { docs, finishRun, persistNow, runById } from '../state/store.js'
import { effectiveSettings, RESEARCH_KEYS } from '../state/settings.js'
import { renderMarkdown } from '../utils/md.js'
import SpendBadge from './SpendBadge.vue'
import UiButton from './ui/UiButton.vue'

const props = defineProps({ message: Object, convo: Object })
const run = computed(() => runById(props.message.runId))
const reportDoc = computed(() => docs.value.find((doc) => doc.id === props.message.docId) || null)
const brief = computed(() => run.value?.prepared?.brief || {})
const questions = computed(() => brief.value.questions || [])
const answers = ref({})
const active = computed(() => ['starting', 'running'].includes(run.value?.status))
const waiting = computed(() => run.value?.status === 'waiting_for_clarification')
const spend = computed(() => run.value?.spend || { calls: 0, input: 0, output: 0, usd: 0, unpriced: 0 })
const sources = computed(() => {
  const seen = new Set()
  const rows = [...Object.values(run.value?.checkpoint?.sources || {}), ...(run.value?.events || []).filter((event) => ['source', 'source_reused', 'source_failed'].includes(event.kind))]
  return rows.filter((source) => {
    const key = source.url || source.source || source.title || JSON.stringify(source)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
const evidence = computed(() => {
  const ids = new Set((run.value?.checkpoint?.evidence || []).map((item) => item.id))
  for (const event of run.value?.events || []) {
    if (event.kind === 'evidence') ids.add(event.evidence?.id || event.evidence_id || `event-${event.seq}`)
  }
  return ids.size
})
const warnings = computed(() => {
  const seen = new Set()
  return [...(run.value?.checkpoint?.breakers || []), ...(run.value?.events || []).filter((event) => ['warn', 'breaker'].includes(event.kind))].filter((warning) => {
    const key = [warning.kind, warning.branch, warning.task_id, warning.url, warning.message || warning.reason].join('|')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
const tasks = computed(() => {
  const latest = new Map((run.value?.checkpoint?.frontier || []).map((task) => [task.id, { kind: `task_${task.status}`, task }]))
  for (const event of run.value?.events || []) {
    if (!['task_added', 'task_started', 'task_resolved', 'task_pruned', 'task_merged'].includes(event.kind)) continue
    const task = event.task && typeof event.task === 'object' ? event.task : event
    const id = task.id || task.task_id || task.question || task.label || event.seq
    latest.set(id, { ...event, task })
  }
  return [...latest.values()]
})
const traceOpen = ref(false)
const error = ref('')
let abort = null
const MAX_STREAM_RETRIES = 5

function taskLabel(item) {
  const task = item.task || item
  return task.question || task.label || task.title || (typeof task.task === 'string' ? task.task : '') || item.kind
}

function answerFor(question) {
  return String(answers.value[question.question] ?? question.default ?? '').trim()
}

function hasMissingAnswers() {
  return questions.value.some((question) => !answerFor(question))
}

async function start() {
  const current = run.value
  if (!current || !['waiting_for_clarification', 'starting', 'error'].includes(current.status)) return false
  if (questions.value.length && hasMissingAnswers()) return false
  current.answers = Object.fromEntries(questions.value.map((question) => [question.question, answerFor(question)]))
  current.prepared.answers = current.answers
  Object.assign(current, { status: 'starting', error: null, updatedAt: Date.now() })
  await persistNow()
  try {
    applyStart(current, await startResearch(buildResearchStartBody(current)))
    await persistNow()
    void tail(true)
    return true
  } catch (startError) {
    applyFailure(current, startError)
    await persistNow()
    return false
  }
}

function useDefaults() {
  Object.assign(answers.value, Object.fromEntries(questions.value.map((question) => [question.question, question.default || ''])))
  void start()
}

async function retryPreparation() {
  const current = run.value
  if (!current) return
  try {
    const input = { ...current.input, model: effectiveSettings(props.convo).model }
    current.input = input
    const prepared = await prepareResearch(input)
    applyPrepared(current, prepared)
    await persistNow()
    if (current.status === 'starting') void start()
  } catch (preparationError) {
    current.error = preparationError.message
    await persistNow()
  }
}

async function tail(allowTerminal = false) {
  if (!run.value?.serverId || (!allowTerminal && !active.value)) return
  abort?.abort()
  const controller = new AbortController()
  abort = controller
  let failures = 0
  while (!controller.signal.aborted && (allowTerminal || active.value)) {
    try {
      await streamResearch(run.value.serverId, run.value.events.length, onEvent, controller.signal)
      if (run.value?.status !== 'running') return
      error.value = 'research stream ended unexpectedly'
    } catch (streamError) {
      if (controller.signal.aborted) return
      if (prepareReplacement(run.value, streamError)) {
        await persistNow()
        if (!await start()) return
        failures = 0
        continue
      }
      error.value = streamError.message
    }
    failures++
    if (failures >= MAX_STREAM_RETRIES) {
      applyFailure(run.value, new Error(error.value || 'research stream failed'))
      await persistNow()
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** (failures - 1)))
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
    try { await discardResearch(current.serverId) } catch {}
    return
  }
  current.events.push(data)
  if (data.checkpoint) current.checkpoint = data.checkpoint
  if (data.kind === 'phase') current.phase = data.phase
  await persistNow()
}

async function stopRun() {
  const current = run.value
  if (!current?.serverId) return
  try {
    await discardResearch(current.serverId)
    applyCancel(current)
    await persistNow()
  } catch (stopError) {
    error.value = stopError.message
  }
}

async function resumeWithModels() {
  const current = run.value
  if (!current) return
  resumeWithCurrentModels(current, effectiveSettings(props.convo, RESEARCH_KEYS))
  await persistNow()
  void start()
}

function retry() {
  if (run.value?.preparationFailed) void retryPreparation()
  else if (run.value?.status === 'running') void tail()
  else {
    run.value.retryFailed = true
    void start()
  }
}

onMounted(() => {
  if (run.value?.status === 'starting' && !questions.value.length) void start()
  else if (run.value?.status === 'running') void tail()
})

onUnmounted(() => abort?.abort())
</script>

<template>
  <div v-if="run" class="max-w-2xl rounded-lg border border-edge bg-surface px-4 py-3 text-sm">
    <div class="flex items-center gap-2">
      <Telescope :size="14" class="shrink-0" :class="active ? 'text-accent' : 'text-muted'" />
      <span class="min-w-0 flex-1 truncate text-xs uppercase tracking-wide text-muted">
        {{ active ? (run.phase || $t('research.statusStarting')) : $t(`research.status.${run.status}`) }}
        <template v-if="spend.calls">· <SpendBadge :spend="spend" /></template>
      </span>
      <UiButton v-if="active" size="compact" @click="stopRun"><Ban :size="12" /> {{ $t('common.stop') }}</UiButton>
    </div>

    <ProgressRoot v-if="active" :model-value="null" class="mt-2 h-1 overflow-hidden rounded-full bg-edge" :aria-label="$t('research.statusStarting')">
      <ProgressIndicator class="research-progress h-full w-1/3 rounded-full bg-accent" />
    </ProgressRoot>

    <div class="mt-3 space-y-2 text-xs">
      <p v-if="brief.objective"><strong class="after:content-[':']">{{ $t('research.objective') }}</strong> {{ brief.objective }}</p>
      <p v-if="brief.deliverable"><strong class="after:content-[':']">{{ $t('research.deliverable') }}</strong> {{ brief.deliverable }}</p>
      <p v-if="brief.scope?.length"><strong class="after:content-[':']">{{ $t('research.scope') }}</strong> {{ brief.scope.join(', ') }}</p>
      <p v-if="brief.constraints?.length"><strong class="after:content-[':']">{{ $t('research.constraints') }}</strong> {{ brief.constraints.join(', ') }}</p>
    </div>

    <form v-if="questions.length && waiting" class="mt-3 space-y-2" @submit.prevent="start">
      <label v-for="question in questions" :key="question.question" class="block">
        <span class="font-medium">{{ question.question }}</span>
        <span v-if="question.reason" class="block text-muted">{{ question.reason }}</span>
        <input v-model="answers[question.question]" :placeholder="question.default" class="mt-1 w-full rounded border border-edge bg-app px-2 py-1" />
      </label>
      <div class="flex gap-2">
        <UiButton type="submit" size="compact"><Play :size="12" /> {{ $t('research.startWithAnswers') }}</UiButton>
        <UiButton type="button" size="compact" variant="ghost" @click="useDefaults">{{ $t('research.startWithDefaults') }}</UiButton>
      </div>
    </form>

    <CollapsibleRoot v-if="tasks.length || sources.length || evidence || warnings.length" v-model:open="traceOpen" class="mt-3">
      <CollapsibleTrigger class="flex w-full items-center gap-1 text-xs uppercase tracking-wide text-muted">
        <ChevronRight :size="12" :class="traceOpen && 'rotate-90'" />
        {{ $t('research.trace') }} · {{ tasks.length }} · {{ sources.length }} · {{ evidence }}
      </CollapsibleTrigger>
      <CollapsibleContent class="mt-2 space-y-1 border-l-2 border-accent/40 pl-2 text-xs">
        <p v-for="task in tasks" :key="task.task?.id || task.id || task.seq">{{ taskLabel(task) }}</p>
        <p v-for="(source, index) in sources" :key="`source-${index}`" class="truncate">{{ source.url || source.title || source.error }}</p>
        <p v-for="(warning, index) in warnings" :key="`warning-${index}`" class="text-warning">{{ warning.reason || warning.message || warning.error || warning.kind }}</p>
      </CollapsibleContent>
    </CollapsibleRoot>

    <div v-if="message.content" class="md mt-3 [overflow-wrap:anywhere]" v-html="renderMarkdown(message.content)"></div>
    <p v-if="reportDoc" class="mt-2 text-xs text-muted">{{ $t('research.attached', { name: reportDoc.name }) }}</p>
    <p v-if="error || run.error" class="mt-2 text-xs text-danger">{{ error || run.error }}</p>
    <div v-if="run.status === 'error'" class="mt-2 flex gap-2">
      <UiButton size="compact" @click="retry"><Play :size="12" /> {{ $t(run.preparationFailed ? 'research.retryPreparation' : 'research.runAgain') }}</UiButton>
      <UiButton v-if="!run.preparationFailed && run.checkpoint" size="compact" variant="ghost" @click="resumeWithModels">{{ $t('research.resumeWithModels') }}</UiButton>
    </div>
  </div>
  <div v-else class="max-w-2xl rounded-lg border border-edge bg-surface px-4 py-3 text-xs text-muted">
    <Telescope :size="12" class="mr-1 inline" /> {{ $t('research.missingRun') }}
  </div>
</template>
