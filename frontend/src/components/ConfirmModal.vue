<script setup>
import { answerConfirm, confirmState } from '../confirm.js'
import Modal from './Modal.vue'
</script>

<template>
  <Modal v-if="confirmState" title="Please confirm" @close="answerConfirm(false)">
    <p class="text-sm">{{ confirmState.message }}</p>
    <div class="mt-4 flex justify-end gap-2">
      <button class="rounded px-3 py-1.5 text-sm hover:bg-surface2" @click="answerConfirm(false)">Cancel</button>
      <button class="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-500" @click="answerConfirm(true)">{{ confirmState.label }}</button>
    </div>
  </Modal>
</template>
