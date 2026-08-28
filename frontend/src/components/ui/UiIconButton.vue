<script setup>
import { TooltipContent, TooltipPortal, TooltipRoot, TooltipTrigger } from 'reka-ui'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  label: { type: String, required: true },
  disabled: Boolean,
  variant: { type: String, default: 'ghost' },
})

const variants = {
  ghost: 'text-muted hover:bg-surface2 hover:text-base',
  danger: 'text-muted hover:bg-danger/10 hover:text-danger',
  dangerSolid: 'bg-danger text-on-danger hover:opacity-90',
  primary: 'bg-accent text-on-accent hover:bg-accent-hover',
}
const buttonClass = 'inline-flex size-8 items-center justify-center rounded-md outline-none transition-colors focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-app disabled:opacity-50'
</script>

<template>
  <TooltipRoot>
    <TooltipTrigger v-if="!disabled" as-child>
      <button v-bind="$attrs" type="button" :aria-label="label" :class="[buttonClass, variants[props.variant]]">
        <slot />
      </button>
    </TooltipTrigger>
    <TooltipTrigger v-else as-child>
      <span class="inline-flex rounded-md outline-none focus-visible:ring-2 focus-visible:ring-focus" tabindex="0">
        <button v-bind="$attrs" type="button" disabled :aria-label="label" :class="[buttonClass, variants[props.variant], 'pointer-events-none']">
          <slot />
        </button>
      </span>
    </TooltipTrigger>
    <TooltipPortal>
      <TooltipContent class="z-[70] max-w-64 rounded-md border border-edge bg-surface px-2 py-1 text-xs text-base shadow-lg" :side-offset="6">
        {{ label }}
      </TooltipContent>
    </TooltipPortal>
  </TooltipRoot>
</template>
