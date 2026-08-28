<script setup>
import { Minus, Plus } from '@lucide/vue'
import { NumberFieldDecrement, NumberFieldIncrement, NumberFieldInput, NumberFieldRoot } from 'reka-ui'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: Number, required: true },
  min: { type: Number, default: undefined },
  max: { type: Number, default: undefined },
  step: { type: Number, default: 1 },
  disabled: Boolean,
  compact: Boolean,
  label: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <NumberFieldRoot
    v-bind="$attrs"
    :model-value="modelValue"
    :min="min"
    :max="max"
    :step="step"
    :disabled="disabled"
    :disable-wheel-change="true"
    :format-options="{ useGrouping: false }"
    class="flex w-full items-stretch overflow-hidden rounded-md border border-edge bg-surface2 outline-none focus-within:ring-2 focus-within:ring-focus focus-within:ring-offset-2 focus-within:ring-offset-app"
    :class="compact ? 'h-8' : 'h-9'"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <NumberFieldDecrement class="flex w-8 items-center justify-center border-r border-edge text-muted outline-none hover:bg-edge hover:text-base disabled:opacity-40" :aria-label="$t('common.decrease')">
      <Minus :size="13" />
    </NumberFieldDecrement>
    <NumberFieldInput :aria-label="label" class="min-w-0 flex-1 bg-transparent px-2 text-center text-sm outline-none" />
    <NumberFieldIncrement class="flex w-8 items-center justify-center border-l border-edge text-muted outline-none hover:bg-edge hover:text-base disabled:opacity-40" :aria-label="$t('common.increase')">
      <Plus :size="13" />
    </NumberFieldIncrement>
  </NumberFieldRoot>
</template>
