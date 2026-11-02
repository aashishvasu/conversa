<script setup>
import { computed, ref, watch } from 'vue'
import { buildPayload } from '../prompt/payload.js'
import { effectiveSettings, enabledTools } from '../state/settings.js'
import { attachedDocs, images, workspaceOf } from '../state/store.js'
import { fetchSystemPreview } from '../api/client.js'
import { tr } from '../i18n/index.js'

const props = defineProps({ convo: Object })

// Live: recomputes as messages, cards, settings, or memory change, so it is exactly what the next send builds.
// The memory summary refreshes in the background after each reply, and this preview shows its current state.
const payload = computed(() => buildPayload(props.convo, effectiveSettings(props.convo), workspaceOf(props.convo), attachedDocs(props.convo), images.value))

// The server renders the same system prompt it will use for the next send. Reuse that path instead of duplicating it.
// A string is shown as-is; a [stable, volatile] cache split is labelled so both blocks read clearly.
const serverSystem = ref(null)
const previewError = ref('')

const previewBody = computed(() => ({ ...payload.value, enabled_tools: enabledTools(effectiveSettings(props.convo)) }))

watch(previewBody, async (body) => {
  try {
    serverSystem.value = await fetchSystemPreview(body)
    previewError.value = ''
  } catch (error) {
    serverSystem.value = null
    previewError.value = error.message || 'Preview failed'
  }
}, { immediate: true })

const systemDisplay = computed(() => {
  if (previewError.value) {
    const system = payload.value.system
    return typeof system === 'string' ? system : previewError.value
  }
  const rendered = serverSystem.value
  if (Array.isArray(rendered)) {
    const [stable, volatile] = rendered
    if (!stable && !volatile) return ''
    return `${tr('debug.stable')}\n\n${stable || ''}\n\n${tr('debug.volatile')}\n\n${volatile || ''}`
  }
  return rendered || ''
})

const systemChars = computed(() => {
  const rendered = serverSystem.value
  if (Array.isArray(rendered)) return rendered.reduce((total, part) => total + (part || '').length, 0)
  return (rendered || '').length
})
</script>

<template>
  <div class="space-y-2 text-sm">
    <p class="text-muted">{{ $t('debug.help') }}</p>
    <pre class="max-h-96 overflow-y-auto whitespace-pre-wrap rounded bg-surface2 p-2 text-xs [overflow-wrap:anywhere]">{{ systemDisplay || $t('debug.empty') }}</pre>
    <p class="text-xs text-muted">{{ $t('debug.summary', { model: payload.model, temperature: payload.temperature, tokens: payload.max_tokens, messages: payload.messages.length, chars: systemChars }) }}</p>
  </div>
</template>
