<script setup>
// One rendering of a spend summary, shared by the chat footer and Usage rows.
defineProps({ spend: { type: Object, required: true } })
</script>

<template>
  <span v-if="spend.calls">
    <span :title="spend.unpriced ? $t('usage.unpriced', spend.unpriced, { count: spend.unpriced }) : $t('usage.estimated')">{{ $t('usage.summary', { calls: spend.calls, tokens: Math.round((spend.input + spend.output) / 1000), amount: `${spend.unpriced ? '>' : ''}$${spend.usd.toFixed(2)}` }) }}</span>
  </span>
</template>
