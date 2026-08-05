<script setup>
import { computed } from 'vue'
import { models } from '../store.js'

// The one model dropdown. The composer toolbar, per-conversation settings, and global
// settings all render this (twice each in the settings panels: model + utility model).
// Native <optgroup> gives real section headers on iOS and Android with no JS.
// The provider is grouping only. Picking a model is the user's choice; picking a
// provider is a consequence of it, so no provider control exists anywhere.

const PROVIDER_LABELS = { anthropic: 'Anthropic', openai: 'OpenAI' }

defineProps({ modelValue: String })
defineEmits(['update:modelValue'])

const groups = computed(() => {
  const by = new Map()
  for (const m of models.value) {
    // Models cached before providers existed have no provider field.
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
