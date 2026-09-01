<script setup>
import { Check, ChevronDown } from '@lucide/vue'
import { computed } from 'vue'
import {
  SelectContent,
  SelectItem,
  SelectItemIndicator,
  SelectItemText,
  SelectPortal,
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from 'reka-ui'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, required: true },
  placeholder: { type: String, default: '' },
  disabled: Boolean,
  compact: Boolean,
  iconOnly: Boolean,
  label: String,
})
const emit = defineEmits(['update:modelValue'])
const EMPTY = '__conversa_empty__'
const valueOf = (value) => value === '' || value === null ? EMPTY : value
const tooltip = computed(() => {
  if (props.modelValue === '' || props.modelValue === null) return props.label
  return `${props.label}: ${props.options.find((option) => option.value === props.modelValue)?.label || props.modelValue}`
})
</script>

<template>
  <SelectRoot :model-value="valueOf(modelValue)" :disabled="disabled" @update:model-value="emit('update:modelValue', $event === EMPTY ? '' : $event)">
    <SelectTrigger
      v-if="iconOnly"
      v-bind="$attrs"
      :title="tooltip"
      class="flex h-8 w-10 items-center justify-center gap-0.5 rounded-md border border-edge bg-surface2 text-muted outline-none transition-colors hover:bg-edge focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-app disabled:cursor-not-allowed disabled:opacity-50"
    >
      <slot name="trigger" />
      <ChevronDown :size="12" />
    </SelectTrigger>
    <SelectTrigger
      v-else
      v-bind="$attrs"
      class="flex w-full items-center justify-between gap-2 rounded-md border border-edge bg-surface2 px-3 text-left outline-none transition-colors hover:bg-edge focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-app disabled:cursor-not-allowed disabled:opacity-50"
      :class="compact ? 'h-8 text-xs' : 'h-9 text-sm'"
    >
      <SelectValue :placeholder="placeholder" />
      <ChevronDown :size="14" class="shrink-0 text-muted" />
    </SelectTrigger>
    <SelectPortal>
      <SelectContent position="popper" class="z-[70] max-h-72 min-w-[var(--reka-select-trigger-width)] overflow-hidden rounded-md border border-edge bg-surface text-sm shadow-lg" :side-offset="4">
        <SelectViewport class="p-1">
          <SelectItem
            v-for="option in options"
            :key="option.value"
            :value="valueOf(option.value)"
            :disabled="option.disabled"
            class="relative flex cursor-default select-none items-center rounded px-8 py-1.5 outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface2 data-[state=checked]:text-accent"
          >
            <SelectItemIndicator class="absolute left-2 inline-flex items-center"><Check :size="14" /></SelectItemIndicator>
            <SelectItemText>{{ option.label }}</SelectItemText>
          </SelectItem>
        </SelectViewport>
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>
