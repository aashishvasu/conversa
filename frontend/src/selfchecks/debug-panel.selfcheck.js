// Run: node src/selfchecks/debug-panel.selfcheck.js.
// Guards that the debug panel shows the server-rendered system prompt, not raw JSON,
// and labels the [stable, volatile] cache split when the server returns a list.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const panel = await readFile(new URL('../components/DebugPanel.vue', import.meta.url), 'utf8')
assert.ok(!/JSON\.stringify\(system/.test(panel), 'DebugPanel must not stringify the structured system object')
assert.ok(/fetchSystemPreview/.test(panel), 'DebugPanel must call the server-rendered preview endpoint')
assert.ok(/enabledTools/.test(panel), 'DebugPanel must include enabledTools(settings) in the preview payload')
assert.ok(/enabled_tools:\s*enabledTools/.test(panel), 'DebugPanel must send top-level enabled_tools for the preview')
assert.ok(/Array\.isArray\(rendered\)/.test(panel), 'DebugPanel must handle the [stable, volatile] cache split')
assert.ok(/tr\('debug\.stable'\)/.test(panel), 'DebugPanel must label the stable system block')
assert.ok(/tr\('debug\.volatile'\)/.test(panel), 'DebugPanel must label the volatile system block')

console.log('debug panel selfcheck OK')
