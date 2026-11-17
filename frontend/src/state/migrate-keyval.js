import { db, SCHEMA_VERSION } from './db.js'

const KEYVAL_DB = 'keyval-store'
const KEYVAL_STORE = 'keyval'
const CONVO_KEY_PREFIX = 'conversa_convo:'
const WORKSPACES_KEY = 'conversa_workspaces'
const RUNS_KEY = 'conversa_runs'
const DOCS_KEY = 'conversa_docs'
const IMAGE_KEY_PREFIX = 'conversa_img:'
const GLOBAL_KEY = 'conversa_global'
const USAGE_KEY = 'conversa_usage'
const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])

const ZERO_COUNTS = { conversations: 0, messages: 0, workspaces: 0, docs: 0, images: 0, runs: 0, runEvents: 0, usage: 0 }

const requestResult = (request) => new Promise((resolve, reject) => {
  request.onsuccess = () => resolve(request.result)
  request.onerror = () => reject(request.error)
})

// Frozen copies of the boot fixups they mirror, because a migration reads shapes as they sit on old disks and must not follow later rewrites of the live modules.
function validImage(image) {
  return Boolean(image?.id && typeof image.data === 'string' && IMAGE_TYPES.has(image.media_type))
}

function hoistInlineDocs(workspaces, docs) {
  const have = new Set(docs.map((d) => d.id))
  for (const w of workspaces) {
    w.docIds ??= []
    for (const d of w.docs || []) {
      if (!d?.id) continue
      if (!have.has(d.id)) {
        docs.push({ id: d.id, name: d.name, text: d.text, createdAt: Date.now(), updatedAt: Date.now(), source: { kind: 'upload' }, versions: [] })
        have.add(d.id)
      }
      w.docIds.push(d.id)
    }
    delete w.docs
  }
}

function migrateWorkspacePrompts(workspaces) {
  for (const w of workspaces) {
    w.messages ??= w.systemPrompt?.trim() ? [{ id: crypto.randomUUID(), role: 'system', content: w.systemPrompt, createdAt: Date.now() }] : []
    delete w.systemPrompt
  }
}

function migrateRunShape(r) {
  if (!r || typeof r !== 'object') return null
  const next = { ...r, events: Array.isArray(r.events) ? r.events : [], checkpoint: r.checkpoint ?? null, retryFailed: r.retryFailed ?? false, spendLedgered: r.spendLedgered ?? false, isPreparing: false, preparationFailed: r.preparationFailed ?? false }
  const rawBrief = r.prepared?.brief
  if (rawBrief && typeof rawBrief === 'object') {
    const rawScope = Array.isArray(rawBrief.scope) ? rawBrief.scope : typeof rawBrief.scope === 'string' ? [rawBrief.scope] : []
    const rawConstraints = Array.isArray(rawBrief.constraints) ? rawBrief.constraints : typeof rawBrief.constraints === 'string' ? [rawBrief.constraints] : []
    const scope = rawScope.filter((s) => typeof s === 'string' && s.trim())
    const constraints = rawConstraints.filter((c) => typeof c === 'string' && c.trim())
    next.prepared = {
      ...r.prepared,
      brief: {
        ...rawBrief,
        objective: (rawBrief.objective || r.prepared?.goal || 'Research').trim() || 'Research',
        deliverable: (rawBrief.deliverable || rawBrief.objective || 'A sourced research brief').trim() || 'A sourced research brief',
        scope: scope.length ? scope : ['The requested subject'],
        constraints: constraints.length ? constraints : ['Use current public sources'],
        questions: Array.isArray(rawBrief.questions) ? rawBrief.questions : [],
      },
    }
  } else {
    const goal = (r.prepared?.goal || 'Research').trim() || 'Research'
    next.prepared = {
      brief: {
        objective: goal,
        deliverable: 'A sourced research brief',
        scope: ['The requested subject'],
        constraints: ['Use current public sources'],
        questions: Array.isArray(r.prepared?.questions) ? r.prepared.questions : [],
      },
      answers: {},
    }
  }
  next.answers = r.answers || next.prepared.answers || {}
  return next
}

function validRunShape(r) {
  const run = migrateRunShape(r)
  return Boolean(run?.id && run.convoId && run.input && run.prepared?.brief && run.settings)
}

