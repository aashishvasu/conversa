# Development

Technical reference for conversa. See the [README](README.md) for the product overview and container setup.

## Architecture

| Layer | Choice |
|-------|--------|
| Frontend | Vue 3, Vite, Tailwind CSS v4, Reka UI |
| Markdown | marked, DOMPurify, highlight.js |
| Browser storage | IndexedDB through idb-keyval |
| Backend | FastAPI and uvicorn |
| Fetching | httpx, trafilatura, pypdf |
| Authentication | PyJWT with HS256 |
| Providers | Anthropic SDK and OpenAI SDK |

```text
Browser (Vue, IndexedDB)  --HTTPS/SSE-->  FastAPI  --streaming-->  model providers
```

The browser stores conversations, settings, cards, templates, documents, images, research records, and usage. FastAPI authenticates requests, reads provider keys from environment variables, relays model streams, fetches public pages, and runs research tasks. Active research tasks and transfer payloads live in process memory.

### Backend API

`backend/main.py` constructs the app and mounts routers from `backend/api/`. `backend/api/sse.py` contains the shared SSE framing.

| Method | Path | Contract |
|--------|------|----------|
| `POST` | `/api/login` | Exchanges `APP_PASSWORD` for a signed token. |
| `POST` | `/api/refresh` | Replaces a valid token with a fresh token. |
| `GET` | `/api/settings` | Returns global defaults and `config_errors`. |
| `GET` | `/api/models` | Returns configured models as `{id, label, provider, supports_cache}`. |
| `POST` | `/api/chat` | Streams text, reasoning, tool traces, usage, and completion frames. |
| `POST` | `/api/research/prepare` | Returns `{action, goal, questions}` from the current chat context. |
| `POST` | `/api/research` | Starts or resumes a browser-named research run. |
| `GET` | `/api/research/{id}` | Returns the current run state. |
| `GET` | `/api/research/{id}/stream` | Replays events after `?after=<seq>` and tails the run. |
| `DELETE` | `/api/research/{id}` | Cancels a run. |
| `POST` | `/api/transfers` | Stores a browser export with scope `conversation` or `snapshot`. |
| `POST` | `/api/transfers/retrieve` | Returns `{scope, data}` for a live transfer phrase. |

Every route except `/api/login` requires `Authorization: Bearer <token>`. A 401 clears client authentication. Production serves the SPA and API from one origin. `CORS_ORIGINS` permits the separate Vite origin used during development.

A chat request may make several provider calls while tools run. The final `usage` frame contains summed tokens, cost, and call count. A list-valued `system` is `[stable, volatile]`; Anthropic can cache the stable block, while the other dialects join both blocks.

### Providers

A provider file in `backend/providers/` exports a `PROVIDER` dictionary. `registry.py` combines provider data and creates clients. `dialects.py` builds requests and maps provider events to conversa frames. `tool_use.py` translates provider tool calls and results.

| Dialect | Providers | API |
|---------|-----------|-----|
| `anthropic` | Anthropic | Messages |
| `responses` | OpenAI, DeepSeek | Responses |
| `chat_completions` | `compatible` | Chat Completions |

A first-class provider using an existing dialect needs a provider file and an explicit import in `registry.py`. A new wire protocol also needs a stream adapter and a `complete()` branch in `dialects.py`.

Model ids use `provider/model`, for example `openai/gpt-5.6-sol`. Bare ids resolve to Anthropic for saved-data and environment compatibility. `MODELS` adds operator-supplied ids. Pre-4.6 Anthropic models must also appear in `LEGACY_MODELS` in `backend/providers/anthropic.py`.

`apply_thinking()` maps the app's empty, `low`, `medium`, and `high` effort values:

| | Claude 4.6+ | Models in `LEGACY_MODELS` |
|---|---|---|
| Thinking | `{type: adaptive, display: summarized}` | `{type: enabled, budget_tokens: N}` |
| Effort | `output_config.effort` | `LEGACY_EFFORT_BUDGETS` |
| Temperature | omitted | sent while thinking is off |
| Token floor | `32000` | `budget + DEFAULT_MAX_TOKENS` |

Responses events map to conversa frames as follows:

