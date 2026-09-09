// Run: node src/selfchecks/phrase.selfcheck.js.
import assert from 'node:assert/strict'
import { normalizePhrase } from '../utils/phrase.js'

assert.equal(normalizePhrase('run-jump-happy-calm-fox'), 'run-jump-happy-calm-fox')
assert.equal(normalizePhrase('  RUN  Jump_happy calm FOX '), 'run-jump-happy-calm-fox')
assert.equal(normalizePhrase('RUN\nJump\thappy.calm fox'), 'run-jump-happy-calm-fox')
assert.equal(normalizePhrase('walk2-jump-kind-kind-fox'), 'walk-jump-kind-kind-fox', 'non-letter characters are dropped, matching the server')
for (const bad of ['', '   ', 'not enough words', 'six-whole-words-right-here-now', 'walk-jump-kind', 'walk-jump-kind-kind']) {
  assert.equal(normalizePhrase(bad), '', bad)
}
assert.equal(normalizePhrase(null), '')
assert.equal(normalizePhrase(undefined), '')

console.log('phrase selfcheck OK')
