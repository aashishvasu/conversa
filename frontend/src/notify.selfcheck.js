// Run: node src/notify.selfcheck.js.
import assert from 'node:assert'
import { dismiss, notifications, notify } from './notify.js'

const first = notify({ key: 'test', text: 'First' })
const second = notify({ key: 'test', text: 'Second' })
assert.equal(notifications.value.length, 1, 'dedupes by key')
assert.equal(notifications.value[0].text, 'Second', 'keeps the latest message')
assert.equal(notifications.value[0].count, 2, 'counts repeated notifications')
assert.notEqual(first.id, second.id, 'reopens the toast')
dismiss('test')
assert.equal(notifications.value.length, 0, 'dismisses by key')

console.log('notify selfcheck OK')
