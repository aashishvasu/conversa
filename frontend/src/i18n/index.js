import { watch } from 'vue'
import { createI18n } from 'vue-i18n'
import de from '../locales/de.json' with { type: 'json' }
import enGB from '../locales/en-GB.json' with { type: 'json' }
import es from '../locales/es.json' with { type: 'json' }
import fr from '../locales/fr.json' with { type: 'json' }
import it from '../locales/it.json' with { type: 'json' }
import { locale } from '../utils/prefs.js'

export const locales = {
  de: 'Deutsch',
  'en-GB': 'English (UK)',
  es: 'Español',
  fr: 'Français',
  it: 'Italiano',
}

export const i18n = createI18n({
  legacy: false,
  locale: locale.value,
  fallbackLocale: 'en-GB',
  messages: { de, 'en-GB': enGB, es, fr, it },
})

export const tr = (...args) => i18n.global.t(...args)

export function setLocale(value) {
  locale.value = Object.hasOwn(locales, value) ? value : 'en-GB'
}

watch(locale, (value) => {
  i18n.global.locale.value = value
  if (globalThis.document) {
    document.documentElement.lang = value
    document.documentElement.dir = ['ar', 'he', 'fa', 'ur'].includes(value.split('-')[0]) ? 'rtl' : 'ltr'
  }
}, { immediate: true })
