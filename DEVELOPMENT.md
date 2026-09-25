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
| `POST` | `/api/chat` | Streams text, reasoning, tool traces, usage, and completion frames; `enabled_tools` fixes the callable tool set for the turn. |
| `POST` | `/api/research/prepare` | Returns `{action, goal, questions}` from the current chat context. |
| `POST` | `/api/research` | Starts or resumes a browser-named research run. |
| `GET` | `/api/research/{id}` | Returns the current run state. |
| `GET` | `/api/research/{id}/stream` | Replays events after `?after=<seq>` and tails the run. |
| `DELETE` | `/api/research/{id}` | Cancels a run. |
| `POST` | `/api/transfers` | Stores a browser export with scope `conversation` or `snapshot`. |
| `POST` | `/api/transfers/retrieve` | Returns `{scope, data}` for a live transfer phrase. |

Every route except `/api/login` requires `Authorization: Bearer <token>`. A token must carry `exp`. A 401 clears client authentication. Production serves the SPA and API from one origin. `CORS_ORIGINS` permits the separate Vite origin used during development. `/api/login` accepts `LOGIN_RATE_LIMIT` attempts per client IP (default `5/minute`) and answers 429 past that; the counter is in-process, so it applies per worker.

A chat request may make several provider calls while tools run. The final `usage` frame contains summed tokens, cost, and call count. A list-valued `system` is `[stable, volatile]`; Anthropic can cache the stable block, while the other dialects join both blocks.

### Providers

A provider file in `backend/providers/` exports a `PROVIDER` dictionary. `registry.py` combines provider data and creates clients. `chat.py` runs the tool loop and aggregates usage across provider calls within one chat turn. `dialects.py` handles wire translation: building requests and mapping provider events to conversa frames. `tool_use.py` translates provider tool calls and results.

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

`backend/tools/conversa_tool.py` defines provider-neutral tool calls. `registry.py` holds `TOOL_REGISTRY`, keyed by name, and `resolve_enabled_tools()`. `runner.py` enforces round and call limits. Anthropic and Responses models receive the resolved tools as part of their request; the generic Chat Completions adapter receives text and optional `reasoning_content` only, never tools.

Five tools are registered: `search_web` and `fetch_url` (`web.py`), `datetime` (`temporal.py`), `calculator` (`calculator.py`, with unit conversions in `units.py`), and `random` (`random_tool.py`). Every tool declares `artifact_fresh_for`: `search_web` and `fetch_url` opt into artifact history (1,800 seconds, matching `FETCH_CACHE_TTL_SECONDS`); the others pass `None` and keep none.

`/api/chat`'s `enabled_tools` is the authoritative list for the turn; `resolve_enabled_tools()` looks up each name in `TOOL_REGISTRY` and raises `ToolConfigError` (surfaced as HTTP 400) on an unknown or duplicate name. The legacy `allow_tools` boolean is read only when `enabled_tools` is omitted, mapping `true` to `DEFAULT_WEB_TOOLS` (`search_web`, `fetch_url`) for callers on a cached frontend that predates the per-tool schema. `backend/api/chat.py` resolves the list once per turn; a disabled tool is absent from the resulting provider schema. Research runs resolve tools separately: `RESEARCH_STAGE_TOOLS` maps each research stage to tool names and `resolve_research_tools()` resolves them without reading chat tool settings, so starting research never mutates the chat tool set.

`fetch.py` accepts public HTTP and HTTPS targets. `assert_public_target()` checks the initial URL and each redirect. HTML extraction uses trafilatura, PDFs use pypdf, and JSON and plain text use content-type handlers. `PageCache` keeps whole pages (extracted and raw variants keyed separately) for `FETCH_CACHE_TTL_SECONDS`, defaults to 1,800 seconds, and evicts least-recently-used content above 2,000,000 characters. `fetch_url` serves one window per call: `topic` selects the relevant sections (capped at 40,000 characters), an omitted `topic` reads the whole page, `raw` returns the page's HTML source instead of the extraction (ignoring `topic`), and `offset` pages through whatever was requested. Every response carries `totalChars` and `nextOffset` so the model can continue or stop; the per-call window is 100,000 characters and cached content is capped at 500,000 with a truncation note.

Search providers run in Exa, Brave, then SearXNG order. `BLOCKED_DOMAINS` applies to every finder. When the app's `search_web` or `fetch_url` is unavailable, `backend/providers/chat.py` falls back to the selected model's matching hosted capability (Anthropic hosted search/fetch, OpenAI hosted search) for the rest of the turn, tracked independently per tool. A rejected call (`ToolRejected`, for example a blocked domain) blocks that tool's hosted fallback for the turn instead of triggering it; an unavailable local tool never enables the hosted counterpart of a different tool, and a failure in one tool leaves the rest of the enabled set available.

