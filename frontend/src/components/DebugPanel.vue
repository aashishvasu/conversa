<script setup>
import { computed } from 'vue'
import { buildPayload } from '../cards.js'
import { effectiveSettings, workspaceOf } from '../store.js'

const props = defineProps({ convo: Object })

// Live: recomputes as messages, cards, settings, or memory change, so it is exactly what the next send builds.
// The memory summary refreshes in the background after each reply, and this preview shows its current state.
const payload = computed(() => buildPayload(props.convo, effectiveSettings(props.convo), workspaceOf(props.convo)))
</script>

<template>
  <div class="space-y-2 text-sm">
    <p class="text-muted">
      Live preview of the <code>system</code> param the next send will carry:
      system messages, memory summary, and triggered cards, in order.
    </p>
    <pre class="max-h-96 overflow-y-auto whitespace-pre-wrap rounded bg-surface2 p-2 text-xs [overflow-wrap:anywhere]">{{ payload.system || '(empty, so no system prompt is sent)' }}</pre>
    <p class="text-xs text-muted">
      {{ payload.model }} · temp {{ payload.temperature }} · max {{ payload.max_tokens }} tokens
      · {{ payload.messages.length }} msg{{ payload.messages.length === 1 ? '' : 's' }} in window
      · system {{ (payload.system || '').length }} chars
    </p>
  </div>
</template>
