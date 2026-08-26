import { get, set } from 'idb-keyval'
import { reactive } from 'vue'

// Client-side usage ledger: day buckets, one row per model per kind (chat, utility, research).
// USD arrives already computed server-side in the usage SSE frame; this module only accumulates it.

const USAGE_KEY = 'conversa_usage'

function blankRow() {
  return { calls: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0, usd: 0, unpriced: 0 }
}

// Shared accumulation: row.calls takes an explicit count so a single generation (always 1) and an
// already-aggregated fold (its own call count) use the same field summation.
// fields.unpriced is a boolean on a single generation's frame and a count on an aggregated fold;
// Number() normalizes both to how many of these calls had no published rate.
function addFields(row, calls, fields) {
  row.calls += calls
  row.input += fields.input || 0
  row.output += fields.output || 0
  row.cacheRead += fields.cache_read ?? fields.cacheRead ?? 0
  row.cacheWrite += fields.cache_write ?? fields.cacheWrite ?? 0
  row.usd += fields.usd || 0
  row.unpriced += Number(fields.unpriced) || 0
  return row
}

// Pure: folds one generation's usage frame into a days object and returns it.
// day defaults to today (UTC date, matching the stamp store.js already uses for research exports).
export function addUsage(days, kind, model, usage, day = new Date().toISOString().slice(0, 10)) {
  const models = (days[day] ??= {})
  const kinds = (models[model] ??= {})
  return addFields((kinds[kind] ??= blankRow()), 1, usage)
}

// Pure: folds an already-aggregated per-model row (a research run's Spend.as_dict().models entry)
// into the ledger, carrying its own call count rather than counting the fold as a single call.
export function foldUsage(days, kind, model, row, day = new Date().toISOString().slice(0, 10)) {
  const models = (days[day] ??= {})
  const kinds = (models[model] ??= {})
  return addFields((kinds[kind] ??= blankRow()), row.calls || 0, row)
}

// Pure: totals ledger rows by model and kind inside an inclusive ISO-date range. Empty bounds mean all time.
export function usageRows(days, start = '', end = '') {
  const rows = new Map()
  for (const [day, models] of Object.entries(days)) {
    if ((start && day < start) || (end && day > end) || !models || typeof models !== 'object' || Array.isArray(models)) continue
    for (const [model, kinds] of Object.entries(models)) {
      if (!kinds || typeof kinds !== 'object' || Array.isArray(kinds)) continue
      for (const [kind, fields] of Object.entries(kinds)) {
        if (!fields || typeof fields !== 'object' || Array.isArray(fields)) continue
        const key = `${model}\0${kind}`
        const row = rows.get(key) || { model, kind, ...blankRow() }
        addFields(row, fields.calls ?? 0, fields)
        rows.set(key, row)
      }
    }
  }
  const kindOrder = ['chat', 'utility', 'research']
  return [...rows.values()].sort((a, b) => a.model.localeCompare(b.model) || kindOrder.indexOf(a.kind) - kindOrder.indexOf(b.kind))
}

// Running total for one conversation, updated by every caller that streams against it (chat and the
// utility callers in memory.js/titles.js/CardsPanel.vue): one number, what this conversation has cost.
export function addConvoUsage(convo, usage) {
  if (!usage) return
  convo.usage ??= blankRow()
  addFields(convo.usage, 1, usage)
}

// --- Stateful layer, persisted like store.js ------------------------------------------

const state = reactive({ days: {} })
let loaded = false

export async function initUsage() {
  state.days = (await get(USAGE_KEY)) || {}
  loaded = true
}

let saveTimer
function persist() {
  if (!loaded) return
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => set(USAGE_KEY, JSON.parse(JSON.stringify(state.days))).catch(() => {}), 400)
}

export function usageDays() {
  return state.days
}

// Snapshot restore: replace the ledger wholesale, matching restoreData's replace-all semantics.
export function replaceUsage(days) {
  state.days = days && typeof days === 'object' && !Array.isArray(days) ? days : {}
  persist()
}

// Record one generation's usage frame under a kind (chat, utility, research).
export function recordUsage(kind, usage) {
  if (!usage?.model) return
  addUsage(state.days, kind, usage.model, usage)
  persist()
}

// Fold a research run's per-model Spend breakdown into the ledger; call once per finished run.
export function foldRunUsage(models) {
  for (const [model, row] of Object.entries(models || {})) foldUsage(state.days, 'research', model, row)
  persist()
}
