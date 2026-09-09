<script setup>
import { RotateCcw } from '@lucide/vue'
import UiIconButton from '../ui/UiIconButton.vue'

defineProps({
  overridden: Boolean,
})
const emit = defineEmits(['useGlobal'])
</script>

<template>
  <UiIconButton v-if="overridden" :label="$t('settings.inheritGlobal')" @click="emit('useGlobal')">
    <RotateCcw :size="14" />
  </UiIconButton>
</template>
