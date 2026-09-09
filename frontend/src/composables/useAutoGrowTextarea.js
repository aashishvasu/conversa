import { ref, watch } from 'vue'
import { fontScale } from '../utils/prefs.js'

// Grows the textarea to fit its content, capped by max-h; shrinks back when cleared.
// Native field-sizing:content would be one CSS line, but Firefox still lacks it.
// fontScale reflows the text, so re-measure on change.
export function useAutoGrowTextarea(input) {
  const composerEl = ref(null)

  watch([input, fontScale], () => {
    const el = composerEl.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, { flush: 'post' })

  return { composerEl }
}