`datetime` (`temporal.py`) supports `now`, `add`, and `difference` against IANA zones. `now` and results carry the zone's current UTC offset. Aware ISO-8601 input converts to the target zone; naive input is treated as wall time in that zone. `add` takes either elapsed units (seconds/minutes/hours, plus weeks/days) or calendar units (years/months, plus integer weeks/days); mixing the two families is rejected. Calendar addition preserves wall time and clamps the day to the target month's last day (adding one month to January 31 lands on the last day of February). A nonexistent spring-forward wall time advances to the post-transition instant; an ambiguous fall-back wall time keeps the earlier offset (`fold=0`). `difference` reports only elapsed time between two timestamps, never a calendar breakdown.

`calculator` (`calculator.py`) evaluates expressions by walking a parsed `ast.Expression` against an operator and function allowlist; it never calls `eval`. Bounds cap expression length, node count, exponent magnitude, factorial input, and result bit length. Unit conversion (`units.py`) covers length, mass, duration, data size (case-sensitive, so `MB` and `Mb` differ), speed, area, volume, pressure, energy, and temperature; US customary volume units (cups, pints, quarts, gallons, tablespoons, teaspoons, fluid ounces) require an explicit `_us` suffix because the bare names are ambiguous with imperial units.

`random` (`random_tool.py`) draws from `secrets.SystemRandom()` by default, so calls are not reproducible. Passing an integer `seed` switches to `random.Random(seed)`, making that call's output reproducible. Actions are `integers` (inclusive range), `sample` (with or without replacement), and `shuffle`.

### Tool evidence artifacts

Tool execution stays ephemeral; only the client keeps durable state. An opted-in tool returns a client-safe provenance record in `ToolOutput.artifact` (built by the tool itself, never derived from `ToolResult.content`, which is model-facing). On success `runner.py` emits an SSE `artifact` frame `{tool, recordedAt, freshUntil, input, output}`; errors, rejections, and budget-limited calls emit nothing. Hosted fallback web tools bypass the runner, so `tool_use.py`'s `hosted_artifacts()` normalizes the provider response into the same frames, keeping only queries, URLs, and result titles (hosted fetch bodies can be base64 PDFs and never enter durable state).

The frontend attaches each artifact to the assistant message that produced it (`research/orchestration.js`), so persistence, exports, cloning, deletion, and regeneration handle it with no second store. `prompt/artifacts.js` serializes artifacts into the outgoing assistant text (a stale record is marked so the model refetches when freshness matters), and adds a fixed trust instruction to the volatile system half only when evidence is in context, preserving the cached stable prefix. Recall and the memory summary include artifact evidence. Editing an assistant message's text or role clears its artifacts (`ChatPane.vue`); cancelling the edit keeps them.

### Research

Research preparation uses the conversation's effective chat model, and `PREPARE_SYSTEM` routes the request to either `answer`, which continues through normal chat, or a structured brief with an objective, deliverable, scope, constraints, and up to three consequential questions. When attached reference documents include a completed research report covering the request, it returns `answer` and uses it; `research` comes back only for a new investigation or a request outside the report's scope or freshness. The browser persists the original preparation input, brief, answers, selected research models, and browser-generated run id before starting work. A failed preparation retries against that same durable turn instead of appending another message.

The research source target is configured through `research_min_sources` (default 8) and `research_max_sources` (default 24). The frontend presents both values through a single dual-thumb range slider, and both the frontend and API clamp the settings so `min_sources >= 8`, `max_sources <= 300`, and `min_sources <= max_sources`.

Per-run budgets derive from `max_sources`:

- `max_calls = max_sources * 2 + MAX_TASKS + MAX_WAVES + 4`, the 4 covering report sections and passes.
- `max_elapsed = max(RESEARCH_MAX_SECONDS, max_sources * 15.0)`.
- The wave-loop call breaker fires at `budget["calls"] >= max_calls - REPORT_RESERVE`, reserving calls for report writing and citation verification.

