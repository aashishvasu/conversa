<script setup>
import { Ban, Boxes, Menu, MessagesSquare, Play, RotateCcw } from '@lucide/vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { clarifyResearch, discardResearch, startResearch, streamResearch } from '../api.js'
import { renderMarkdown } from '../md.js'
import {
  applyResearch,
  currentRun,
  effectiveSettings,
  persistNow,
  RESEARCH_KEYS,
  sidebarOpen,
  workspaces,
} from '../store.js'
import ModelSelect from './ModelSelect.vue'

const run = currentRun

const settings = computed(() => effectiveSettings(run.value, RESEARCH_KEYS))
const eff = (k) => settings.value[k]
const overridden = (k) => run.value.settings[k] !== undefined
const setOv = (k, v) => (run.value.settings[k] = v)
const reset = (k) => delete run.value.settings[k]

const error = ref('')
const busy = ref('')
let abort = null

const running = computed(() => run.value?.status === 'running')
const questions = computed(() => run.value?.events?.find((e) => e.kind === 'plan')?.questions || [])
const sources = computed(() => run.value?.events?.filter((e) => e.kind === 'source') || [])
const read = computed(() => sources.value.filter((s) => !s.error).length)
const spend = computed(() => run.value?.spend || { calls: 0, input: 0, output: 0, usd: 0, unpriced: 0 })
const report = computed(() => run.value?.payload?.docs?.[0]?.text || '')
const perQuestion = computed(() => {
  const counts = new Map()
  for (const s of sources.value) {
    const c = counts.get(s.question) || { read: 0, failed: 0 }
    s.error ? c.failed++ : c.read++
    counts.set(s.question, c)
  }
  return counts
})

// The brief the run actually receives, with the clarifying exchange folded in.
// The planner reads this, which is the whole point of asking: scope arrives as text rather than as a guess.
function fullBrief() {
  const r = run.value
  const answers = (r.answers || '').trim()
  if (!r.questions?.length || !answers) return r.brief.trim()
  return `${r.brief.trim()}\n\nClarifications:\n${r.questions.map((q) => `Q: ${q}`).join('\n')}\n\nA: ${answers}`
}

async function ask() {
  const brief = run.value.brief.trim()
  if (!brief) return
  busy.value = 'clarify'
  error.value = ''
  try {
    run.value.questions = await clarifyResearch(brief, eff('research_report_model'))
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = ''
  }
}

async function start() {
  const brief = fullBrief()
  if (!brief) return
  busy.value = 'start'
  error.value = ''
  try {
    const { id } = await startResearch({
      brief,
      title: run.value.brief.trim(),
      depth: eff('research_depth'),
      models: {
        search: eff('research_search_model'),
        note: eff('research_note_model'),
        report: eff('research_report_model'),
      },
    })
    Object.assign(run.value, {
      serverId: id,
      status: 'running',
      phase: 'plan',
      events: [],
      payload: null,
      spend: null,
      title: run.value.brief.trim().slice(0, 60) || 'Research',
      updatedAt: Date.now(),
    })
    tail()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = ''
  }
}

// Reconnect from the last seq already stored, so reopening a run replays only what it missed.
// The loop matters: a stream ending while the run is still going means the connection dropped, and an idle proxy will do exactly that during a long phase.
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

function onEvent(data) {
  const r = run.value
  if (!r) return
  if (data.spend) r.spend = data.spend
  // A tick is a keep-alive with no seq, so it updates the counters and stays out of the replay position.
  if (data.kind === 'tick') {
    r.phase = data.phase
    return
  }
  if (data.kind === 'final') {
    Object.assign(r, { status: data.status, phase: data.phase, payload: data.payload, updatedAt: Date.now() })
    if (data.error) error.value = data.error
    persistNow()
    return
  }
  r.events.push(data)
  if (data.kind === 'phase') r.phase = data.phase
}

async function stop() {
  if (!run.value?.serverId) return
  try {
    await discardResearch(run.value.serverId)
  } catch (e) {
    error.value = e.message
  }
  tail() // re-arm, in case the stream this was meant to end had already dropped
}

