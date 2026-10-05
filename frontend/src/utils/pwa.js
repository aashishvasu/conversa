import { useRegisterSW } from 'virtual:pwa-register/vue'
import { persistNow } from '../state/store.js'

// Flush pending IndexedDB writes before reload, including when another tab activates the worker.
const { needRefresh, updateServiceWorker } = useRegisterSW({
  onNeedReload: () => { persistNow().finally(() => location.reload()) },
})

export { needRefresh }

export async function applyUpdate() {
  await persistNow()
  await updateServiceWorker()
}
