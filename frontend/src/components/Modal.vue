<script setup>
import { onMounted, onUnmounted } from 'vue'

defineProps({ title: String })
const emit = defineEmits(['close'])

function onKey(e) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-40 flex items-center justify-center bg-black/50 p-4"
      @click.self="emit('close')"
    >
      <div class="flex max-h-[85vh] w-full max-w-lg flex-col rounded-lg bg-surface text-base shadow-xl">
        <div class="flex items-center justify-between border-b border-edge px-4 py-3">
          <h2 class="text-sm font-medium">{{ title }}</h2>
          <button class="text-muted hover:text-base" @click="emit('close')">✕</button>
        </div>
        <div class="overflow-y-auto p-4">
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>
