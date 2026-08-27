import { watch } from 'vue'
import { createI18n } from 'vue-i18n'
import de from './locales/de.json'
import enGB from './locales/en-GB.json'
import es from './locales/es.json'
import fr from './locales/fr.json'
import it from './locales/it.json'
import { locale } from './utils/prefs.js'

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

export function setLocale(value) {
  locale.value = Object.hasOwn(locales, value) ? value : 'en-GB'
}

watch(locale, (value) => {
  i18n.global.locale.value = value
  document.documentElement.lang = value
  document.documentElement.dir = ['ar', 'he', 'fa', 'ur'].includes(value.split('-')[0]) ? 'rtl' : 'ltr'
}, { immediate: true })
