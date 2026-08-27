<script setup>
import { computed } from 'vue'
import { buildPayload } from '../prompt/payload.js'
import { effectiveSettings } from '../state/settings.js'
import { attachedDocs, images, workspaceOf } from '../state/store.js'

const props = defineProps({ convo: Object })

// Live: recomputes as messages, cards, settings, or memory change, so it is exactly what the next send builds.
// The memory summary refreshes in the background after each reply, and this preview shows its current state.
const payload = computed(() => buildPayload(props.convo, effectiveSettings(props.convo), workspaceOf(props.convo), attachedDocs(props.convo), images.value))
</script>

<template>
  <div class="space-y-2 text-sm">
    <p class="text-muted">{{ $t('debug.help') }}</p>
    <pre class="max-h-96 overflow-y-auto whitespace-pre-wrap rounded bg-surface2 p-2 text-xs [overflow-wrap:anywhere]">{{ payload.system || $t('debug.empty') }}</pre>
    <p class="text-xs text-muted">{{ $t('debug.summary', { model: payload.model, temperature: payload.temperature, tokens: payload.max_tokens, messages: payload.messages.length, chars: (payload.system || '').length }) }}</p>
  </div>
</template>
