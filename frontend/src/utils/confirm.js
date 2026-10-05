import { ref } from 'vue'

import { tr } from '../i18n/index.js'

// Promise-based confirmation, backed by one ConfirmModal mounted at app root.
// Usage: if (await confirmDelete('Delete this card?')) remove()
// Single-flight: the modal's backdrop blocks other clicks, so only one is ever open.

export const confirmState = ref(null) // { message, label, resolve } when open, else null

export function confirmDelete(message, label = tr('common.delete')) {
  return new Promise((resolve) => {
    confirmState.value = { message, label, resolve }
  })
}

export function answerConfirm(ok) {
  confirmState.value?.resolve(ok)
  confirmState.value = null
}
