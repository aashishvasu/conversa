<script setup>
import { Ban, ChevronRight, Play, RotateCcw, Telescope } from '@lucide/vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from 'reka-ui'
import { clarifyResearch, discardResearch, startResearch, streamResearch } from '../api.js'
import { effectiveSettings, RESEARCH_KEYS } from '../settings.js'
import { docs, finishRun, persistNow, runById } from '../store.js'
import { renderMarkdown } from '../utils/md.js'
import ModelSelect from './ModelSelect.vue'
import SpendBadge from './SpendBadge.vue'

// The research turn's timeline item: clarify, confirm, live progress, and the finished report, all on the assistant placeholder message.
// The run record (store.js) is the durable state; this component is a view over it plus the live stream.
const props = defineProps({ message: Object, convo: Object })

const run = computed(() => runById(props.message.runId))
const reportDoc = computed(() => docs.value.find((d) => d.id === props.message.docId) || null)

const settings = computed(() => effectiveSettings(run.value, RESEARCH_KEYS))
const eff = (k) => settings.value[k]
const overridden = (k) => run.value.settings[k] !== undefined
const setOv = (k, v) => (run.value.settings[k] = v)
const reset = (k) => delete run.value.settings[k]

const error = ref('')
const busy = ref('')
let abort = null

const running = computed(() => run.value?.status === 'running')
const subquestions = computed(() => run.value?.events?.find((e) => e.kind === 'plan')?.questions || [])
const sources = computed(() => run.value?.events?.filter((e) => e.kind === 'source') || [])
const read = computed(() => sources.value.filter((s) => !s.error).length)
const spend = computed(() => run.value?.spend || { calls: 0, input: 0, output: 0, usd: 0, unpriced: 0 })
const reportText = computed(() => reportDoc.value?.text || run.value?.payload?.report?.text || '')
const traceOpen = ref(false)
const reportOpen = ref(false)

// The clarifying exchange leans on the conversation for pronouns and prior decisions: the last few turns before the request, bounded so a long history stays an excerpt.
function conversationExcerpt() {
  const cut = props.convo.messages.findIndex((m) => m.id === run.value.promptMessageId)
  const turns = (cut < 0 ? [] : props.convo.messages.slice(0, cut)).filter((m) => m.role !== 'system' && m.content)
  return turns.slice(-6).map((m) => `${m.role}: ${m.content}`).join('\n\n').slice(-4000) || null
}

// Clarification runs once per run, unprompted; a complete brief comes back with no questions and only the confirm remains.
async function ask() {
  busy.value = 'clarify'
  error.value = ''
  try {
    run.value.questions = await clarifyResearch(run.value.brief, eff('research_report_model'), conversationExcerpt())
    run.value.clarified = true
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = ''
  }
}

// Answered clarifying questions join the planner's brief.
function fullBrief() {
  const r = run.value
  const answers = (r.answers || '').trim()
  if (!r.questions?.length || !answers) return r.brief.trim()
  return `${r.brief.trim()}\n\nClarifications:\n${r.questions.map((q) => `Q: ${q}`).join('\n')}\n\nA: ${answers}`
}

async function start() {
  busy.value = 'start'
  error.value = ''
  try {
    const { id } = await startResearch({
      brief: fullBrief(),
      title: run.value.brief.trim(),
      depth: eff('research_depth'),
      models: {
        search: eff('research_search_model'),
        note: eff('research_note_model'),
        report: eff('research_report_model'),
      },
    })
    Object.assign(run.value, { serverId: id, status: 'running', phase: 'plan', events: [], payload: null, spend: null, updatedAt: Date.now() })
    traceOpen.value = true
    tail()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = ''
  }
}