`backend/research/runs.py` owns an iterative frontier. Each wave starts up to three pending tasks, and a coordinator resolves, prunes, merges, or adds tasks from the combined findings. Per task, `gather.py` reformulates the question into up to three query variants through the run's search model (cached in checkpoint operations, counted as one budgeted call), triages the widened hit scan into top candidates in a single batched utility-model call, then fetches the survivors concurrently under `FETCH_CONCURRENCY`. The note model may page a source through `fetch_url`'s `offset`, capped at three windows. Note replies validate against a schema of `relevant`, `gist`, and `claims`, each claim carrying `text`, `stance`, `confidence`, and `as_of`; recorded evidence keeps `excerpt` and `claims`. The legacy duplicate `note` key is no longer emitted, but readers tolerate it on older checkpoints.

The coordinator works from a bounded projection: evidence gists capped at 240 characters, new evidence ids, worker gaps, exhausted queries, budgets, per-scope coverage counts, and the working `theory`, which it updates each wave (`hypothesis`, `confidence`, `supporting`, `contradicting`, `revised_at_wave`). When theory reports contradicting evidence or claims on one question carry opposing stances, the loop adds at most one contradiction-verification task per wave within `MAX_TASKS`, flips the coordinator's `finish` to `continue`, and logs it in `decision["forced_redirection"]`. `run.data["coverage"]` maps each brief scope item to supporting evidence ids as evidence lands, and `report.py` groups that ledger into section batches written within the remaining budget.

`state.py` manages run checkpoints using checkpoint version 2 (`CHECKPOINT_VERSION = 2`). A checkpoint stores the brief, frontier, canonical source registry, evidence, gaps, decisions, budgets, completed operations, `theory`, and `coverage`. Version 1 checkpoints remain valid and migrate automatically with empty theory and coverage defaults on resume. Checkpoints stream to the browser after state transitions; a missing backend run restarts from the latest browser checkpoint without replaying completed operations.

URL canonicalization removes fragments and tracking parameters and deduplicates sources across the whole run. Breakers bound duplicate queries, task attempts, repeated fetch failures, no-progress waves, elapsed time, provider calls, tasks, and unique sources; budgets are rechecked after each wave's gather, and the elapsed budget accumulates across checkpoint resumes. Fetch failures carry their HTTP status and stay per-source: a paywalled or bot-blocked page records `source_failed` and the run continues. Only provider authentication, credit, and invalid-model failures end the run with their detail. A coverage gate rejects the coordinator's first `finish` while the run holds fewer than `run.min_sources` (default 8) evidence items or a scope item has neither matching evidence nor an acknowledging gap; the second finish passes. A run with useful evidence can end `partial` when a breaker or unresolved citation gap prevents a complete answer.

`report.py` asks the writer to cite evidence IDs, rejects unknown IDs, runs one whole-report support-verification and correction pass over the stitched sections, then renders IDs as links to registered source URLs. A report-generation error retains the checkpoint and exposes recovery with the current research models.

The client owns run ids and durable state. Reusing a retained id reconnects to that run; after a backend restart it recreates the run from the checkpoint. `POST /api/research` answers with an `outcome` of `created`, `resumed_from_checkpoint`, `restarted`, `already_running`, or `already_finished`, plus a compatible `resumed` boolean that is true for every outcome except `created`; restarts emit a `resumed` event, and a restart with no pending tasks emits a breaker and finishes from the checkpoint. One `starting`, `waiting_for_clarification`, or `running` run blocks new sends in its conversation. `MAX_ACTIVE_RUNS` (default 2) caps concurrent server runs. Environment variables `RESEARCH_MAX_WAVES` (default 8), `RESEARCH_MAX_TASKS` (default 18), `RESEARCH_MIN_SOURCES` (default 8), `RESEARCH_MAX_SOURCES` (default 24), `RESEARCH_MAX_CALLS` (default 48), `RESEARCH_MAX_SECONDS` (default 900), and `RESEARCH_MIN_EVIDENCE` provide baseline defaults; active run budgets derive dynamically from the request settings. `DEFAULT_RESEARCH_DEPTH` (default 5) in `research/runs.py` is the single depth default; `/api/settings` serves it as `research_depth` and the API clamps requests to 1-12.

The terminal payload contains the report plus its audit material:

```text
{name, summary, report: {name, text}, sections, evidence, sources, gaps, decisions}
```

`frontend/src/state/runs.js` saves `done` and `partial` reports as documents, links them to the conversation, and records spend once. Saved report documents prepend a `## Research provenance` header with the completion timestamp, gathered and failed source counts, model call count and cost, waves run, fired caps, summary, gaps, and decisions. `ResearchBlock.vue` shows the evolving task/source/evidence trace, persists each checkpoint, and forgets the backend run only after terminal state is durable.

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

