// Per-message timestamp (e.g. "Jun 25, 14:30").
export function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Compact stamp for sidebar: time if today, else date.
export function formatShort(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const today = d.toDateString() === new Date().toDateString()
  return today
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}
