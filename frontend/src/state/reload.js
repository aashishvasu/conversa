import { db } from './db.js'
import { persistNow } from './store.js'

// User-triggered reload/update must not discard unsaved work: a failed flush keeps the tab open.
export async function requestReload() {
  const saved = await persistNow()
  if (saved === false) return false
  location.reload()
  return true
}

// A forced schema/version change proceeds regardless: the old schema is gone, so staying open is not an option.
// Must return false: Dexie's default versionchange handler closes the connection, dropping the pending flush.
export function onVersionChange() {
  persistNow().finally(() => location.reload())
  return false
}

db.on('versionchange', onVersionChange)