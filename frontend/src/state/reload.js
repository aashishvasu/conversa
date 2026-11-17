import { db } from './db.js'
import { persistNow } from './store.js'

export function requestReload() {
  persistNow().finally(() => location.reload())
}

// Must return false: Dexie's default versionchange handler closes the connection, dropping the pending flush.
export function onVersionChange() {
  requestReload()
  return false
}

db.on('versionchange', onVersionChange)