<script setup>
import { computed } from 'vue'
import { SliderRange, SliderRoot, SliderThumb, SliderTrack } from 'reka-ui'

const props = defineProps({
  modelValue: { type: [Number, Array], required: true },
  min: { type: Number, required: true },
  max: { type: Number, required: true },
  step: { type: Number, default: 1 },
  label: { type: String, required: true },
  secondLabel: { type: String, default: undefined },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue', 'valueCommit'])
const isRange = computed(() => Array.isArray(props.modelValue))
const rootValue = computed(() => (isRange.value ? props.modelValue : [props.modelValue]))
const first = (values) => values?.[0]
const emitValue = (event, name) => {
  if (isRange.value) {
    if (Array.isArray(event)) emit(name, event)
  } else {
    const val = first(event)
    if (val !== undefined) emit(name, val)
  }
}
</script>

<template>
  <SliderRoot
    :model-value="rootValue"
    :min="min"
    :max="max"
    :step="step"
    :disabled="disabled"
    class="relative flex h-8 w-full touch-none select-none items-center"
    @update:model-value="emitValue($event, 'update:modelValue')"
    @value-commit="emitValue($event, 'valueCommit')"
  >
    <SliderTrack class="relative h-1.5 grow overflow-hidden rounded-full bg-edge">
      <SliderRange class="absolute h-full bg-accent" />
    </SliderTrack>
    <SliderThumb
      :aria-label="label"
      class="block size-4 rounded-full border-2 border-accent bg-surface shadow-sm outline-none transition-transform hover:scale-110 focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-app disabled:opacity-50"
    />
    <SliderThumb
      v-if="isRange"
      :aria-label="secondLabel || label"
      class="block size-4 rounded-full border-2 border-accent bg-surface shadow-sm outline-none transition-transform hover:scale-110 focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-app disabled:opacity-50"
    />
  </SliderRoot>
</template>
