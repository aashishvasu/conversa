<script setup>
import UiTooltip from './ui/UiTooltip.vue'

// One rendering of a spend summary, shared by the chat footer and Usage rows.
defineProps({ spend: { type: Object, required: true } })

function formatNumber(num)
{
  const units = ['', 'k', 'M', 'B', 'T']
  const tier = Math.min(
    Math.floor(Math.log10(Math.abs(num)) / 3),
    units.length - 1,
  )

  if (tier <= 0) return String(num)

  const scaled = num / 1000 ** tier
  return `${Number(scaled.toFixed(1))}${units[tier]}`
}
</script>

<template>
  <span v-if="spend.calls">
    <UiTooltip :content="spend.unpriced ? $t('usage.unpriced', spend.unpriced, { count: spend.unpriced }) : $t('usage.estimated')">
      <span>{{ $t('usage.summary', { calls: spend.calls, tokens: formatNumber(spend.input + spend.output), amount: `${spend.unpriced ? '>' : ''}$${spend.usd.toFixed(2)}` }) }}</span>
    </UiTooltip>
  </span>
</template>
