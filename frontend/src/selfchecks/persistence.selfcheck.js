// Run: node src/selfchecks/persistence.selfcheck.js.
import 'fake-indexeddb/auto'
import assert from 'node:assert'
import { cp, rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { nextTick, reactive } from 'vue'
import { applyFrame, newDraft, settleMessage } from '../chat/turn.js'
import { db } from '../state/db.js'
import { ensureLoaded, plainCopy, setDownloadExport, state, storageFailure } from '../state/persistence.js'
import { conversations, deleteConversation, initStore, persistNow } from '../state/store.js'
import { deleteDoc, gcImages, updateDocText } from '../state/docs.js'
import { deleteWorkspace } from '../state/workspaces.js'
import { addConvoUsage } from '../state/usage.js'
import { dismiss, notifications } from '../utils/notify.js'
function convoRow(id, title, createdAt, messageIds = []) {
  return {
    id, title, isTemplate: false, scanAssistant: false, workspaceId: null, docIds: [],
    mode: 'chat', settings: {}, cards: [], cardOverrides: {}, memory: '', memoryCount: 0, usage: null,
    createdAt, messageIds,
  }
}
function msgRow(id, convoId, role, content, createdAt, extra = {}) {
  return { id, convoId, role, content, createdAt, ...extra }
}
function byId(id) {
  return conversations.value.find((c) => c.id === id)
}
async function clearDb() {
  await db.transaction('rw', ['conversations', 'messages', 'workspaces', 'docs', 'runs', 'meta', 'images', 'usage'], async () => {
    await db.conversations.clear()
    await db.messages.clear()
    await db.workspaces.clear()
    await db.docs.clear()
    await db.runs.clear()
    await db.meta.clear()
    await db.images.clear()
    await db.usage.clear()
  })
}
// Stands in for the browser document and window event target from the first initStore on, so the teardown flush wiring registers against something the test can dispatch real events to.
const fakeDocument = new EventTarget()
fakeDocument.visibilityState = 'visible'
fakeDocument.documentElement = {}
globalThis.document = fakeDocument
const globalEvents = new EventTarget()
globalThis.addEventListener = globalEvents.addEventListener.bind(globalEvents)
globalThis.removeEventListener = globalEvents.removeEventListener.bind(globalEvents)
globalThis.dispatchEvent = globalEvents.dispatchEvent.bind(globalEvents)
function afterDebounceWindow() {
  return new Promise((resolve) => setTimeout(resolve, 50))
}
async function saveAndReload() {
  await nextTick()
  assert.equal(await persistNow(), true, 'a save against working storage reports success')
  await initStore()
}
// --- A summary conversation has no messages field, and the boot-loaded one has its messages ---
await clearDb()
await db.conversations.bulkPut([convoRow('a', 'Alpha', 300, ['a-m0']), convoRow('b', 'Bravo', 200, ['b-m0']), convoRow('c', 'Charlie', 100, ['c-m0'])])
await db.messages.bulkPut([
  msgRow('a-m0', 'a', 'system', 'seed-a', 0),
  msgRow('b-m0', 'b', 'system', 'seed-b', 0),
  msgRow('c-m0', 'c', 'system', 'seed-c', 0),
])
await initStore()
assert.deepEqual(conversations.value.map((c) => c.id), ['a', 'b', 'c'], 'rows load newest-created first')
assert.ok(!Object.hasOwn(byId('b'), 'messages'), 'a summary conversation has no messages field')
assert.ok(!Object.hasOwn(byId('c'), 'messages'), 'every unloaded conversation stays a summary')
assert.ok(Array.isArray(byId('a').messages), 'the boot-loaded first conversation is loaded')
assert.equal(byId('a').messages[0].content, 'seed-a', 'the first conversation loads its messages')
// --- ensureLoaded yields the same messages a full read would, and recovers strays by createdAt ---
await db.conversations.bulkPut([convoRow('x', 'Xray', 50, ['x1', 'x2'])])
await db.messages.bulkPut([
  msgRow('x1', 'x', 'user', 'ONE', 10),
  msgRow('x3', 'x', 'user', 'STRAY-SENTINEL', 15),
  msgRow('x2', 'x', 'user', 'TWO', 20),
])
await initStore()
await ensureLoaded(byId('x'))
assert.deepEqual(byId('x').messages.map((m) => m.id), ['x1', 'x2', 'x3'], 'messages order by messageIds, then strays by createdAt')
assert.equal(byId('x').messages[2].content, 'STRAY-SENTINEL', 'a stray message missing from messageIds is recovered and placed by createdAt')
const fullX = await db.messages.where('convoId').equals('x').toArray()
assert.equal(byId('x').messages.length, fullX.length, 'ensureLoaded yields the same messages a full read would')
// --- Reload fidelity ---
byId('a').title = 'Alpha-edited'
byId('a').messages.push({ id: 'a-m1', role: 'user', content: 'SENTINEL-RELOAD', createdAt: Date.now() })
await saveAndReload()
assert.equal(byId('a').title, 'Alpha-edited', 'an edited title survives a reload')
assert.ok(byId('a').messages.some((m) => m.content === 'SENTINEL-RELOAD'), 'a pushed message survives a reload')
// --- A turn that ran a tool saves and reloads ---
// The draft is reactive, as in the live coordinator, so its artifacts reach storage through the same copy the stream uses.
const toolMessage = { id: 'a-tool', role: 'assistant', content: '', turnId: 'turn-a-tool', createdAt: 400 }
byId('a').messages.push(toolMessage)
const toolDraft = reactive(newDraft())
applyFrame(toolDraft, { text: 'TOOL-REPLY' })
applyFrame(toolDraft, { artifact: { tool: 'web_search', output: { hits: 2 } } })
applyFrame(toolDraft, { done: true })
settleMessage(toolMessage, toolDraft, 'done')
await saveAndReload()
const reloadedTool = byId('a').messages.find((m) => m.id === 'a-tool')
assert.equal(reloadedTool?.content, 'TOOL-REPLY', 'a reply from a turn that ran a tool survives a reload')
assert.equal(reloadedTool?.artifacts?.[0]?.tool, 'web_search', 'a tool artifact survives a reload')
// --- A reactive value nested inside a message saves and reloads ---
// plainCopy unwraps only plain containers and leaves proxies out, so a proxy stored below the message surface must still copy as plain data.
byId('a').messages.push({ id: 'a-deep', role: 'user', content: 'DEEP-SENTINEL', createdAt: 500, meta: reactive({ note: 'DEEP-NOTE' }) })
await saveAndReload()
assert.equal(byId('a').messages.find((m) => m.id === 'a-deep')?.meta?.note, 'DEEP-NOTE', 'a reactive value nested below the message survives a reload')
// --- A checkpoint writes exactly one message row ---
let rowPuts = 0
const origBulkPut = db.messages.bulkPut
db.messages.bulkPut = async (rows) => {
  rowPuts += rows.length
  return origBulkPut.call(db.messages, rows)
}
try {
  byId('a').messages.find((m) => m.id === 'a-m1').content = 'CHECKPOINT-SENTINEL'
  await nextTick()
  await persistNow()
  assert.equal(rowPuts, 1, 'a 2 s checkpoint writes exactly one message row')
} finally {
  db.messages.bulkPut = origBulkPut
}
// --- A failed transaction leaves no partial flush, and a later retry succeeds ---
const cleanMsgs = byId('a').messages
const clean = cleanMsgs.find((m) => m.id === 'a-m0')
const poison = cleanMsgs.find((m) => m.id === 'a-deep')
clean.content = 'ROLLBACK-CLEAN-SENTINEL'
poison.__poison = () => {}
await nextTick()
assert.equal(await persistNow(), false, 'a flush that hits an uncloneable row reports failure')
const afterFail = await db.messages.where('convoId').equals('a').toArray()
assert.ok(!afterFail.some((m) => m.content === 'ROLLBACK-CLEAN-SENTINEL'), 'a failed transaction leaves no partial flush')
delete poison.__poison
await nextTick()
assert.equal(await persistNow(), true, 'the same flush succeeds once the poison is removed')
const afterRetry = await db.messages.where('convoId').equals('a').toArray()
assert.ok(afterRetry.some((m) => m.content === 'ROLLBACK-CLEAN-SENTINEL'), 'the clean edit lands once the transaction succeeds')
// --- Delete removes the row and its message rows ---
deleteConversation('c')
await saveAndReload()
assert.deepEqual(conversations.value.map((c) => c.id), ['a', 'b', 'x'], 'a deleted conversation is gone after reload and the survivors load newest-created first')
assert.equal((await db.messages.where('convoId').equals('c').toArray()).length, 0, 'deleting a conversation removes its message rows')
// --- A teardown flush persists an edit made inside the debounce window ---
// The wait stays under the save debounce, so only a teardown-triggered flush can have written.
byId('b').title = 'Bravo-teardown'
globalThis.dispatchEvent(new Event('pagehide'))
await afterDebounceWindow()
await initStore()
assert.equal(byId('b').title, 'Bravo-teardown', 'an edit made inside the debounce window reaches storage when the page hides')
byId('a').title = 'Alpha-hidden'
fakeDocument.visibilityState = 'hidden'
fakeDocument.dispatchEvent(new Event('visibilitychange'))
await afterDebounceWindow()
await initStore()
assert.equal(byId('a').title, 'Alpha-hidden', 'an edit made inside the debounce window reaches storage when the tab goes hidden')
fakeDocument.visibilityState = 'visible'
// --- Independent conversations do not interfere across tabs ---
// A second module graph over the same fake IndexedDB is a second browser tab: its own memory, one shared storage.
await initStore()
const srcDir = fileURLToPath(new URL('..', import.meta.url))
const tmpDir = fileURLToPath(new URL('../../node_modules/.tmp-persistence-selfcheck', import.meta.url))
await rm(tmpDir, { recursive: true, force: true })
await cp(srcDir, tmpDir, { recursive: true })
const tab2 = await import(pathToFileURL(path.join(tmpDir, 'state', 'store.js')).href)
await tab2.initStore()
tab2.conversations.value.find((c) => c.id === 'b').title = 'Bravo-tab2'
await nextTick()
await tab2.persistNow()
// Tab 1 loaded before tab 2 saved, so its copy of b is stale.
byId('a').title = 'Alpha-tab1'
await nextTick()
await persistNow()
await initStore()
assert.equal(byId('a').title, 'Alpha-tab1', "tab 1's edit to conversation a survives")
assert.equal(byId('b').title, 'Bravo-tab2', "tab 2's edit to conversation b survives tab 1's later save over a stale copy")
await rm(tmpDir, { recursive: true, force: true })
// --- Conversations load newest-created first from their createdAt index, not table write order ---
await clearDb()
await db.conversations.bulkPut([convoRow('early', 'Early', 100), convoRow('late', 'Late', 999)])
await initStore()
assert.deepEqual(conversations.value.map((c) => c.id), ['late', 'early'], 'conversations load in createdAt-descending order, so the later-created one leads')
// --- A stale tab's 404 reattach does not destroy a settled reply ---
await clearDb()
await db.conversations.bulkPut([convoRow('live1', 'Live', 1500, ['live1-m1'])])
await db.messages.bulkPut([msgRow('live1-m1', 'live1', 'assistant', 'STALE-PARTIAL', 1501, { turnId: 'turn-live1' })])
await initStore()
const tmpDir2 = fileURLToPath(new URL('../../node_modules/.tmp-persistence-selfcheck-stale', import.meta.url))
await rm(tmpDir2, { recursive: true, force: true })
await cp(srcDir, tmpDir2, { recursive: true })
const staleTab = await import(pathToFileURL(path.join(tmpDir2, 'state', 'store.js')).href)
await staleTab.initStore()
const staleConvo = staleTab.conversations.value.find((c) => c.id === 'live1')
const staleMessage = staleConvo.messages.find((m) => m.id === 'live1-m1')
// The first tab finishes the turn: the complete reply lands in storage and the turnId is released.
const settledMessage = byId('live1').messages.find((m) => m.id === 'live1-m1')
settledMessage.content = 'COMPLETE-SENTINEL-8'
delete settledMessage.turnId
await saveAndReload()
// The stale tab, still holding the turnId, reattaches into a 404.
globalThis.localStorage = { getItem: () => 'token', removeItem: () => {} }
Object.defineProperty(globalThis, 'navigator', { value: {}, configurable: true })
globalThis.fetch = async (_url, options = {}) => {
  if (options.method === 'DELETE') return new Response(null, { status: 204 })
  return new Response(JSON.stringify({ detail: { code: 'no_such_turn', message: 'no such turn' } }), { status: 404, headers: { 'Content-Type': 'application/json' } })
}
const staleCoordinator = await import(pathToFileURL(path.join(tmpDir2, 'chat', 'coordinator.js')).href)
await staleCoordinator.attachTurn(staleConvo, staleMessage)
assert.equal(staleMessage.content, 'COMPLETE-SENTINEL-8', 'the stale tab adopts the settled reply instead of keeping its partial text')
assert.ok(!Object.hasOwn(staleMessage, 'turnId'), 'the stale tab releases the turn it no longer owns')
await initStore()
assert.equal(byId('live1').messages.find((m) => m.id === 'live1-m1').content, 'COMPLETE-SENTINEL-8', "the settled reply survives the stale tab's 404 in storage")
await rm(tmpDir2, { recursive: true, force: true })
// --- The storage banner's backup action runs the export with no arguments ---
// The notification is rendered as a button, so the action receives the click event; the export must not treat it as a conversation id.
let exportArgs = null
setDownloadExport((...args) => { exportArgs = args })
storageFailure(new Error('storage down'))
const banner = notifications.value.find((n) => n.key === 'storage')
banner.action.fn({ type: 'click' })
assert.ok(exportArgs && exportArgs.length === 0, 'the backup action exports the full archive when a click event reaches it')
dismiss('storage')
// --- plainCopy makes a proxy-laden value acceptable to Dexie while a function still throws ---
const proxyLaden = reactive({
  id: 'px', convoId: 'zz', content: 'x',
  extra: { date: new Date('2020-01-02T00:00:00Z'), nan: NaN, inf: Infinity, zero: 0, empty: '', map: new Map([['k', 1]]), nested: reactive({ q: 9 }) },
  arr: [{ deep: reactive({ v: 1 }) }],
})
await db.messages.put(plainCopy(proxyLaden))
const stored = await db.messages.get('px')
assert.ok(stored.extra.date instanceof Date, 'a Date survives plainCopy and the Dexie write')
assert.ok(Number.isNaN(stored.extra.nan), 'NaN survives plainCopy and the Dexie write')
assert.equal(stored.extra.inf, Infinity, 'Infinity survives plainCopy and the Dexie write')
assert.equal(stored.extra.zero, 0, '0 survives plainCopy and the Dexie write')
assert.equal(stored.extra.empty, '', 'the empty string survives plainCopy and the Dexie write')
assert.ok(stored.extra.map instanceof Map && stored.extra.map.get('k') === 1, 'a Map survives plainCopy and the Dexie write')
assert.deepEqual(stored.extra.nested, { q: 9 }, 'a nested proxy unwraps through plainCopy')
assert.deepEqual(stored.arr, [{ deep: { v: 1 } }], 'a nested reactive array unwraps through plainCopy')
await assert.rejects(db.messages.put(plainCopy({ id: 'poison-fn', convoId: 'zzz', content: () => {} })), (e) => e.name === 'DataCloneError', 'a function in a row is refused loudly by the write instead of silently dropped')
// --- gcImages: an orphan image is reclaimed at boot over both a loaded and a summary conversation ---
await clearDb()
await db.conversations.bulkPut([convoRow('g1', 'Gamma', 400, ['g1-m0']), convoRow('g2', 'Gamma2', 300, ['g2-m0'])])
await db.messages.bulkPut([
  msgRow('g1-m0', 'g1', 'user', 'seed-g1', 1, { imageIds: ['img-kept'] }),
  msgRow('g2-m0', 'g2', 'user', 'seed-g2', 2, { imageIds: ['img-g2'] }),
])
await db.images.bulkPut([
  { id: 'img-kept', data: 'aGk=', media_type: 'image/png' },
  { id: 'img-orphan', data: 'aGk=', media_type: 'image/png' },
  { id: 'img-g2', data: 'aGk=', media_type: 'image/png' },
])
// The sweep runs while g2 is still a summary (no messages field), which the old flatMap implementation would throw on.
await initStore()
assert.ok(!state.images.some((i) => i.id === 'img-orphan'), 'an image no message references is reclaimed by the boot sweep')
assert.ok(state.images.some((i) => i.id === 'img-kept'), 'a referenced image survives the boot sweep')
assert.ok(!state.images.some((i) => i.id === 'img-g2'), 'lazy boot loads only the active conversation, so a summary-owned image is absent from memory')
await persistNow()
assert.equal(await db.images.get('img-orphan'), undefined, "the reclaimed image's row joins the flush")
assert.equal(await db.images.count(), 2, 'the table still holds every never-loaded conversation image after the sweep')
assert.ok(await db.images.get('img-g2'), 'an image kept by a summary conversation survives the boot sweep, row included')

// Deleting a conversation reclaims the images its summary rows referenced, rows and all.
await deleteConversation('g2')
await nextTick()
await persistNow()
assert.equal(await db.images.get('img-g2'), undefined, 'deleting a conversation reclaims its images')
assert.equal((await db.messages.where('convoId').equals('g2').toArray()).length, 0, 'its message rows go with it')
assert.ok(state.images.some((i) => i.id === 'img-kept'), 'unrelated images survive')

// Explicit ids skip the index, so a still-referenced loaded conversation is not swept.
await gcImages(['img-kept'])
assert.ok(state.images.some((i) => i.id === 'img-kept'), 'an id still referenced by a loaded conversation is not swept')

// --- conversation.updatedAt is maintained on the row, not recomputed from messages ---
await clearDb()
await db.conversations.bulkPut([convoRow('u1', 'Upsilon', 100, ['u1-m0'])])
await db.messages.bulkPut([msgRow('u1-m0', 'u1', 'system', 'seed-u1', 0)])
await initStore()
const u = byId('u1')
const pushMoment = Date.now()
u.messages.push({ id: 'u1-m1', role: 'user', content: 'SENTINEL-UPDATED', turnId: 'turn-u1', createdAt: Date.now() })
await nextTick()
assert.ok(u.updatedAt >= pushMoment, 'adding a message bumps updatedAt')
const beforeTitle = u.updatedAt
u.title = 'Upsilon-edited'
await nextTick()
assert.equal(u.updatedAt, beforeTitle, 'a trivial field edit does not bump updatedAt')
// settleMessage releases the turnId on the reactive proxy; a raw-object delete would bypass the trigger the watcher waits on.
const draft = u.messages.find((m) => m.id === 'u1-m1')
// The coarse Windows clock can pin two bumps to one tick, so the settle is forced across one before it releases the turnId.
await new Promise((r) => setTimeout(r, 25))
const settleMoment = Date.now()
delete draft.turnId
await nextTick()
const settled = u.updatedAt
assert.ok(settled >= settleMoment && settled > beforeTitle, 'settling a message bumps updatedAt')
await saveAndReload()
assert.ok(byId('u1').updatedAt >= settled, 'the maintained timestamp survives a reload')
// --- Per-row dirty tracking: editing one doc writes only that doc's row ---
await clearDb()
await db.conversations.bulkPut([convoRow('donly', 'DocsOnly', 1, [])])
await db.docs.bulkPut([
  { id: 'dd1', name: 'one.md', text: 'ONE', versions: [], createdAt: 1, updatedAt: 1 },
  { id: 'dd2', name: 'two.md', text: 'TWO', versions: [], createdAt: 2, updatedAt: 2 },
])
await initStore()
let docPuts = []
const docsBulkPut = db.docs.bulkPut
db.docs.bulkPut = async (rows) => { docPuts.push(...rows.map((d) => d.id)); return docsBulkPut.call(db.docs, rows) }
try {
  const one = state.docs.find((d) => d.id === 'dd1')
  updateDocText(one, 'ONE-EDITED')
  await nextTick()
  await persistNow()
} finally {
  db.docs.bulkPut = docsBulkPut
}
assert.equal(docPuts.join(','), 'dd1', 'editing one doc writes exactly that doc row')
assert.equal((await db.docs.get('dd1')).text, 'ONE-EDITED', 'the edited doc reaches storage')
assert.equal((await db.docs.get('dd2')).text, 'TWO', 'the other doc row is not rewritten')
// Deleting one doc removes only its row, and a doc dropped from the array without deleteDoc still leaves the table.
let docDeletes = []
const docsBulkDelete = db.docs.bulkDelete
db.docs.bulkDelete = async (ids) => { docDeletes.push(...ids); return docsBulkDelete.call(db.docs, ids) }
try {
  deleteDoc('dd1')
  await nextTick()
  await persistNow()
  state.docs = state.docs.filter((d) => d.id !== 'dd2')
  await nextTick()
  await persistNow()
} finally {
  db.docs.bulkDelete = docsBulkDelete
}
assert.equal(docDeletes.join(','), 'dd1,dd2', 'deleteDoc and an array-only drop each delete exactly their own row')
assert.equal(await db.docs.get('dd1'), undefined, 'the deleted doc row is gone')
assert.equal(await db.docs.get('dd2'), undefined, 'a doc dropped from the array without deleteDoc still leaves the table')
// --- Per-row dirty tracking: editing one workspace writes only that row ---
await clearDb()
await db.conversations.bulkPut([convoRow('wonly', 'Won', 1, [])])
await db.workspaces.bulkPut([
  { id: 'ws1', name: 'Alfa', messages: [], cards: [], docIds: [], createdAt: 1 },
  { id: 'ws2', name: 'Bravo', messages: [], cards: [], docIds: [], createdAt: 2 },
])
await initStore()
let wsPuts = []
const wsBulkPut = db.workspaces.bulkPut
db.workspaces.bulkPut = async (rows) => { wsPuts.push(...rows.map((w) => w.id)); return wsBulkPut.call(db.workspaces, rows) }
try {
  const one = state.workspaces.find((w) => w.id === 'ws1')
  one.name = 'Alfa-edited'
  one.messages.push({ id: 'sp', role: 'system', content: 'WS_SENTINEL', createdAt: 1 })
  one.cards.push({ id: 'c1', prompt: 'CARD' })
  one.docIds.push('d1')
  addConvoUsage(one, { calls: 1, input: 5 })
  await nextTick()
  await persistNow()
} finally {
  db.workspaces.bulkPut = wsBulkPut
}
assert.equal(wsPuts.join(','), 'ws1', 'mutating one workspace writes exactly that workspace row')
assert.equal((await db.workspaces.get('ws1')).name, 'Alfa-edited', 'the edited workspace reaches storage')
assert.equal((await db.workspaces.get('ws1')).usage.input, 5, 'a usage field mutation rides the same workspace row')
assert.equal((await db.workspaces.get('ws2')).name, 'Bravo', 'the other workspace row is not rewritten')
// Deleting one workspace removes only its row, and a drop from the array without deleteWorkspace still leaves the table.
let wsDeletes = []
const wsBulkDelete = db.workspaces.bulkDelete
db.workspaces.bulkDelete = async (ids) => { wsDeletes.push(...ids); return wsBulkDelete.call(db.workspaces, ids) }
try {
  deleteWorkspace('ws1')
  await nextTick()
  await persistNow()
  state.workspaces = state.workspaces.filter((w) => w.id !== 'ws2')
  await nextTick()
  await persistNow()
} finally {
  db.workspaces.bulkDelete = wsBulkDelete
}
assert.equal(wsDeletes.join(','), 'ws1,ws2', 'deleteWorkspace and an array-only drop each delete exactly their own row')
assert.equal(await db.workspaces.get('ws1'), undefined, 'the deleted workspace row is gone')
assert.equal(await db.workspaces.get('ws2'), undefined, 'a workspace dropped from the array without deleteWorkspace still leaves the table')
console.log('persistence selfcheck OK')
