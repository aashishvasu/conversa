import { ref } from 'vue'

const KEY = 'conversa_theme'
export const isDark = ref(true)

function apply() {
  document.documentElement.classList.toggle('dark', isDark.value)
}

// Saved choice wins; otherwise follow the OS preference. Call before mount to avoid a flash.
export function initTheme() {
  const saved = localStorage.getItem(KEY)
  isDark.value = saved
    ? saved === 'dark'
    : window.matchMedia('(prefers-color-scheme: dark)').matches
  apply()
}

export function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem(KEY, isDark.value ? 'dark' : 'light')
  apply()
}
