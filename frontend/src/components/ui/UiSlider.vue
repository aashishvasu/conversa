<script setup>
import { SliderRange, SliderRoot, SliderThumb, SliderTrack } from 'reka-ui'

const props = defineProps({
  modelValue: { type: Number, required: true },
  min: { type: Number, required: true },
  max: { type: Number, required: true },
  step: { type: Number, default: 1 },
  label: { type: String, required: true },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue', 'valueCommit'])
const first = (values) => values?.[0]
</script>

<template>
  <SliderRoot
    :model-value="[modelValue]"
    :min="min"
    :max="max"
    :step="step"
    :disabled="disabled"
    class="relative flex h-8 w-full touch-none select-none items-center"
    @update:model-value="first($event) !== undefined && emit('update:modelValue', first($event))"
    @value-commit="first($event) !== undefined && emit('valueCommit', first($event))"
  >
    <SliderTrack class="relative h-1.5 grow overflow-hidden rounded-full bg-edge">
      <SliderRange class="absolute h-full bg-accent" />
    </SliderTrack>
    <SliderThumb
      :aria-label="label"
      class="block size-4 rounded-full border-2 border-accent bg-surface shadow-sm outline-none transition-transform hover:scale-110 focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-app disabled:opacity-50"
    />
  </SliderRoot>
</template>
