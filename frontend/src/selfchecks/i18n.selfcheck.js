import assert from 'node:assert/strict'
import de from '../locales/de.json' with { type: 'json' }
import enGB from '../locales/en-GB.json' with { type: 'json' }
import es from '../locales/es.json' with { type: 'json' }
import fr from '../locales/fr.json' with { type: 'json' }
import it from '../locales/it.json' with { type: 'json' }

function flatten(messages, prefix = '', out = {}) {
  for (const [key, value] of Object.entries(messages)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object') flatten(value, path, out)
    else out[path] = value
  }
  return out
}

function placeholders(message) {
  return [...message.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort()
}

const english = flatten(enGB)
for (const [locale, messages] of Object.entries({ de, es, fr, it })) {
  const catalog = flatten(messages)
  assert.deepEqual(Object.keys(catalog).sort(), Object.keys(english).sort(), `${locale} keys`)
  for (const [key, value] of Object.entries(catalog)) {
    assert.ok(value, `${locale}.${key} is not empty`)
    assert.deepEqual(placeholders(value), placeholders(english[key]), `${locale}.${key} placeholders`)
  }
}

console.log('i18n selfcheck passed')
