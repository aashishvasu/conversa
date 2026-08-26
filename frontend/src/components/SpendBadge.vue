<script setup>
// One rendering of a spend summary, shared by the research pane, the chat footer, and (later) the Usage pane.
defineProps({ spend: { type: Object, required: true } })
</script>

<template>
  <span v-if="spend.calls">
    {{ spend.calls }} calls · {{ Math.round((spend.input + spend.output) / 1000) }}k tokens ·
    <span :title="spend.unpriced ? spend.unpriced + ' call(s) used a model with no published rate, charged here at the top tier' : 'estimated from published rates'">
      {{ spend.unpriced ? '>' : '' }}${{ spend.usd.toFixed(2) }}
    </span>
  </span>
</template>
