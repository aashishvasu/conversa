// Run: node src/utils/md.selfcheck.js.
// Node has no DOM, so guard the security wiring that the browser executes.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const source = await readFile(new URL('./md.js', import.meta.url), 'utf8')

assert.match(source, /DOMPurify\.addHook\('afterSanitizeAttributes', \(node\) => \{\s*if \(node\.tagName === 'A'\) \{\s*node\.setAttribute\('target', '_blank'\)\s*node\.setAttribute\('rel', 'noopener noreferrer'\)/s, 'links get safe new-tab attributes after sanitization')
assert.match(source, /return DOMPurify\.sanitize\(marked\.parse\(text \|\| ''\)\)/, 'rendered markdown is sanitized')

console.log('md selfcheck OK')