The Tools tabs in Global Settings and Conversation Settings control a master switch and each registered tool. Conversation values inherit global settings until overridden. `enabledTools()` in `state/settings.js` builds the allowlist once when `research/orchestration.js` assembles a chat turn; utility-model calls send an empty allowlist. Disabled definitions do not enter the provider request.

### State and persistence

`frontend/src/state/` splits browser state across several modules. `persistence.js` holds the shared reactive state, IndexedDB keys, and debounced writes. `store.js` is the public facade: it re-exports all public APIs from the sub-modules and owns global settings, models, and `initStore`.

- A workspace is `{id, name, systemPrompt, cards, docIds}`.
- A document is `{id, name, text, createdAt, updatedAt, source, versions}`.
- Conversations link to workspaces through `workspaceId` and to documents through `docIds`.
- Documents are deleted when their final workspace or conversation reference is removed.
- Image records use separate `conversa_img:<id>` keys; messages store image ids.
- An assistant message may carry `artifacts`, the durable tool-evidence records described under Tool evidence artifacts. Pre-v3 snapshots lack the field; it simply stays absent.

`snapshot.js` implements full export and restore. Full exports use `SNAPSHOT_VERSION` and include conversations, workspaces, documents, images, research runs, settings, usage, and UI preferences. Merge import keeps local records on id collisions. Snapshot restore replaces browser-owned collections after confirmation. Older snapshots leave fields they lack unchanged.

The image pipeline accepts JPEG, PNG, GIF, and WebP. Canvas orientation and resizing cap the long edge at 2,000 pixels. Encoded records target less than 1 MB.

`frontend/src/jobs/memory.js` refreshes the summary after assistant replies. It summarizes the `summarize_n` turns above the send window and records the covered message count. The request builder sends later turns verbatim.

### Module map

| Path | Responsibility |
|------|----------------|
| `App.vue` | Application assembly, authentication state, and pane routing. |
| `api/client.js` | HTTP, SSE, authentication, chat, research, and transfer calls. |
| `state/persistence.js` | Shared reactive state, IndexedDB keys, and debounced persistence. |
| `state/store.js` | Public facade: re-exports from sub-modules; owns global settings, models, and `initStore`. |
| `state/conversations.js` | Conversation and template CRUD, `attachedDocs`. |
| `state/runs.js` | Research run CRUD, finalization, and spend recording. |
| `state/workspaces.js` | Workspace CRUD. |
| `state/docs.js` | Document and image CRUD and GC. |
| `state/snapshot.js` | Export, import, restore, and snapshot info. |
| `state/settings.js` | Global defaults, per-conversation overrides, and enabled-tool allowlists. |
| `state/usage.js` | Daily usage grouped by model and call kind. |
| `prompt/cards.js` | Card triggers, overrides, generation parsing, and effective card sets. |
| `prompt/artifacts.js` | Tool-evidence serialization and the fixed trust instruction. |
| `prompt/payload.js` | Chat request assembly, send windows, recall, and cache blocks. |
| `prompt/research-input.js` | Research preparation context. |
| `jobs/` | Memory, titles, and shared utility-model calls. |
| `views/ChatPane.vue` | Composer and message management, delegates to composables and `research/orchestration.js`. |
| `composables/useImageAttachments.js` | Image attachment lifecycle for the composer. |
| `composables/useAutoScroll.js` | Chat scroll management. |
| `composables/useAutoGrowTextarea.js` | Textarea auto-grow. |
| `research/orchestration.js` | Streaming, research routing, live trace, and stream guard. |
| `components/ConversationRow.vue` | Shared sidebar conversation row. |
| `components/ResearchBlock.vue` | Research stream lifecycle and final report handoff. |
| `components/ContextPanel.vue`, `CardsPanel.vue`, `WorkspacePanel.vue` | User-managed context. |
| `components/DocRow.vue` | Document preview, revision, download, and removal. |
| `components/ui/` | Shared Reka controls and conversa styling. |
| `styles/style.css` | Theme tokens and shared styles. |
| `i18n/index.js`, `locales/` | EFIGS interface strings and locale setup. |
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
node src/selfchecks/settings.selfcheck.js
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
.venv/Scripts/python -m selfchecks.fetch
.venv/Scripts/python -m selfchecks.topic
.venv/Scripts/python -m selfchecks.tools
.venv/Scripts/python -m selfchecks.registry
.venv/Scripts/python -m selfchecks.temporal
.venv/Scripts/python -m selfchecks.calculator
.venv/Scripts/python -m selfchecks.random_tool
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
