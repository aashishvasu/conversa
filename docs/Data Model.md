# Data model

One IndexedDB database in the browser, named `conversa`. `frontend/src/state/db.js` declares the schema.

## Schema Versions and changes

Two independent version numbers.

`SCHEMA_VERSION`: bumped when a table or index changes, with the matching `db.version(n).stores({...}).upgrade(...)` step.

`SNAPSHOT_VERSION`: bumped when an older reader could silently lose data. Add the row below.

Migration from the pre-Dexie `idb-keyval` layout is one-way. `frontend/src/state/migrate-keyval.js` reads the old store and applies the record fixups in one transaction. It deletes the old database once the counts match.

| Type | Current Value | Latest Change |
|---|---|---|
| SCHEMA_VERSION | 1 | [26f38f4](https://github.com/aashishvasu/conversa/commit/26f38f45c7f4de33f7a68a7ef8c571ea3f7f7024) |
| SNAPSHOT_VERSION | 5 | [e953d7c](https://github.com/aashishvasu/conversa/commit/e953d7cc4443ec960c17c3d9dce87eae4b3f2489) |

## Schema

```js
db.version(1).stores({
  conversations: 'id, createdAt',
  messages:      'id, convoId, turnId, *imageIds',
  workspaces:    'id',
  docs:          'id',
  images:        'id',
  runs:          'id, convoId',
  runEvents:     '++key, runId',
  usage:         '[day+model+kind]',
  meta:          'key',
})
```

| Index | What it buys |
|-------|--------------|
| `conversations.createdAt` | Sidebar order. Read descending, so the newest conversation leads and no row stores a list. |
| `messages.turnId` | Finds an in-flight turn in any conversation after a reload, without loading it. |
| `messages.*imageIds` | Image collection. Multi-entry, so one entry per image id. |
| `runs.convoId` | Deleting a conversation deletes its runs and their events. |
| `runEvents.++key` | Auto-increment gives arrival order for free. `seq` is stored as data, not indexed: the backend restarts numbering from 1 after a restart, so `[runId+seq]` would collide. |
| `usage.[day+model+kind]` | The ledger's natural key. |

`meta` holds three single rows: `global`, `models`, `schema`.

## Records

A conversation row is metadata only.

```js
conversation: { id, title, isTemplate, scanAssistant, workspaceId, docIds, mode,
                settings, cards, cardOverrides, memory, memoryCount, usage,
                messageIds, createdAt, updatedAt }
message:      { id, role, content, createdAt, imageIds, mode, turnId, runId,
                artifacts, pinned, docId }
artifact:     { tool, input, output, recordedAt, freshUntil }
card:         { id, triggers, content, path, force }
workspace:    { id, name, messages, cards, docIds }
doc:          { id, name, text, createdAt, updatedAt, source, versions }
image:        { id, data, media_type, width, height, createdAt }
usage row:    { calls, input, output, cacheRead, cacheWrite, usd, unpriced }
```

Notes worth knowing:

- Templates are conversations with `isTemplate: true`.
- A conversation's own system prompt is a `role: 'system'` message. A workspace's are its `messages` array.
- `turnId` is set while a turn streams and released when it settles. That is how another tab adopts the reply.
- `artifacts` are tool evidence on the assistant message that produced them. `freshUntil` decides whether they can be reused without refetching.
- Card `triggers` is a comma-separated clause list: comma is OR, `&` inside a clause is AND. `force` overrides triggers.
- `doc.versions` keeps the last 10 `{ text, savedAt }` entries.
- `image.data` is base64. Images are stored one row each and written the moment you attach them, not on the debounce.
- `workspace.usage` appears only if utility spend was recorded against it.
- A conversation row holds no messages. `ensureLoaded(convo)` pulls them plus the images they reference, and nothing is evicted.
- A message missing from `messageIds` still loads, placed by its own `createdAt`.
- A run's `events` live in `runEvents`, not on the run row. The run row carries everything else:

```js
run: { id, convoId, promptMessageId, resultMessageId, reportDocId, sourceWorkspaceId,
       input, prepared, answers, checkpoint, retryFailed, settings, serverId,
       status, phase, isPreparing, preparationFailed, spend, spendLedgered,
       payload, createdAt, updatedAt }
```

`serverId` is the browser-generated id. The backend accepts it idempotently, so a run survives a lost start response. `spendLedgered` keeps spend from reaching the usage ledger twice.

## Exports

`SNAPSHOT_VERSION` is a data-contract version, not the app release number. Export builds from the tables and still carries `messages` inline; the move to Dexie did not change the shape. The reader accepts version 5 only, so neither older nor newer backups restore.

| Version | Contract change | Why older readers break |
|---------|-----------------|-------------------------|
| 1 | Initial full snapshot format. No usage ledger. | Restore leaves the current ledger alone when the snapshot has no `usage` field. |
| 2 | Adds the usage ledger to full snapshots. | Older readers cannot preserve usage when restoring or re-exporting. |
| 3 | Moves documents out of workspace records into the shared store; assistant messages can carry artifacts. | Readers expecting inline docs lose them; readers that ignore artifacts drop evidence from prompts. |
| 4 | Structured research briefs and checkpoint-aware run state. | Runs saved by older builds fail validation or recovery. |
| 5 | A workspace's single `systemPrompt` string becomes a `messages` array. | Older readers look for `systemPrompt` and miss the shared instructions. |

Merge import re-ids an imported conversation whose id already exists, so both copies survive. For documents, workspaces, runs and images your local record wins. An import with no creation time gets one, because the `createdAt` index skips rows that lack it. Restore replaces the browser-owned tables in one transaction, so a failure part-way leaves what you had.