// Reconnect from the last stored sequence while the run remains active.
async function tail() {
  abort?.abort()
  const ctl = (abort = new AbortController())
  while (!ctl.signal.aborted && run.value?.serverId && run.value.status === 'running') {
    try {
      await streamResearch(run.value.serverId, run.value.events.length, onEvent, ctl.signal)
    } catch (e) {
      if (!ctl.signal.aborted) error.value = e.message
      return
    }
    await new Promise((r) => setTimeout(r, 500))
  }
}

async function onEvent(data) {
  const r = run.value
  if (!r) return
  if (data.spend) r.spend = data.spend
  // A tick is a keep-alive with no seq, so it updates the counters and stays out of the replay position.
  if (data.kind === 'tick') {
    r.phase = data.phase
    return
  }
  if (data.kind === 'final') {
    finishRun(r, data)
    if (data.error) error.value = data.error
    traceOpen.value = false
    // Save before forget: the backend copy goes only after the report and spend are persisted here.
    await persistNow()
    try {
      await discardResearch(r.serverId)
    } catch { /* the eviction sweep will get it */ }
    return
  }
  r.events.push(data)
  if (data.kind === 'phase') r.phase = data.phase
}

async function stopRun() {
  if (!run.value?.serverId) return
  try {
    await discardResearch(run.value.serverId)
  } catch (e) {
    error.value = e.message
  }
  tail() // re-arm, in case the stream this was meant to end had already dropped
}

onMounted(() => {
  if (!run.value) return
  if (run.value.status === 'running') tail()
  else if (run.value.status === 'draft' && !run.value.clarified) ask()
})
onUnmounted(() => abort?.abort())
</script>

