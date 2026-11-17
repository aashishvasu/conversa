// Run: node src/selfchecks/versionchange.selfcheck.js.
import 'fake-indexeddb/auto'
import assert from 'node:assert'
import { db } from '../state/db.js'
import { onVersionChange } from '../state/reload.js'
import { setLoaded } from '../state/persistence.js'

let reloads = 0
globalThis.location = { reload: () => { reloads++ } }

await db.open()
setLoaded(true)

assert.ok(
  db.on('versionchange').subscribers.includes(onVersionChange),
  'the versionchange handler is installed on the Dexie instance',
)

const result = db.on('versionchange').fire({ newVersion: 2, oldVersion: 1 })
assert.equal(result, false, 'the versionchange listener returns false, overriding Dexie\'s default close')
assert.equal(db.isOpen(), true, 'the connection is not surrendered when versionchange fires, so pending writes can still flush')

await new Promise((resolve) => setTimeout(resolve, 30))
assert.equal(reloads, 1, 'versionchange schedules exactly one reload, after the flush')

console.log('versionchange.selfcheck: ok')