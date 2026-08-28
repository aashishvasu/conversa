// Run: node src/selfchecks/importers.selfcheck.js.
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { convertImport } from '../state/importers.js'

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)))
const chats = fixture('nextchat-chats.json')
const models = chats['chat-next-web-store'].sessions.map((session) => session.mask.modelConfig.model)
const converted = convertImport(chats, models)

assert.equal(converted.report.conversations, 7, 'skips the empty session while importing each populated model')
assert.equal(converted.report.templates, 0, 'chat fixture has no standalone masks')
assert.equal(converted.data.conversations.length, 7)
assert.ok(converted.data.conversations.every((convo) => convo.settings.model), 'keeps a model only when the deployment lists it')
assert.ok(converted.data.conversations.every((convo) => convo.messages[0].role === 'system'), 'creates conversa system turn')
assert.ok(converted.data.conversations.every((convo) => convo.messages.slice(1).every((message) => ['user', 'assistant'].includes(message.role))), 'converts chat turns')
assert.equal(converted.data.conversations[0].messages.at(-1).createdAt, new Date(2025, 7, 16, 16, 2, 3).getTime(), 'infers DMY dates instead of native MDY parsing')

const edges = fixture('nextchat-edges.json')
const edgeResult = convertImport(edges)
assert.ok(edgeResult.report.sessionsSkipped > 0, 'skips empty sessions')
assert.ok(edgeResult.report.messagesSkipped > 0, 'skips partial streaming messages')
assert.ok(edgeResult.report.toolsDropped > 0, 'counts dropped tools')
assert.ok(edgeResult.data.conversations.some((convo) => convo.memoryCount > convo.messages.filter((message) => message.role !== 'system').length), 'preserves a memory index beyond current history')
assert.deepEqual([...new Set(edgeResult.data.conversations.flatMap((convo) => convo.messages.filter((message) => message.pinned).map((message) => message.role)))].sort(), ['assistant', 'user'], 'pins mask examples')

const mask = fixture('nextchat-mask.json')
const maskResult = convertImport(mask)
assert.equal(maskResult.report.conversations, 0)
assert.equal(maskResult.report.templates, 1, 'imports standalone masks as templates')
assert.equal(maskResult.data.conversations[0].isTemplate, true)
assert.equal(convertImport({ conversations: [] }), null, 'leaves native exports to importData')
assert.equal(convertImport({ 'chat-next-web-store': {} }), null, 'leaves malformed files to native validation')

console.log('importers selfcheck OK')