<template>
  <div v-if="run" class="max-w-2xl rounded-lg border border-edge bg-surface px-4 py-3 text-sm">
    <div class="flex items-center gap-2">
      <Telescope :size="14" class="shrink-0" :class="running ? 'text-indigo-500' : 'text-muted'" />
      <span class="min-w-0 flex-1 truncate text-xs uppercase tracking-wide text-muted">
        {{ running ? run.phase || 'starting' : run.status === 'draft' ? 'research' : run.status }}
        <template v-if="spend.calls">· <SpendBadge :spend="spend" /></template>
      </span>
      <button v-if="running" class="flex shrink-0 items-center gap-1 rounded bg-surface2 px-2 py-1 text-xs hover:text-red-500" @click="stopRun">
        <Ban :size="12" /> Stop
      </button>
    </div>

    <!-- Scope confirmation: clarifying questions, per-run models, and the explicit start -->
    <div v-if="run.status === 'draft'" class="mt-2 space-y-2">
      <p v-if="busy === 'clarify'" class="text-muted">Checking what the brief leaves open…</p>
      <template v-else-if="run.questions.length">
        <ul class="space-y-1">
          <li v-for="q in run.questions" :key="q" class="text-muted">{{ q }}</li>
        </ul>
        <textarea
          v-model="run.answers" rows="3"
          placeholder="Answer what matters, skip the rest. This goes to the planner with the request."
          class="w-full rounded bg-surface2 px-2 py-2 outline-none"
        ></textarea>
      </template>
      <p v-else-if="run.clarified" class="text-muted">The request is specific enough to run as is.</p>

      <details class="rounded border border-edge">
        <summary class="cursor-pointer list-none px-2 py-1.5 text-xs uppercase tracking-wide text-muted [&::-webkit-details-marker]:hidden">Models &amp; depth</summary>
        <div class="space-y-2 border-t border-edge p-2">
          <div v-for="f in [
            { key: 'research_search_model', label: 'Search' },
            { key: 'research_note_model', label: 'Note-taking (most of the tokens)' },
            { key: 'research_report_model', label: 'Plan & report' },
          ]" :key="f.key">
            <label class="mb-1 flex items-center gap-1 text-xs text-muted">
              {{ f.label }}
              <button v-if="overridden(f.key)" class="text-indigo-500" title="Back to the global default" @click="reset(f.key)"><RotateCcw :size="11" /></button>
            </label>
            <ModelSelect :model-value="eff(f.key)" class="w-full rounded bg-surface2 px-2 py-1 text-xs" @update:model-value="setOv(f.key, $event)" />
          </div>
          <div>
            <label class="mb-1 flex items-center gap-1 text-xs text-muted">
              Sources per subquestion
              <button v-if="overridden('research_depth')" class="text-indigo-500" title="Back to the global default" @click="reset('research_depth')"><RotateCcw :size="11" /></button>
            </label>
            <input type="number" min="1" max="12" :value="eff('research_depth')" class="w-full rounded bg-surface2 px-2 py-1 text-xs" @input="setOv('research_depth', Number($event.target.value))" />
          </div>
        </div>
      </details>

      <button
        class="flex w-full items-center justify-center gap-2 rounded bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        :disabled="busy !== ''"
        @click="start"
      >
        <Play :size="14" /> Start research
      </button>
    </div>

    <!-- Plan and source trace, live while gathering and kept as the audit trail -->
    <CollapsibleRoot v-if="subquestions.length" v-model:open="traceOpen" class="mt-2">
      <CollapsibleTrigger class="flex w-full items-center gap-1 text-xs uppercase tracking-wide text-muted hover:text-base">
        <ChevronRight :size="12" class="transition-transform" :class="traceOpen && 'rotate-90'" />
        {{ subquestions.length }} subquestions · {{ read }} of {{ sources.length }} sources read
      </CollapsibleTrigger>
      <CollapsibleContent class="mt-1 space-y-2 border-l-2 border-indigo-500/40 pl-2">
        <div v-for="(q, i) in subquestions" :key="q" class="flex gap-2 text-xs">
          <span class="shrink-0 text-muted">q{{ i + 1 }}</span>
          <span class="min-w-0 flex-1">{{ q }}</span>
        </div>
        <div v-if="sources.length" class="max-h-48 space-y-0.5 overflow-y-auto">
          <p v-for="(s, i) in sources" :key="i" class="truncate text-xs" :class="s.error ? 'text-muted line-through' : 'text-muted'" :title="s.error || s.url">
            {{ s.url || s.error }}
          </p>
        </div>
      </CollapsibleContent>
    </CollapsibleRoot>

    <!-- The finished report; the same text lives in the doc store and stays attached to this conversation -->
    <CollapsibleRoot v-if="reportText" v-model:open="reportOpen" class="mt-2">
      <CollapsibleTrigger class="flex w-full items-center gap-1 text-xs uppercase tracking-wide text-muted hover:text-base">
        <ChevronRight :size="12" class="transition-transform" :class="reportOpen && 'rotate-90'" />
        Report · {{ (reportText.length / 1000).toFixed(1) }}k chars
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div class="md mt-1 max-h-[32rem] overflow-y-auto rounded border border-edge p-3 [overflow-wrap:anywhere]" v-html="renderMarkdown(reportText)"></div>
      </CollapsibleContent>
    </CollapsibleRoot>
    <p v-if="reportDoc" class="mt-1 text-xs text-muted">Attached to this conversation as "{{ reportDoc.name }}" (Context editor to detach).</p>

    <p v-if="error" class="mt-2 text-xs text-red-500">{{ error }}</p>
    <button
      v-if="run.status === 'error' || run.status === 'cancelled'"
      class="mt-2 flex items-center gap-1.5 rounded bg-surface2 px-2.5 py-1.5 text-xs hover:opacity-80"
      @click="start"
    >
      <Play :size="12" /> Run again
    </button>
  </div>
  <!-- The run record is gone (imported conversation without its runs, or a deleted run); the turn stays honest about it. -->
  <div v-else class="max-w-2xl rounded-lg border border-edge bg-surface px-4 py-3 text-xs text-muted">
    <Telescope :size="12" class="mr-1 inline" /> Research turn without its run record.
    <template v-if="reportDoc">The report survives as "{{ reportDoc.name }}".</template>
  </div>
</template>
