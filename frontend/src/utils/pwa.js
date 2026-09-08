import { useRegisterSW } from 'virtual:pwa-register/vue'
import { persistNow } from '../state/store.js'

// vite-plugin-pwa is configured with registerType: 'prompt', so a new service
// worker installs to the waiting state and stays there until something posts
// SKIP_WAITING. useRegisterSW wires that: it flips needRefresh when a worker is
// waiting, and updateServiceWorker posts the skip-waiting message.
//
// The reload does not happen inside updateServiceWorker. The waiting worker
// activates, fires the controlling event, and the plugin calls onNeedReload.
// Flushing IndexedDB before reloading closes the 400ms persistence debounce in
// state/store.js so an in-flight save is not lost. This covers both the button
// path and a controllerchange triggered from another tab activating the worker.
const { needRefresh, updateServiceWorker } = useRegisterSW({
  onNeedReload: () => { persistNow().finally(() => location.reload()) },
})

export { needRefresh }

// Flush the persistence debounce, then activate the waiting worker. The
// reload itself fires from onNeedReload once the new worker claims control.
// Call this only when needRefresh is true; with no waiting worker it is a no-op.
export async function applyUpdate() {
  await persistNow()
  await updateServiceWorker()
}
