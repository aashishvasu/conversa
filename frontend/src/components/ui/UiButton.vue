<script setup>
defineOptions({ inheritAttrs: false })

const props = defineProps({
  variant: { type: String, default: 'secondary' },
  size: { type: String, default: 'normal' },
  loading: Boolean,
  disabled: Boolean,
  type: { type: String, default: 'button' },
})

const variants = {
  primary: 'bg-accent text-on-accent hover:bg-accent-hover',
  secondary: 'border border-edge bg-surface2 hover:bg-edge',
  ghost: 'bg-transparent text-muted hover:bg-surface2 hover:text-base',
  danger: 'bg-danger text-on-danger hover:opacity-90',
}
const sizes = {
  compact: 'h-8 px-2 text-xs',
  normal: 'h-9 px-3 text-sm',
}
</script>

<template>
  <button
    v-bind="$attrs"
    :type="props.type"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
    class="inline-flex items-center justify-center gap-2 rounded-md font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-app disabled:pointer-events-none disabled:opacity-50"
    :class="[variants[props.variant], sizes[props.size]]"
  >
    <slot />
  </button>
</template>
