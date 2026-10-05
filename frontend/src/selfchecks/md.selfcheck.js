// Run: node src/selfchecks/md.selfcheck.js.
// Node has no DOM, so guard the security wiring that the browser executes.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const source = await readFile(new URL('../utils/md.js', import.meta.url), 'utf8')

assert.match(source, /DOMPurify\.addHook\('afterSanitizeAttributes', \(node\) => \{\s*if \(node\.tagName === 'A'\) \{\s*node\.setAttribute\('target', '_blank'\)\s*node\.setAttribute\('rel', 'noopener noreferrer'\)/s, 'links get safe new-tab attributes after sanitization')
assert.match(source, /return DOMPurify\.sanitize\(marked\.parse\(text \|\| ''\)\)/, 'rendered markdown is sanitized')

// Link color comes from the --c-link token so it flips with the theme and clears AA on both surfaces.
const css = await readFile(new URL('../styles/style.css', import.meta.url), 'utf8')
assert.match(css, /--c-link:\s*#4338ca/, 'light --c-link is set')
assert.match(css, /\.dark\s*\{[^}]*--c-link:\s*#a5b4fc/s, 'dark --c-link is set')
assert.match(css, /\.md a \{ color: var\(--c-link\)/, '.md a uses the --c-link token')
assert.match(css, /\.bg-accent \.md a \{ color: currentColor/, 'links inside an accent bubble inherit the on-accent text color')

console.log('md selfcheck OK')
