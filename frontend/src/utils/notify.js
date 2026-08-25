import { ref } from 'vue'

export const notifications = ref([])
let nextId = 1

export function notify(notification) {
  const existing = notifications.value.find((n) => n.key === notification.key)
  const n = {
    id: nextId++,
    count: (existing?.count || 0) + 1,
    severity: 'error',
    sticky: false,
    ...notification,
  }
  notifications.value = existing
    ? notifications.value.map((item) => item === existing ? n : item)
    : [...notifications.value, n]
  return n
}

export function dismiss(idOrKey) {
  notifications.value = notifications.value.filter((n) => n.id !== idOrKey && n.key !== idOrKey)
}
