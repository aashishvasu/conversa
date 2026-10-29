# Development

Technical reference for conversa. See the [README](README.md) for the product overview and container setup.

## Architecture

| Layer | Choice |
|-------|--------|
| Frontend | Vue 3, Vite, Tailwind CSS v4, Reka UI |
| Browser storage | IndexedDB through idb-keyval |
| Backend | FastAPI and uvicorn |
| Provider SDKs | Anthropic and OpenAI |
| Fetching | httpx, trafilatura, pypdf |

```text
Browser (Vue, IndexedDB)  --HTTPS/SSE-->  FastAPI  --streaming-->  model providers
```

The browser owns conversations, templates, workspaces, documents, images, research records, settings, and usage. The backend owns provider access, public-page fetching, and active research and transfer work. Provider API keys come from server configuration.

## Backend

### API and authentication

`backend/main.py` constructs the app and mounts routers from `backend/api/`. `backend/api/sse.py` defines shared event framing.

| Method | Path | Contract |
|--------|------|----------|
| `POST` | `/api/login` | Exchanges `APP_PASSWORD` for a signed token. |
| `POST` | `/api/refresh` | Replaces a valid token. |
| `GET` | `/api/settings` | Returns global defaults and configuration errors. |
| `GET` | `/api/models` | Returns configured models as `{id, label, provider, supports_cache}`. |
| `POST` | `/api/chat` | Streams model output, tool traces, usage, and completion frames. |
| `POST` | `/api/research/prepare` | Routes a request to chat or returns a structured research brief. |
| `POST` | `/api/research` | Starts or resumes a browser-named research run. |
| `GET` | `/api/research/{id}` | Returns current run state. |
| `GET` | `/api/research/{id}/stream` | Replays events after `?after=<seq>` and tails the run. |
| `DELETE` | `/api/research/{id}` | Cancels a run. |
| `POST` | `/api/transfers` | Stores a conversation or snapshot export for transfer. |
| `POST` | `/api/transfers/retrieve` | Returns the payload for a live transfer phrase. |

`backend/api/auth.py` handles bearer-token validation. Every route except `/api/login` requires a token carrying `exp`. A 401 clears client authentication. `CORS_ORIGINS` allows the separate Vite origin during development. `LOGIN_RATE_LIMIT` defaults to `5/minute`; the counter is per worker because it lives in process memory. Production serves the SPA and API from one origin.

`backend/api/chat.py` validates chat input, resolves enabled tools once per turn, and streams provider frames. A chat turn can make several provider calls; its final `usage` frame sums tokens, cost, and call count. List-valued `system` content represents stable and volatile blocks. Anthropic can cache the stable block; other dialects join the blocks.

### Providers

| Module | Responsibility |
|--------|----------------|
| `backend/providers/registry.py` | Combines provider definitions, resolves model ids, creates clients, and prices calls. |
| `backend/providers/dialects.py` | Builds provider requests and maps provider events to conversa frames. |
| `backend/providers/chat.py` | Runs the provider-neutral tool loop and aggregates usage. |
| `backend/providers/tool_use.py` | Translates provider tool calls and results, including hosted-tool evidence. |
| `backend/providers/anthropic.py`, `openai.py`, `deepseek.py`, `compatible.py` | Provider definitions and model-specific capabilities. |

Model ids use `provider/model`. Bare ids resolve to Anthropic for saved-data and environment compatibility; `MODELS` adds operator-supplied ids. Provider definitions export `PROVIDER` and are imported explicitly by `registry.py`. An existing dialect needs no new protocol adapter. A new wire protocol needs a stream adapter and a `complete()` branch in `dialects.py`.

`anthropic.py` owns the pre-4.6 model list and thinking-budget compatibility. `registry.py` owns per-model pricing and the unpriced fallback. Keep provider-specific request and event details with the dialect implementation and its selfchecks.

### Tools and fetching

| Module | Responsibility |
|--------|----------------|
| `backend/tools/conversa_tool.py` | Provider-neutral tool inputs and outputs. |
| `backend/tools/registry.py` | `TOOL_REGISTRY`, enabled-tool resolution, and research-stage tool sets. |
| `backend/tools/runner.py` | Executes calls and enforces per-turn round and call limits. |
| `backend/tools/web.py`, `search.py` | Search and page-reading tools. |
| `backend/tools/fetch.py`, `topic.py` | Public-target validation, page retrieval, caching, extraction, and topic windows. |
| `backend/tools/temporal.py`, `calculator.py`, `units.py`, `random_tool.py` | Local date/time, arithmetic, conversion, and random tools. |

`enabled_tools` is authoritative for chat. Unknown or duplicate names produce HTTP 400. `allow_tools` is read only when `enabled_tools` is absent, for cached clients using the older boolean request shape. Research resolves its stage tools separately from chat settings. A disabled tool is absent from the provider schema.

`fetch.py` accepts public HTTP and HTTPS targets and validates every redirect. It handles HTML, PDF, JSON, and plain text. `PageCache` stores extracted and raw variants separately. `fetch_url` accepts `topic`, `raw`, and `offset`; responses include `totalChars` and `nextOffset` for paging. Search uses Exa, Brave, then SearXNG. `BLOCKED_DOMAINS` applies to every finder.

