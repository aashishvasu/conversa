// Run: node src/selfchecks/persistence.selfcheck.js.
import 'fake-indexeddb/auto'
import assert from 'node:assert'
import { cp, rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { nextTick, reactive } from 'vue'
import { applyFrame, newDraft, settleMessage } from '../chat/turn.js'
import { set } from 'idb-keyval'
import { STORE_KEY } from '../state/persistence.js'
import { SNAPSHOT_VERSION } from '../state/snapshot.js'
import { conversations, deleteConversation, exportData, initStore, persistNow, restoreData } from '../state/store.js'
import { setDownloadExport, storageFailure } from '../state/persistence.js'
import { dismiss, notifications } from '../utils/notify.js'

function convo(id, title, createdAt) {
  return {
    id, title, isTemplate: false, scanAssistant: false, workspaceId: null, docIds: [],
    mode: 'chat', settings: {}, cards: [], cardOverrides: {}, memory: '', memoryCount: 0, usage: null,
    messages: [{ id: `${id}-m0`, role: 'system', content: `seed-${id}`, createdAt }],
    createdAt, updatedAt: createdAt,
  }
}

function byId(id) {
  return conversations.value.find((c) => c.id === id)
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

// --- Migration preserves a legacy single-array archive ---
await set(STORE_KEY, [convo('b', 'Bravo', 200), convo('a', 'Alpha', 300), convo('c', 'Charlie', 100)])
await initStore()
await initStore()
assert.deepEqual(conversations.value.map((c) => c.id), ['b', 'a', 'c'], 'a legacy archive loads in its stored order, not a createdAt sort')
assert.equal(byId('b').title, 'Bravo', 'a migrated conversation keeps its title')
assert.equal(byId('b').messages[0].content, 'seed-b', 'a migrated conversation keeps its messages')

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

// --- Delete removes ---
deleteConversation('c')
await saveAndReload()
assert.deepEqual(conversations.value.map((c) => c.id), ['b', 'a'], 'a deleted conversation is gone after reload and the survivors keep their order')

// --- Migration is idempotent and the legacy seed cannot resurface ---
byId('b').title = 'Bravo-edited'
await saveAndReload()
await initStore()
assert.deepEqual(conversations.value.map((c) => c.id), ['b', 'a'], 'repeated loads over migrated storage lose nothing')
assert.equal(byId('b').title, 'Bravo-edited', 'an edit made after migration is not rolled back by a later load')

// --- Export round trip ---
assert.equal(SNAPSHOT_VERSION, 5, 'the snapshot contract version is unchanged')
const snapshot = exportData()
assert.equal(snapshot.version, SNAPSHOT_VERSION, 'a full export is versioned')
assert.deepEqual(snapshot.conversations.map((c) => c.id), ['b', 'a'], 'the export carries the library')
await restoreData(snapshot)
assert.deepEqual(conversations.value.map((c) => c.id), ['b', 'a'], 'restore accepts the export shape')
assert.equal(byId('b').title, 'Bravo-edited', 'restore keeps content')

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

// --- A record missing from the order list still loads ---
const { CONVO_KEY_PREFIX } = await import('../state/persistence.js')
await set(`${CONVO_KEY_PREFIX}z`, convo('z', 'Zulu', 999))
await set(`${CONVO_KEY_PREFIX}y`, convo('y', 'Yankee', 888))
await initStore()
assert.deepEqual(conversations.value.map((c) => c.id), ['z', 'y', 'b', 'a'], 'conversations absent from the order key are prepended, newest first')

// --- A stale tab's 404 reattach does not destroy a settled reply ---
const live = convo('live1', 'Live', 1500)
live.messages.push({ id: 'live1-m1', role: 'assistant', content: 'STALE-PARTIAL', turnId: 'turn-live1', createdAt: 1501 })
await set(`${CONVO_KEY_PREFIX}live1`, live)
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
console.log('persistence selfcheck OK')