function buildRows(records) {
  const conversations = []
  for (const [key, value] of records) {
    if (typeof key === 'string' && key.startsWith(CONVO_KEY_PREFIX) && value?.id) conversations.push(value)
  }
  for (const conversation of conversations) {
    for (const message of conversation.messages) if (!message.id) message.id = crypto.randomUUID()
  }
  const messageRows = conversations.flatMap((conversation) => conversation.messages.map((message) => ({ convoId: conversation.id, ...message })))
  const workspaces = records.get(WORKSPACES_KEY) || []
  const docs = records.get(DOCS_KEY) || []
  hoistInlineDocs(workspaces, docs)
  migrateWorkspacePrompts(workspaces)
  const runs = []
  const runEvents = []
  for (const raw of (records.get(RUNS_KEY) || []).map(migrateRunShape).filter(validRunShape)) {
    const run = { ...raw }
    const events = run.events
    delete run.events
    runs.push(run)
    events.forEach((event) => runEvents.push({ ...event, runId: raw.id }))
  }
  const images = []
  for (const [key, value] of records) {
    if (typeof key === 'string' && key.startsWith(IMAGE_KEY_PREFIX) && validImage(value)) images.push(value)
  }
  const usage = []
  for (const [day, models] of Object.entries(records.get(USAGE_KEY) || {})) {
    if (!models || typeof models !== 'object' || Array.isArray(models)) continue
    for (const [model, kinds] of Object.entries(models)) {
      if (!kinds || typeof kinds !== 'object' || Array.isArray(kinds)) continue
      for (const [kind, fields] of Object.entries(kinds)) {
        if (!fields || typeof fields !== 'object' || Array.isArray(fields)) continue
        usage.push({ day, model, kind, ...fields })
      }
    }
  }
  const conversationRows = conversations.map((conversation) => {
    const row = { ...conversation, messageIds: conversation.messages.map((message) => message.id) }
    delete row.messages
    // The row now carries the sidebar's last-activity stamp, which the messages array used to supply; derive it from the last message, keeping any value the record already had.
    const lastCreatedAt = conversation.messages.at(-1)?.createdAt
    if (lastCreatedAt) row.updatedAt = lastCreatedAt
    return row
  })
  return {
    conversationRows,
    messageRows,
    workspaces,
    docs,
    images,
    runs,
    runEvents,
    usage,
    global: records.get(GLOBAL_KEY),
  }
}

// Opening keyval-store without a version upgrades from 0 only when it does not exist, and aborting that upgrade rolls back creation, so a fresh install leaves no empty database behind.
// This works wherever databases() does not.
function openLegacyConnection() {
  return new Promise((resolve) => {
    const request = indexedDB.open(KEYVAL_DB)
    request.onupgradeneeded = (event) => event.target.transaction.abort()
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => resolve(null)
    request.onblocked = () => resolve(null)
  })
}

async function readLegacyRecords() {
  const connection = await openLegacyConnection()
  if (!connection) return null
  try {
    if (!connection.objectStoreNames.contains(KEYVAL_STORE)) return null
    const store = connection.transaction(KEYVAL_STORE, 'readonly').objectStore(KEYVAL_STORE)
    const [keys, values] = await Promise.all([requestResult(store.getAllKeys()), requestResult(store.getAll())])
    const records = new Map()
    for (let i = 0; i < keys.length; i++) records.set(keys[i], values[i])
    return records
  } finally {
    connection.close()
  }
}

// Best effort: a blocked delete (an old tab still holding the connection) is a leftover file, not a lost migration;
// the new tables are already committed and the next boot skips via meta.schema.
function deleteLegacyDatabase() {
  return new Promise((resolve) => {
    const request = indexedDB.deleteDatabase(KEYVAL_DB)
    request.onsuccess = () => resolve()
    request.onerror = () => resolve()
    request.onblocked = () => resolve()
  })
}

export async function migrateFromKeyval() {
  if (await db.meta.get('schema')) return { migrated: false, counts: { ...ZERO_COUNTS } }
  const records = await readLegacyRecords()
  if (!records) return { migrated: false, counts: { ...ZERO_COUNTS } }
  const built = buildRows(records)
  const counts = {
    conversations: built.conversationRows.length,
    messages: built.messageRows.length,
    workspaces: built.workspaces.length,
    docs: built.docs.length,
    images: built.images.length,
    runs: built.runs.length,
    runEvents: built.runEvents.length,
    usage: built.usage.length,
  }
  await db.transaction('rw', db.tables, async () => {
    await db.conversations.bulkPut(built.conversationRows)
    await db.messages.bulkPut(built.messageRows)
    await db.workspaces.bulkPut(built.workspaces)
    await db.docs.bulkPut(built.docs)
    await db.images.bulkPut(built.images)
    await db.runs.bulkPut(built.runs)
    await db.runEvents.bulkPut(built.runEvents)
    await db.usage.bulkPut(built.usage)
    const metaRows = []
    if (built.global) metaRows.push({ key: 'global', value: built.global })
    metaRows.push({ key: 'schema', value: SCHEMA_VERSION })
    await db.meta.bulkPut(metaRows)
    for (const [table, expected] of Object.entries(counts)) {
      const written = await db.table(table).count()
      if (written !== expected) throw new Error(`migrate-keyval: ${table} holds ${written} rows, expected ${expected}`)
    }
  })
  await deleteLegacyDatabase()
  return { migrated: true, counts }
}