const target = ref('')
async function save() {
  const existing = workspaces.value.find((w) => w.id === target.value)
  const w = applyResearch(run.value.payload, existing || null)
  run.value.workspaceId = w.id
  persistNow()
  // The browser now holds the only copy that matters, so the server can drop its own.
  // Best-effort: a failure here costs some server memory until the next run sweeps it, and nothing the user has.
  try {
    await discardResearch(run.value.serverId)
  } catch { /* the eviction sweep will get it */ }
}
const savedTo = computed(() => workspaces.value.find((w) => w.id === run.value?.workspaceId) || null)

// Switching runs in the sidebar drops the old stream and picks up the new one if it is live.
watch(
  () => run.value?.id,
  () => {
    error.value = ''
    abort?.abort()
    if (run.value?.status === 'running') tail()
  },
)
onMounted(() => {
  if (run.value?.status === 'running') tail()
})
onUnmounted(() => abort?.abort())
</script>

<template>
  <main v-if="run" class="flex min-w-0 flex-1 flex-col bg-app">
    <header class="flex items-center gap-2 border-b border-edge px-3 py-2">
      <button class="rounded p-1.5 hover:bg-surface2 md:hidden" title="Menu" @click="sidebarOpen = true"><Menu :size="16" /></button>
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-medium">{{ run.title }}</p>
        <p class="text-xs text-muted">
          {{ running ? run.phase || 'starting' : run.status }}
          <span v-if="spend.calls">
            · {{ spend.calls }} calls · {{ Math.round((spend.input + spend.output) / 1000) }}k tokens ·
            <span :title="spend.unpriced ? spend.unpriced + ' call(s) used a model with no published rate, charged here at the top tier' : 'estimated from published rates'">
              {{ spend.unpriced ? '>' : '' }}${{ spend.usd.toFixed(2) }}
            </span>
          </span>
        </p>
      </div>
      <button v-if="running" class="flex items-center gap-1.5 rounded bg-surface2 px-2.5 py-1.5 text-sm hover:text-red-500" @click="stop">
        <Ban :size="14" /> Stop
      </button>
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <div class="mx-auto grid max-w-5xl gap-4 p-4 md:grid-cols-2">
        <section class="min-w-0 space-y-3">
          <div>
            <label class="mb-1 block text-xs uppercase tracking-wide text-muted">Brief</label>
            <textarea
              v-model="run.brief" rows="4" :disabled="running"
              placeholder="What should this run find out?"
              class="w-full rounded bg-surface2 px-2 py-2 text-sm outline-none disabled:opacity-60"
            ></textarea>
          </div>

          <button
            class="flex w-full items-center justify-center gap-2 rounded bg-surface2 py-2 text-sm hover:opacity-80 disabled:opacity-50"
            :disabled="!run.brief.trim() || busy === 'clarify' || running"
            @click="ask"
          >
            <MessagesSquare :size="14" />
            {{ busy === 'clarify' ? 'Thinking…' : run.questions.length ? 'Ask again' : 'Ask me questions first' }}
          </button>

          <details v-if="run.questions.length" open class="rounded border border-edge">
            <summary class="cursor-pointer px-2 py-1.5 text-xs uppercase tracking-wide text-muted">
              Answer what matters, skip the rest
            </summary>
            <ul class="space-y-1 border-t border-edge p-2">
              <li v-for="q in run.questions" :key="q" class="text-sm text-muted">{{ q }}</li>
            </ul>
            <textarea
              v-model="run.answers" rows="4" :disabled="running"
              placeholder="Answer in your own words. This goes to the planner with the brief."
              class="w-full rounded-b bg-surface2 px-2 py-2 text-sm outline-none disabled:opacity-60"
            ></textarea>
          </details>

          <details class="rounded border border-edge">
            <summary class="cursor-pointer px-2 py-1.5 text-xs uppercase tracking-wide text-muted">
              Models &amp; depth for this run
            </summary>
            <div class="space-y-2 border-t border-edge p-2">
              <div v-for="f in [
                { key: 'research_search_model', label: 'Search' },
                { key: 'research_note_model', label: 'Note-taking (most of the tokens)' },
                { key: 'research_report_model', label: 'Plan &amp; report' },
              ]" :key="f.key">
                <label class="mb-1 flex items-center gap-1 text-xs text-muted">
                  <span v-html="f.label"></span>
                  <button v-if="overridden(f.key)" class="text-indigo-500" title="Back to the global default" @click="reset(f.key)"><RotateCcw :size="11" /></button>
                </label>
                <ModelSelect :model-value="eff(f.key)" class="w-full rounded bg-surface2 px-2 py-1 text-sm" @update:model-value="setOv(f.key, $event)" />
              </div>
              <div>
                <label class="mb-1 flex items-center gap-1 text-xs text-muted">
                  Sources per subquestion
                  <button v-if="overridden('research_depth')" class="text-indigo-500" title="Back to the global default" @click="reset('research_depth')"><RotateCcw :size="11" /></button>
                </label>
                <input type="number" min="1" max="12" :value="eff('research_depth')" class="w-full rounded bg-surface2 px-2 py-1 text-sm" @input="setOv('research_depth', Number($event.target.value))" />
              </div>
            </div>
          </details>

          <button
            class="flex w-full items-center justify-center gap-2 rounded bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            :disabled="!run.brief.trim() || running || busy === 'start'"
            @click="start"
          >
            <Play :size="14" /> {{ run.serverId ? 'Run again' : 'Start research' }}
          </button>

          <p v-if="error" class="text-xs text-red-500">{{ error }}</p>
        </section>

        <section class="min-w-0 space-y-3">
          <div v-if="questions.length" class="min-w-0 space-y-1 rounded border border-edge p-2">
            <p class="text-xs uppercase tracking-wide text-muted">Subquestions</p>
            <div v-for="(q, i) in questions" :key="q" class="flex gap-2 text-sm">
              <span class="shrink-0 text-muted">q{{ i + 1 }}</span>
              <span class="min-w-0 flex-1">{{ q }}</span>
              <span v-if="perQuestion.get(q)" class="shrink-0 text-xs text-muted">
                {{ perQuestion.get(q).read }}<span v-if="perQuestion.get(q).failed">/{{ perQuestion.get(q).read + perQuestion.get(q).failed }}</span>
              </span>
            </div>
          </div>

          <details v-if="sources.length" open class="rounded border border-edge">
            <summary class="cursor-pointer px-2 py-1.5 text-xs uppercase tracking-wide text-muted">
              {{ read }} of {{ sources.length }} sources read
            </summary>
            <div class="max-h-64 space-y-0.5 overflow-y-auto border-t border-edge p-2">
              <p v-for="(s, i) in sources" :key="i" class="truncate text-xs" :class="s.error ? 'text-muted line-through' : ''" :title="s.error || s.url">
                {{ s.url || s.error }}
              </p>
            </div>
          </details>

          <template v-if="run.payload">
            <div class="flex gap-2">
              <select v-model="target" class="min-w-0 flex-1 rounded bg-surface2 px-2 py-2 text-sm">
                <option value="">New workspace</option>
                <option v-for="w in workspaces" :key="w.id" :value="w.id">Add to {{ w.name }}</option>
              </select>
              <button class="flex shrink-0 items-center gap-2 rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-500" @click="save">
                <Boxes :size="14" /> Save
              </button>
            </div>
            <p v-if="savedTo" class="text-xs text-muted">
              Saved into workspace "{{ savedTo.name }}". Say q1, q2 and so on in a conversation there to pull in the notes.
            </p>
            <div class="rounded border border-edge">
              <p class="border-b border-edge px-2 py-1.5 text-xs uppercase tracking-wide text-muted">
                Report · {{ report.length }} chars · {{ run.payload.cards.length }} note cards
              </p>
              <div class="md max-h-[32rem] overflow-y-auto p-3 [overflow-wrap:anywhere]" v-html="renderMarkdown(report)"></div>
            </div>
          </template>
        </section>
      </div>
    </div>
  </main>
</template>
