import { reactive } from 'vue'
import { db } from './db.js'
import { scheduleFlush } from './persistence.js'

// Rows are the persisted form: pending increments commit as deltas, so concurrent tabs accumulate instead of the last writer winning.

function blankRow() {
  return { calls: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0, usd: 0, unpriced: 0 }
}

// Shared accumulation: row.calls takes an explicit count so a streamed turn and an already-aggregated fold use the same field summation.
// fields.unpriced is a boolean on a single-call frame and a count on an aggregated fold;
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

// Day defaults to the same UTC stamp store.js already uses for research exports.
export function addUsage(days, kind, model, usage, day = new Date().toISOString().slice(0, 10)) {
  const models = (days[day] ??= {})
  const kinds = (models[model] ??= {})
  return addFields((kinds[kind] ??= blankRow()), usage.calls ?? 1, usage)
}

// An already-aggregated row carries its own call count, unlike the fixed +1 in addUsage.
export function foldUsage(days, kind, model, row, day = new Date().toISOString().slice(0, 10)) {
  const models = (days[day] ??= {})
  const kinds = (models[model] ??= {})
  return addFields((kinds[kind] ??= blankRow()), row.calls || 0, row)
}

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

// Kept current by both streaming call sites (the chat turn and every utilityCall) so neither can drift.
export function addConvoUsage(convo, usage) {
  if (!usage) return
  convo.usage ??= blankRow()
  addFields(convo.usage, usage.calls ?? 1, usage)
}

// --- Stateful layer, persisted like store.js ------------------------------------------

const state = reactive({ days: {} })

export function usageDays() {
  return state.days
}

const pendingDeltas = new Map()
let pendingReplace = null

function accumulate(day, model, kind, fields, calls) {
  const key = `${day}\0${model}\0${kind}`
  const row = pendingDeltas.get(key) || blankRow()
  addFields(row, calls, fields)
  pendingDeltas.set(key, row)
}

// Record a usage frame under a kind (chat, utility, research).
export function recordUsage(kind, usage) {
  if (!usage?.model) return
  const day = new Date().toISOString().slice(0, 10)
  addUsage(state.days, kind, usage.model, usage, day)
  accumulate(day, usage.model, kind, usage, usage.calls ?? 1)
  scheduleFlush()
}

// Deltas commit in the same flush transaction as the run row, so spend and run status cannot diverge.
export function foldRunUsage(models) {
  const day = new Date().toISOString().slice(0, 10)
  for (const [model, row] of Object.entries(models || {})) {
    foldUsage(state.days, 'research', model, row, day)
    accumulate(day, model, 'research', row, row.calls || 0)
  }
  scheduleFlush()
}

// Snapshot restore: replace the ledger wholesale, matching restoreData's replace-all semantics.
export function replaceUsage(days) {
  state.days = days && typeof days === 'object' && !Array.isArray(days) ? days : {}
  pendingDeltas.clear()
  pendingReplace = state.days
  scheduleFlush()
}

export function takeUsagePending() {
  const pending = { replace: pendingReplace, deltas: new Map(pendingDeltas) }
  pendingReplace = null
  pendingDeltas.clear()
  return pending
}
export function restoreUsagePending(pending) {
  if (pending.replace !== null) pendingReplace = pending.replace
  for (const [key, delta] of pending.deltas) {
    const existing = pendingDeltas.get(key)
    if (existing) addFields(existing, delta.calls, delta)
    else pendingDeltas.set(key, { ...delta })
  }
}

export async function commitUsage(pending) {
  if (pending.replace !== null) {
    await db.usage.clear()
    const rows = buildRows(pending.replace)
    if (rows.length) await db.usage.bulkPut(rows)
    return
  }
  for (const [key, delta] of pending.deltas) {
    const [day, model, kind] = key.split('\0')
    const row = (await db.usage.get([day, model, kind])) || { day, model, kind, ...blankRow() }
    addFields(row, delta.calls, delta)
    await db.usage.put(row)
  }
}

export async function initUsage() {
  state.days = rowsToDays(await db.usage.toArray())
  // Loading replaces the in-memory ledger wholesale, so marks accumulated before the load (folded into a days object that is now discarded) would double-count against the rows.
  pendingDeltas.clear()
  pendingReplace = null
}

function buildRows(days) {
  const rows = []
  for (const [day, models] of Object.entries(days || {})) {
    if (!models || typeof models !== 'object' || Array.isArray(models)) continue
    for (const [model, kinds] of Object.entries(models)) {
      if (!kinds || typeof kinds !== 'object' || Array.isArray(kinds)) continue
      for (const [kind, fields] of Object.entries(kinds)) {
        if (!fields || typeof fields !== 'object' || Array.isArray(fields)) continue
        rows.push({ day, model, kind, ...blankRow(), ...fields })
      }
    }
  }
  return rows
}

const rowsToDays = (rows) => {
  const days = {}
  for (const row of rows || []) {
    if (!row?.day || !row.model || !row.kind) continue
    const { day, model, kind, ...fields } = row
    const kinds = (days[day] ??= {})
    const byModel = (kinds[model] ??= {})
    byModel[kind] = { ...blankRow(), ...fields }
  }
  return days
}

// The ledger as a days-shaped object read straight from the rows; the caller flushes first so the rows reflect pending deltas.
export async function usageDaysFromTable() {
  return rowsToDays(await db.usage.toArray())
}

// A snapshot's days object folded into the rows an atomic restore writes.
export function usageRowsFromDays(days) {
  return buildRows(days)
}
