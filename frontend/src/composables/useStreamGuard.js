import { onMounted, onUnmounted, watch } from 'vue'

// Keeps a pending chat turn healthy while its tab is backgrounded.
// A screen wake lock held while the viewed conversation streams prevents the freeze that mobile browsers apply when the screen locks.
// Mobile browsers can still freeze a backgrounded tab, leaving the read hung with no frames and no error.
// On returning to a visible tab after STALL_MS without a frame, the caller's reattach callback reconnects to the server-side stream, which replays the reply so far.
// The server's keepalive comments never reach the frame handler, so a long thinking gap can trigger a reattach of a healthy stream; that is harmless.
const STALL_MS = 60_000

export function useStreamGuard(isStreaming, lastFrameAt, reattach) {
  let wakeLock = null

  async function acquireWakeLock() {
    // The lock is dropped automatically whenever the page hides, so this re-runs on every return to visible.
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
    if (Date.now() - (lastFrameAt() ?? 0) > STALL_MS) reattach()
  }

  watch(isStreaming, (on) => (on ? acquireWakeLock() : releaseWakeLock()), { immediate: true })
  onMounted(() => document.addEventListener('visibilitychange', onVisibilityChange))
  onUnmounted(() => {
    document.removeEventListener('visibilitychange', onVisibilityChange)
    releaseWakeLock()
  })
}
