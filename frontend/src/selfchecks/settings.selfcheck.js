// Run: node src/selfchecks/settings.selfcheck.js.
// Covers the settings surface: key registration, the tool switch -> enabled_tools mapping, and the payload contract.
import assert from 'node:assert'
import { readFile } from 'node:fs/promises'
import { globalSettings } from '../state/store.js'
import { effectiveSettings, enabledTools, SETTING_KEYS, TOOL_FIELDS } from '../state/settings.js'

// Every tool switch is a registered setting, and the backend schema names are fixed.
assert.deepEqual(TOOL_FIELDS.map((f) => f.key), ['tool_web_search', 'tool_fetch_url', 'tool_datetime', 'tool_calculator', 'tool_random'])
assert.deepEqual(TOOL_FIELDS.map((f) => f.tool), ['search_web', 'fetch_url', 'datetime', 'calculator', 'random'])
for (const field of TOOL_FIELDS) assert.ok(SETTING_KEYS.includes(field.key), `${field.key} must be in SETTING_KEYS`)
assert.ok(SETTING_KEYS.includes('tools_enabled'), 'the master switch must be in SETTING_KEYS')

const allOn = {
  tools_enabled: true, tool_web_search: true, tool_fetch_url: true,
  tool_datetime: true, tool_calculator: true, tool_random: true,
}
assert.deepEqual(enabledTools(allOn), ['search_web', 'fetch_url', 'datetime', 'calculator', 'random'], 'all on sends every schema in field order')
assert.deepEqual(enabledTools({ ...allOn, tools_enabled: false }), [], 'master off sends nothing')
assert.deepEqual(enabledTools({ ...allOn, tool_fetch_url: false, tool_random: false }), ['search_web', 'datetime', 'calculator'], 'an off switch drops only its own schema')
assert.deepEqual(enabledTools({}), [], 'missing keys send nothing')
assert.deepEqual(enabledTools(null), [])

// Pure: the settings object is never mutated.
const frozen = { tools_enabled: true, tool_web_search: true, tool_calculator: true }
enabledTools(frozen)
assert.deepEqual(frozen, { tools_enabled: true, tool_web_search: true, tool_calculator: true })

// A conversation missing the keys inherits the global values; an explicit false override wins over a true global.
globalSettings.value = { ...allOn, tool_datetime: false }
const inherited = effectiveSettings({ settings: {} })
assert.equal(inherited.tool_web_search, true, 'missing conversation keys inherit the global value')
assert.equal(inherited.tool_datetime, false)
assert.deepEqual(enabledTools(inherited), ['search_web', 'fetch_url', 'calculator', 'random'])
const overridden = effectiveSettings({ settings: { tool_web_search: false, tools_enabled: true } })
assert.equal(overridden.tool_web_search, false, 'a false override is respected, not read as inherit')
assert.equal(overridden.tool_fetch_url, true, 'unset keys still inherit')
assert.deepEqual(enabledTools(overridden), ['fetch_url', 'calculator', 'random'])
// An old conversation snapshot without any tool keys rides on the server-seeded global defaults.
globalSettings.value = { model: 'm' }
assert.deepEqual(enabledTools(effectiveSettings({ settings: {} })), [], 'no tool keys anywhere sends nothing')

// Payload contract: the chat turn fixes its tool selection at assembly time; utility jobs stay tool-free.
const orchestration = await readFile(new URL('../research/orchestration.js', import.meta.url), 'utf8')
assert.ok(/enabled_tools: enabledTools\(settings\)/.test(orchestration), 'the chat payload carries enabledTools read once at assembly')
assert.ok(!/allow_tools/.test(orchestration), 'the legacy allow_tools flag is gone from chat sends')
const utility = await readFile(new URL('../jobs/utility.js', import.meta.url), 'utf8')
assert.ok(/enabled_tools: \[\]/.test(utility), 'utility jobs send an empty tool list')
assert.ok(!/allow_tools/.test(utility), 'the legacy allow_tools flag is gone from utility sends')

console.log('settings selfcheck OK')