When a local web tool is unavailable, `providers/chat.py` can use the selected model's corresponding hosted capability for the rest of the turn. Rejected calls do not trigger hosted fallback, and fallback state is tracked per tool. `runner.py` emits artifact frames only for successful opted-in calls; `tool_use.py` normalizes hosted evidence into the same frame shape.

### Research

| Module | Responsibility |
|--------|----------------|
| `backend/api/research.py` | Preparation and run endpoints, event streaming, cancellation, and run limits. |
| `backend/research/runs.py` | Iterative task frontier, coordinator, budgets, breakers, and terminal results. |
| `backend/research/gather.py` | Query generation, candidate selection, page reads, and evidence notes. |
| `backend/research/report.py` | Report sections, citation validation, and support verification. |
| `backend/research/state.py` | Checkpoint and run-state representation. |
| `backend/research/parsing.py`, `prompts.py` | Model response parsing and research prompts. |

Preparation uses the conversation's effective chat model. It either returns `answer` for the normal chat path or a structured brief with an objective, deliverable, scope, constraints, and up to three consequential questions. Clarification holds the original turn; accepting the brief starts the run. Completed research reports attached to the request can answer in place when their scope and freshness match.

The browser creates and persists a run id, original input, brief, answers, settings, and checkpoint before starting work. Reusing the id is idempotent. A backend restart can recreate work from the browser checkpoint without replaying completed operations. One active run blocks new sends in its conversation. A run can finish `done`, `partial`, or with an error; both report-bearing terminal states save a document.

Gathering runs bounded waves of tasks. The coordinator updates coverage and can redirect work to verify contradictions. Source, task, call, wave, and elapsed-time limits bound the run; defaults live in `backend/research/runs.py` and `backend/api/research.py`. Provider authentication, credit, and invalid-model failures end the run. Fetch failures remain source-local. Report generation rejects unknown evidence ids and performs one report-wide support check.

### Transfers

`backend/transfers/phrases.py` creates five-word phrases from committed word lists. `backend/transfers/store.py` holds payloads in process memory until expiry. Retrieval leaves a payload available until expiry; unknown and expired phrases both return 404.

| Variable | Default |
|----------|---------|
| `TRANSFER_TTL_SECONDS` | `3600` |
| `TRANSFER_MAX_ENTRY_BYTES` | `10000000` |
| `TRANSFER_MAX_TOTAL_BYTES` | `50000000` |
| `TRANSFER_MAX_ENTRIES` | `32` |

## Frontend

### Request assembly

`frontend/src/prompt/payload.js` builds chat requests. `prompt/cards.js` resolves workspace and conversation cards and trigger clauses. `prompt/research-input.js` assembles preparation context.

The system content order is:

1. Workspace system prompts, then conversation system messages, when `send_system_prompt` is enabled.
2. Attached workspace and conversation documents.
3. Memory when `use_memory` is enabled.
4. Triggered cards.
5. Recalled turns when `use_recall` is enabled.

Comma separates OR clauses in card triggers; `&` joins required terms. Conversation overrides `include` and `skip` change the effective card set without editing workspace cards. With `use_cache`, prompts, system messages, and documents form the stable block; memory, cards, and recall form the volatile block.

Pinned turns precede the send window, are deduplicated, and bypass `num_messages_to_send`. With memory enabled, the window includes turns after the summary's recorded coverage. Images become provider image blocks on their original turns. Recall selects up to three dropped turns by token overlap with the latest user message and returns them in chronological order.

`state/settings.js` resolves per-conversation values against global defaults. The Tools tabs control the master switch and individual tools. `enabledTools()` builds the chat allowlist when `research/orchestration.js` assembles the turn; utility-model calls use an empty allowlist.

### State and persistence

`frontend/src/state/persistence.js` owns the shared reactive state, IndexedDB keys, and debounced writes. `state/store.js` is the public facade; it owns global settings, model cache, and `initStore()`. User-owned records are exported. The model cache is server-owned and refetched after login; authentication tokens are not part of snapshots.

| Record | Shape and ownership |
|--------|---------------------|
| Workspace | `{id, name, messages, cards, docIds}`; workspace messages are shared system prompts. |
| Document | `{id, name, text, createdAt, updatedAt, source, versions}`; owners reference documents through `docIds`. |
| Image | Stored under `conversa_img:<id>`; messages keep image ids. |
| Assistant evidence | Optional `artifacts` on the assistant message that produced the evidence. |
| Research run | Browser-owned input, brief, answers, settings, checkpoint, events, and terminal result. |

Documents are removed after their final conversation or workspace reference is removed. Images are collected when no conversation message references them. Snapshot merge import keeps local records on id collisions; restore replaces browser-owned collections after confirmation. A missing field in an older snapshot leaves the current value unchanged.

