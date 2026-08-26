import { ref, watch } from 'vue'

// Frontend-only UI preferences.
// They live in localStorage and apply purely to how this browser renders the app.

const FONT_KEY = 'conversa_font_scale'
const ENTER_KEY = 'conversa_enter_to_send'

export const fontScale = ref(1) // root font-size multiplier; Tailwind is rem-based, so this zooms the whole UI
export const enterToSend = ref(true) // false: Enter makes a newline and Shift+Enter sends

function applyFontScale() {
  document.documentElement.style.fontSize = `${fontScale.value * 100}%`
}

// Load saved prefs and start persisting changes.
// Call before mount to avoid a flash.
export function restorePrefs(prefs) {
  if (typeof prefs.fontScale === 'number' && prefs.fontScale >= 0.8 && prefs.fontScale <= 1.4) fontScale.value = prefs.fontScale
  if (typeof prefs.enterToSend === 'boolean') enterToSend.value = prefs.enterToSend
}

export function initPrefs() {
  const f = parseFloat(localStorage.getItem(FONT_KEY))
  if (f) fontScale.value = f
  if (localStorage.getItem(ENTER_KEY) !== null) enterToSend.value = localStorage.getItem(ENTER_KEY) === 'true'
  applyFontScale()
  watch(fontScale, (v) => {
    localStorage.setItem(FONT_KEY, String(v))
    applyFontScale()
  })
  watch(enterToSend, (v) => localStorage.setItem(ENTER_KEY, String(v)))
}
