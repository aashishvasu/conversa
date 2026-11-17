// WHY: dexie over idb-keyval or raw IndexedDB.
// A row-per-record store needs multi-table atomic transactions, secondary indexes and per-row writes, which a key-value store cannot express.
import Dexie from 'dexie'

export const SCHEMA_VERSION = 1

export const db = new Dexie('conversa')
db.version(SCHEMA_VERSION).stores({
  conversations: 'id, createdAt',
  messages: 'id, convoId, turnId, *imageIds',
  workspaces: 'id',
  docs: 'id',
  images: 'id',
  runs: 'id, convoId',
  runEvents: '++key, runId',
  usage: '[day+model+kind]',
  meta: 'key',
})

