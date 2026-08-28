<script setup>
import { useId } from 'vue'
import { Label, SwitchRoot, SwitchThumb } from 'reka-ui'

const model = defineModel({ type: Boolean, required: true })
const props = defineProps({
  label: { type: String, required: true },
  help: { type: String, default: '' },
  disabled: Boolean,
  compact: Boolean,
})
const id = useId()
</script>

<template>
  <div class="flex items-center justify-between" :class="compact ? 'inline-flex' : 'min-h-9 gap-4'">
    <div :class="compact ? 'sr-only' : 'min-w-0'">
      <Label :for="id" class="block cursor-pointer text-sm font-medium" :class="disabled && 'cursor-not-allowed opacity-50'">{{ label }}</Label>
      <p v-if="help" class="mt-0.5 text-xs text-muted">{{ help }}</p>
    </div>
    <div class="flex shrink-0 items-center gap-1">
      <slot name="action" />
    <SwitchRoot
      :id="id"
      v-model="model"
      :disabled="disabled"
      class="relative h-6 w-11 shrink-0 rounded-full border border-edge bg-edge outline-none transition-colors data-[state=checked]:border-accent data-[state=checked]:bg-accent focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-app disabled:cursor-not-allowed disabled:opacity-50"
    >
      <SwitchThumb class="block size-5 translate-x-0 rounded-full bg-surface shadow-sm transition-transform data-[state=checked]:translate-x-5 rtl:data-[state=checked]:-translate-x-5" />
    </SwitchRoot>
    </div>
  </div>
</template>
