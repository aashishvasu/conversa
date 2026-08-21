import { onMounted, onUnmounted } from 'vue'

// Defences for streams in backgrounded tabs.
// Mobile browsers freeze a backgrounded tab and the read hangs: no chunks, no error, so `finally` never runs and the composer stays locked behind a spinner.
// Two defences.
// A screen wake lock held while streaming prevents the freeze when the cause is the screen locking.
// And on returning to a visible tab, a stream that went silent is aborted through the caller's abort callback (the existing stop() path), keeping the partial reply and unlocking the composer.
// Neither provider can restart a dropped stream, so a clean stop is the best outcome available.
// Typing "continue" picks up from the partial assistant turn, which the next request already sends as history.
// The knob: 60s of silence, no server keepalive.
// If a long search or thinking gap trips it, emit a periodic `: ping` from /api/chat and key the watchdog off that.
const STALL_MS = 60_000

export function useStreamGuard(isStreaming, abort) {
  let lastChunkAt = 0
  let wakeLock = null

  async function acquireWakeLock() {
    // The lock is dropped automatically whenever the page hides, so this re-runs on every return to visible.
    // Unsupported, insecure-context, and denied all land in catch, and the watchdog below still covers those cases.
    try {
      wakeLock = (await navigator.wakeLock?.request('screen')) || null
    } catch { /* best-effort */ }
  }
  function releaseWakeLock() {
    wakeLock?.release().catch(() => {})
    wakeLock = null
  }

  function onVisibilityChange() {
    if (document.visibilityState !== 'visible' || !isStreaming()) return
    acquireWakeLock()
    if (Date.now() - lastChunkAt > STALL_MS) abort()
  }
  onMounted(() => document.addEventListener('visibilitychange', onVisibilityChange))
  onUnmounted(() => document.removeEventListener('visibilitychange', onVisibilityChange))

  return {
    start() {
      lastChunkAt = Date.now() // watchdog baseline: nothing has arrived yet
      acquireWakeLock()
    },
    heartbeat() {
      lastChunkAt = Date.now()
    },
    end: releaseWakeLock,
  }
}