| conversa frame | Responses event |
|----------------|-----------------|
| `text` | `response.output_text.delta` |
| `think` | `response.reasoning_summary_text.delta` or `response.reasoning_text.delta` |
| `search`, `fetch` | completed `web_search_call` output items |
| `results` | `url_citation` annotations |

`cost()` in `registry.py` is the pricing function. It reads the provider's per-model input and output rates, prices Anthropic cache writes at 1.25 times input and cache reads at 0.1 times input, and adds $10 per 1,000 Anthropic hosted searches. Unknown prices use `UNKNOWN_PRICE` and set `unpriced: true`. The `compatible` provider is always unpriced.

### Tools and fetching

`backend/tools/conversa_tool.py` defines provider-neutral tool calls. `runner.py` enforces round and call limits. `web.py` exposes `search_web` and `fetch_url`. Anthropic and Responses models receive these tools; the generic Chat Completions adapter receives text and optional `reasoning_content` only.

`fetch.py` accepts public HTTP and HTTPS targets. `assert_public_target()` checks the initial URL and each redirect. HTML extraction uses trafilatura, PDFs use pypdf, and JSON and plain text use content-type handlers. `PageCache` keeps extracted pages for `FETCH_CACHE_TTL_SECONDS`, defaults to 1,800 seconds, and evicts least-recently-used content above 2,000,000 characters.

Search providers run in Exa, Brave, then SearXNG order. The selected model's hosted search is the fallback. `BLOCKED_DOMAINS` applies to every finder.

### Research

`backend/research/runs.py` stores each active run as an `asyncio.Task` and event list. `gather.py` handles planning, searches, page reads, and notes. Runs have four phases: `plan`, `gather`, `gap`, and `report`.

The client creates the run id and persists it with the conversation. Reusing a retained id resumes that run. A backend restart clears active runs and allows the client to start the saved id again. One `starting` or `running` run blocks new sends in its conversation.

The final frame contains:

```text
{name, summary, report: {name, text}, sections: [{question, notes: [{note, url}]}]}
```

`frontend/src/state/store.js` saves the report as a document, links it to the conversation, records spend once, then asks the backend to forget the run.

### Transfers

`backend/transfers/phrases.py` creates five-word phrases from committed word lists. `store.py` keeps payloads in process memory until expiry. Unknown and expired phrases both return 404. Retrieval leaves the payload available until expiry.

| Variable | Default |
|----------|---------|
| `TRANSFER_TTL_SECONDS` | `3600` |
| `TRANSFER_MAX_ENTRY_BYTES` | `10000000` |
| `TRANSFER_MAX_TOTAL_BYTES` | `50000000` |
| `TRANSFER_MAX_ENTRIES` | `32` |

## Frontend

### Request assembly

`buildPayload()` in `frontend/src/prompt/payload.js` creates provider requests. `frontend/src/prompt/cards.js` handles cards and trigger matching.

The `system` content is assembled in this order:

1. Workspace prompt and system messages when `send_system_prompt` is enabled.
2. Attached workspace and conversation documents.
3. Memory when `use_memory` is enabled.
4. Triggered cards.
5. Recalled turns when `use_recall` is enabled.

Card trigger clauses are comma-separated OR terms. `&` joins required terms within a clause. Conversation card overrides use `include` and `skip`.

The `messages` array contains pinned turns followed by the send window. Pinned turns are deduplicated and bypass `num_messages_to_send`. With memory enabled, the window also includes every turn after the summary's recorded coverage. Images become provider image blocks on their original turn.

Recall scores dropped turns against the latest user message using stopword-filtered token overlap normalized by message length. It returns the top three turns in chronological order.

With `use_cache` enabled, `system` becomes `[stable, volatile]`. The workspace prompt, system messages, and documents form the stable block. Memory, cards, and recall form the volatile block.

### State and persistence

`frontend/src/state/store.js` stores browser-owned data in IndexedDB.

- A workspace is `{id, name, systemPrompt, cards, docIds}`.
- A document is `{id, name, text, createdAt, updatedAt, source, versions}`.
- Conversations link to workspaces through `workspaceId` and to documents through `docIds`.
- Documents are deleted when their final workspace or conversation reference is removed.
- Image records use separate `conversa_img:<id>` keys; messages store image ids.