`state/snapshot.js` owns full and single-conversation export, merge import, restore, and snapshot validation. `SNAPSHOT_VERSION` is a data-contract version, not the app release number. Current code accepts older understood snapshots and migrates their records on load, import, or restore. It rejects a snapshot with a version newer than the current reader, because fields or layouts may have changed in ways it cannot preserve.

| Version | Snapshot contract change | Compatibility reason |
|---------|--------------------------|----------------------|
| 1 | Initial full snapshot format. It has no usage ledger. | Restore leaves the current ledger alone when the snapshot has no `usage` field. |
| 2 | Adds the usage ledger to full snapshots. | Older readers cannot preserve usage when restoring or re-exporting the snapshot. |
| 3 | Moves documents from inline workspace records into the shared document store; assistant messages can carry tool evidence artifacts. | Readers that expect inline docs can lose them after the move; readers that do not handle artifacts cannot include that evidence in prompts. |
| 4 | Research records use structured briefs and checkpoint-aware run state. | `migrateRun()` fills the current run shape from older records; without it, valid saved runs may fail validation or recovery. |
| 5 | Workspaces replace one `systemPrompt` string with a `messages` array of system prompts. | Older readers look for `systemPrompt` and would miss the shared instructions. |

`state/workspaces.js`, `state/docs.js`, and `state/runs.js` own their record migrations. `snapshot.js` applies them on import and restore; `store.js` applies them on initial load. Raise `SNAPSHOT_VERSION` when a snapshot change needs an in-place migration or when an older reader could silently drop user data. Keep the version list here aligned with migration code and `store.selfcheck.js`.

### Frontend modules

| Path | Responsibility |
|------|----------------|
| `App.vue` | Application assembly, authentication state, and pane routing. |
| `api/client.js` | HTTP, SSE, authentication, chat, research, and transfer calls. |
| `state/persistence.js`, `state/store.js` | Shared IndexedDB state and public state API. |
| `state/conversations.js`, `workspaces.js` | Conversation, template, and workspace records. |
| `state/docs.js`, `snapshot.js` | Documents, images, garbage collection, import, export, and restore. |
| `state/runs.js`, `usage.js` | Browser research records, finalization, and usage accounting. |
| `state/settings.js` | Global defaults, per-conversation overrides, and enabled-tool allowlists. |
| `prompt/` | Request assembly, cards, artifacts, and research preparation input. |
| `research/orchestration.js`, `lifecycle.js`, `coordinator.js` | Preparation routing, stream lifecycle, and research coordination. |
| `jobs/` | Memory summaries, titles, and shared utility-model calls. |
| `views/ChatPane.vue`, `views/Sidebar.vue`, `views/UsagePane.vue` | Main chat, navigation, and usage screens. |
| `components/` | Message display, settings, context panels, documents, research, notifications, and transfers. |
| `composables/` | Image attachment, auto-scroll, textarea sizing, and stream guard logic. |
| `utils/` | Markdown, formatting, preferences, confirmation, notifications, themes, and transfer phrases. |
| `i18n/index.js`, `locales/` | EFIGS interface strings and locale setup. |
| `styles/style.css` | Theme tokens and shared styles. |

Tool evidence moves from backend artifact frames to assistant-message `artifacts` in `research/orchestration.js`. `prompt/artifacts.js` serializes evidence into later model context and adds the trust instruction when evidence is present. Memory and recall retain the evidence with its message. Editing an assistant message's text or role clears its artifacts; cancelling an edit keeps them.

`jobs/memory.js` refreshes the summary after assistant replies. It summarizes `summarize_n` turns above the send window and records the covered message count; the request builder sends later turns verbatim.

`utils/pwa.js` registers the service worker through `virtual:pwa-register/vue`. Vite precaches the app shell and disables runtime caching. `/api` is excluded from navigation fallback so SSE remains a stream. The worker waits for the Global Settings reload action; IndexedDB is flushed before reload, and the action is disabled when no update is waiting.

## Local development

Run the backend and frontend separately. Vite proxies `/api` to port 8000.

Backend:

```sh
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env
.venv/Scripts/python -m uvicorn main:app --reload --port 8000
```

Use `.venv/bin/python` on Unix. Set `APP_PASSWORD` and at least one provider key in `backend/.env`.

Frontend:

```sh
cd frontend
pnpm install
pnpm dev
```

Production build:

```sh
pnpm --dir frontend build
```

## Checks

Run the full repository check from the root:

```powershell
backend\.venv\Scripts\python.exe tools\check.py
```

Use `--no-build` to skip the frontend production build. Run the settings drift check separately with:

```powershell
backend\.venv\Scripts\python.exe tools\settings-drift.py
```

The full check runs frontend locale lint and selfchecks, backend selfchecks, then the production frontend build. The selfchecks are split by owning module under `frontend/src/selfchecks/` and `backend/selfchecks/`.

The wake-lock and stall-watchdog check requires a browser: start a streamed reply, background the tab for more than one minute, then return. The partial reply remains and the composer is idle.

## Container

`Containerfile` builds the frontend, copies `frontend/dist/` into `backend/static/`, and starts the backend. Files in `frontend/public/` ship with the built app.
