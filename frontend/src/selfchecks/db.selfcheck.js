// Run: node src/selfchecks/db.selfcheck.js.

import 'fake-indexeddb/auto'
import assert from 'node:assert'
import { db, SCHEMA_VERSION } from '../state/db.js'

const expectedTables = ['conversations', 'messages', 'workspaces', 'docs', 'images', 'runs', 'runEvents', 'usage', 'meta']

await db.open()
assert.equal(db.isOpen(), true, 'database opens under fake-indexeddb')
assert.equal(db.verno, SCHEMA_VERSION, 'SCHEMA_VERSION matches the opened Dexie version')
for (const table of expectedTables) {
  assert.ok(db.table(table), `table ${table} exists on the opened instance`)
}
console.log('db.selfcheck: ok')
