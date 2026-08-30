<script setup>
import { Bot, Check, ChevronsUpDown } from '@lucide/vue'
import { computed } from 'vue'
import {
  ComboboxAnchor,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxGroup,
  ComboboxInput,
  ComboboxItem,
  ComboboxItemIndicator,
  ComboboxLabel,
  ComboboxPortal,
  ComboboxRoot,
  ComboboxTrigger,
  ComboboxViewport,
} from 'reka-ui'
import { models } from '../state/store.js'

defineOptions({ inheritAttrs: false })

const PROVIDER_LABELS = { anthropic: 'Anthropic', openai: 'OpenAI' }

const props = defineProps({ modelValue: String, compact: Boolean, iconOnly: Boolean, label: { type: String, required: true } })
const emit = defineEmits(['update:modelValue'])

const groups = computed(() => {
  const by = new Map()
  for (const model of models.value) {
    const provider = model.provider || 'anthropic'
    if (!by.has(provider)) by.set(provider, [])
    by.get(provider).push(model)
  }
  return [...by].map(([provider, items]) => ({ key: provider, label: PROVIDER_LABELS[provider] || provider, items }))
})
const labelOf = (id) => models.value.find((model) => model.id === id)?.label || id || ''
const tooltip = computed(() => `${props.label}: ${labelOf(props.modelValue)}`)
</script>

<template>
  <ComboboxRoot :model-value="modelValue" open-on-click @update:model-value="emit('update:modelValue', $event)">
    <ComboboxAnchor
      v-bind="$attrs"
      class="flex w-full items-center rounded-md border border-edge bg-surface2 outline-none transition-colors hover:bg-edge focus-within:ring-2 focus-within:ring-focus focus-within:ring-offset-2 focus-within:ring-offset-app"
      :class="[compact ? 'h-8 text-xs' : 'h-9 text-sm', iconOnly && '!w-10']"
    >
      <ComboboxInput :display-value="labelOf" :aria-label="label" :class="iconOnly ? 'sr-only' : 'min-w-0 flex-1 bg-transparent px-3 outline-none'" />
      <ComboboxTrigger class="flex h-full shrink-0 items-center justify-center gap-0.5 text-muted outline-none" :class="iconOnly ? 'w-full' : 'w-8'" :aria-label="tooltip" :title="tooltip">
        <Bot v-if="iconOnly" :size="14" />
        <ChevronsUpDown :size="iconOnly ? 12 : 14" />
      </ComboboxTrigger>
    </ComboboxAnchor>
    <ComboboxPortal>
      <ComboboxContent position="popper" class="z-[70] max-h-72 min-w-[var(--reka-combobox-trigger-width)] overflow-hidden rounded-md border border-edge bg-surface text-sm shadow-lg" :side-offset="4">
        <ComboboxViewport class="p-1">
          <ComboboxEmpty class="px-3 py-6 text-center text-sm text-muted">{{ $t('common.noResults') }}</ComboboxEmpty>
          <ComboboxGroup v-for="group in groups" :key="group.key">
            <ComboboxLabel class="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-muted">{{ group.label }}</ComboboxLabel>
            <ComboboxItem
              v-for="model in group.items"
              :key="model.id"
              :value="model.id"
              :text-value="model.label"
              class="relative flex cursor-default select-none items-center rounded px-8 py-1.5 outline-none data-[highlighted]:bg-surface2 data-[state=checked]:text-accent"
            >
              <ComboboxItemIndicator class="absolute left-2 inline-flex items-center"><Check :size="14" /></ComboboxItemIndicator>
              <span class="truncate">{{ model.label }}</span>
            </ComboboxItem>
          </ComboboxGroup>
        </ComboboxViewport>
      </ComboboxContent>
    </ComboboxPortal>
  </ComboboxRoot>
</template>
