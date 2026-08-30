import { ref, watch } from 'vue'

// Frontend-only UI preferences.
// They live in localStorage and apply purely to how this browser renders the app.

const FONT_KEY = 'conversa_font_scale'
const ENTER_KEY = 'conversa_enter_to_send'
const SHOW_TRACE_KEY = 'conversa_show_thinking_and_search'
const LOCALE_KEY = 'conversa_locale'
const LOCALES = new Set(['de', 'en-GB', 'es', 'fr', 'it'])

export const fontScale = ref(1) // root font-size multiplier; Tailwind is rem-based, so this zooms the whole UI
export const enterToSend = ref(true) // false: Enter makes a newline and Shift+Enter sends
export const showThinkingAndSearch = ref(true)
export const locale = ref('en-GB')

function browserLocale(value) {
  if (LOCALES.has(value)) return value
  const language = value?.split('-')[0]
  return language === 'en' ? 'en-GB' : LOCALES.has(language) ? language : 'en-GB'
}

function applyFontScale() {
  document.documentElement.style.fontSize = `${fontScale.value * 100}%`
}

// Load saved prefs and start persisting changes.
// Call before mount to avoid a flash.
export function restorePrefs(prefs) {
  if (typeof prefs.fontScale === 'number' && prefs.fontScale >= 0.8 && prefs.fontScale <= 1.4) fontScale.value = prefs.fontScale
  if (typeof prefs.enterToSend === 'boolean') enterToSend.value = prefs.enterToSend
  if (typeof prefs.showThinkingAndSearch === 'boolean') showThinkingAndSearch.value = prefs.showThinkingAndSearch
  if (LOCALES.has(prefs.locale)) locale.value = prefs.locale
}

export function initPrefs() {
  const f = parseFloat(localStorage.getItem(FONT_KEY))
  if (f) fontScale.value = f
  if (localStorage.getItem(ENTER_KEY) !== null) enterToSend.value = localStorage.getItem(ENTER_KEY) === 'true'
  if (localStorage.getItem(SHOW_TRACE_KEY) !== null) showThinkingAndSearch.value = localStorage.getItem(SHOW_TRACE_KEY) === 'true'
  const savedLocale = localStorage.getItem(LOCALE_KEY)
  locale.value = LOCALES.has(savedLocale) ? savedLocale : browserLocale(navigator.language)
  applyFontScale()
  watch(fontScale, (v) => {
    localStorage.setItem(FONT_KEY, String(v))
    applyFontScale()
  })
  watch(enterToSend, (v) => localStorage.setItem(ENTER_KEY, String(v)))
  watch(showThinkingAndSearch, (v) => localStorage.setItem(SHOW_TRACE_KEY, String(v)))
  watch(locale, (v) => localStorage.setItem(LOCALE_KEY, v))
}
