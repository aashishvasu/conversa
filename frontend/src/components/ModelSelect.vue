<script setup>
import { computed } from 'vue'
import { models } from '../state/store.js'

// Shared model dropdown for the composer and settings panels.
// Native <optgroup> supplies provider headings on desktop and mobile.

const PROVIDER_LABELS = { anthropic: 'Anthropic', openai: 'OpenAI' }

defineProps({ modelValue: String })
defineEmits(['update:modelValue'])

const groups = computed(() => {
  const by = new Map()
  for (const m of models.value) {
    // Bare cached model ids belong to Anthropic.
    const p = m.provider || 'anthropic'
    if (!by.has(p)) by.set(p, [])
    by.get(p).push(m)
  }
  return [...by].map(([p, items]) => ({ key: p, label: PROVIDER_LABELS[p] || p, items }))
})
</script>

<template>
  <select :value="modelValue" @change="$emit('update:modelValue', $event.target.value)">
    <optgroup v-for="g in groups" :key="g.key" :label="g.label">
      <option v-for="m in g.items" :key="m.id" :value="m.id">{{ m.label }}</option>
    </optgroup>
  </select>
</template>