Full exports use `SNAPSHOT_VERSION` and include conversations, workspaces, documents, images, research runs, settings, usage, and UI preferences. Merge import keeps local records on id collisions. Snapshot restore replaces browser-owned collections after confirmation. Older snapshots leave fields they lack unchanged.

The image pipeline accepts JPEG, PNG, GIF, and WebP. Canvas orientation and resizing cap the long edge at 2,000 pixels. Encoded records target less than 1 MB.

`frontend/src/jobs/memory.js` refreshes the summary after assistant replies. It summarizes the `summarize_n` turns above the send window and records the covered message count. The request builder sends later turns verbatim.

### Module map

| Path | Responsibility |
|------|----------------|
| `App.vue` | Application assembly, authentication state, and pane routing. |
| `api/client.js` | HTTP, SSE, authentication, chat, research, and transfer calls. |
| `state/store.js` | Conversations, workspaces, documents, images, research runs, import, and export. |
| `state/settings.js` | Global defaults and per-conversation overrides. |
| `state/usage.js` | Daily usage grouped by model and call kind. |
| `prompt/cards.js` | Card triggers, overrides, generation parsing, and effective card sets. |
| `prompt/payload.js` | Chat request assembly, send windows, recall, and cache blocks. |
| `prompt/research-input.js` | Research preparation context. |
| `jobs/` | Memory, titles, and shared utility-model calls. |
| `views/ChatPane.vue` | Composer, chat stream, and research routing. |
| `components/ResearchBlock.vue` | Research stream lifecycle and final report handoff. |
| `components/ContextPanel.vue`, `CardsPanel.vue`, `WorkspacePanel.vue` | User-managed context. |
| `components/DocRow.vue` | Document preview, revision, download, and removal. |
| `components/ui/` | Shared Reka controls and conversa styling. |
| `i18n.js`, `locales/` | EFIGS interface strings and locale setup. |
| `utils/` | Markdown, formatting, preferences, confirmation, notifications, themes, and transfer phrases. |

UI strings live in `frontend/src/locales/`. Model output, conversation content, documents, research material, backend logs, and provider errors retain their source language. `pnpm lint:i18n` checks Vue templates for untranslated interface text.

`vite-plugin-pwa` precaches the app shell. Runtime caching is disabled, and `/api` is excluded from navigation fallback so SSE responses stream directly. `registerType: 'prompt'` holds a new worker in the waiting state until the Global Settings reload button activates it; `utils/pwa.js` registers through `virtual:pwa-register/vue`, flushes IndexedDB before the reload, and disables the button when no update is waiting.

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

Use `--no-build` to skip the frontend production build. Check settings separately with:

```powershell
backend\.venv\Scripts\python.exe tools\settings-drift.py
```

Frontend checks:

```sh
cd frontend
pnpm lint:i18n
node src/selfchecks/i18n.selfcheck.js
node src/selfchecks/cards.selfcheck.js
node src/selfchecks/payload.selfcheck.js
node src/selfchecks/confirm.selfcheck.js
node src/selfchecks/md.selfcheck.js
node src/selfchecks/notify.selfcheck.js
node src/selfchecks/store.selfcheck.js
node src/selfchecks/usage.selfcheck.js
node src/selfchecks/research-lifecycle.selfcheck.js
node src/selfchecks/phrase.selfcheck.js
```

Backend checks:

```sh
cd backend
.venv/Scripts/python -m selfchecks.providers
.venv/Scripts/python -m selfchecks.api
.venv/Scripts/python -m selfchecks.auth
.venv/Scripts/python -m selfchecks.fetcher
.venv/Scripts/python -m selfchecks.topic
.venv/Scripts/python -m selfchecks.tools
.venv/Scripts/python -m selfchecks.web_tools
.venv/Scripts/python -m selfchecks.tool_runner
.venv/Scripts/python -m selfchecks.gather
.venv/Scripts/python -m selfchecks.runs
.venv/Scripts/python -m selfchecks.transfers
```

Use `.venv/bin/python` on Unix.

The wake-lock and stall-watchdog check requires a browser: start a streamed reply, background the tab for more than one minute, then return. The partial reply remains and the composer is idle.

## Container

`Containerfile` builds the frontend, copies `frontend/dist/` into `backend/static/`, and starts the backend. Files in `frontend/public/` ship with the built app.

The sidebar version comes from `frontend/package.json`. Bump it when tagging a release.
