# Development

Technical reference for working on conversa.
For what the app does and how to run the released container, see the [README](README.md).

## Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | **Vue 3 + Vite** | Reactive SPA with Vite development and production builds. |
| Styling | **Tailwind CSS v4** | Semantic CSS-variable tokens that flip on `.dark`. |
| Icons | **@lucide/vue** | Consistent outline set. |
| Markdown | **marked** + **DOMPurify** + **highlight.js** | Render, sanitize, highlight. Sanitizing is the security boundary. |
| Client storage | **IndexedDB** (via `idb-keyval`) | Browser-local persistence for conversation state and documents. |
| Backend | **FastAPI** + **uvicorn** | Async proxy to the model providers, plus the fetcher and the research run loop. |
| Fetching | **httpx** + **trafilatura** + **pypdf** | Manual redirect control for the SSRF guard, readable-text extraction that keeps fenced code blocks, and PDF text. |
| Auth | **PyJWT** (HS256) | Password is exchanged once for a signed, expiring token. |
| LLM | **Anthropic Python SDK** + **OpenAI Python SDK** | `messages.stream()` and `responses.create(stream=True)`, both mapped onto one SSE format. |

## Architecture

IndexedDB stores messages, settings, cards, templates, and memory.
FastAPI authenticates requests, reads provider keys from its environment, relays model streams, and holds active research runs in process memory. A process restart ends those runs.

```
Browser (Vue SPA, IndexedDB)  --HTTPS-->  FastAPI  --streaming-->  Model APIs
   conversation state                 keys + password
```

### Backend endpoints (`backend/main.py`)

- `POST /api/login`: exchanges `APP_PASSWORD` (constant-time compared) for a signed, expiring JWT.
- `POST /api/refresh`: trades a still-valid token for a fresh full-TTL one.
  The client calls it opportunistically once a token is past half-life (sliding session).
- `GET  /api/settings`: global setting defaults from env vars, plus `config_errors` (see Providers below).
- `GET  /api/models`: selectable models as `{id, label, provider, supports_cache}`, filtered to configured providers. `supports_cache` is a dialect property (Anthropic only), not a per-model one; `SettingsPanel.vue`/`GlobalSettings.vue` disable the cache checkbox and explain why when the effective model can't use it. Effort has the same gap (`takes_reasoning()`'s `reasoning_prefixes` check) and is not flagged yet.
- `POST /api/chat`: streams a completion as SSE from the provider that owns the requested model.
  The server environment supplies API keys. The provider layer translates `effort`, attaches configured hosted tools, and emits text, thinking, and tool-trace events (`search`, `fetch`, `results`), plus one `usage` frame (`{model, input, output, cache_read, cache_write, usd, unpriced}`, priced server-side) before `done`.
  `main.py` JSON-encodes each event so newlines and special characters remain inside one SSE frame.
  A list-valued `system` is `[stable, volatile]`: the Anthropic dialect marks the first block for prompt caching (`use_cache`, off by default); the other dialects rejoin it.
- `POST /api/fetch`: returns readable markdown from a URL (`backend/fetcher.py`).
  With a `topic`, `backend/topic.py` returns the sections matching that topic.
- `POST /api/research/clarify`: returns 3 to 5 questions about a brief. Their answers become part of the brief read by the planner.
- `POST /api/research`: starts a run and returns its id.
  `GET /api/research/{id}` reads its state, `GET /api/research/{id}/stream` replays from `?after=<seq>` then tails live as SSE, `DELETE /api/research/{id}` cancels it.

All endpoints except `/api/login` require `Authorization: Bearer <token>`.
`/api/login`, `/api/refresh`, and the `require_auth` dependency the other routes depend on live in `backend/auth.py`.
A 401 logs the client out automatically.
Production serves the SPA and API from one origin through the `StaticFiles` mount. `CORS_ORIGINS` configures the separate Vite origin used in development.

### Provider layer (`backend/providers/`)

Each first-class provider has one file exporting a `PROVIDER` dict. `providers/registry.py` combines them and owns keys, clients, model ids, and defaults; `providers/dialects.py` owns request construction, provider event parsing, streaming, and `complete()`.
`providers/__init__.py` is the import facade. `main.py` owns the FastAPI boundary and SSE framing, `research.py` owns gathering, and `runs.py` owns the run loop. Dependency direction is `main.py`, `research.py`, and `runs.py` -> `providers`.

### Research runs (`backend/runs.py`, `backend/research.py`)

`runs.py` owns the run lifecycle: a run is an `asyncio.Task` plus an event list held in the `RUNS` dict.
Runs continue after the client closes its tab and end when the process restarts. The browser stores the brief.

Phases are plan, gather, gap, report.
Gather fans out one coroutine per subquestion under a semaphore; each searches, fetches, and writes notes, then drops the document.
The search, fetch and note-taking stages live in `research.py`, with `PageCache`, `Spend`, and the prompts; `runs.py` imports them.
A run retains notes and source URLs. Page bodies are released after note-taking, keeping retained memory proportional to the notes.

`search()` tries configured app finders in Exa, Brave, SearXNG order, then the search model's hosted tool. Each query logs its finder to the uvicorn console; a failed finder logs its error before the next attempt.
`BLOCKED_DOMAINS` controls hosted-tool source quality by asking Anthropic for replacements and filtering results from other finders through `is_blocked`.
Subquestions overlap enough that one canonical source gets picked repeatedly, so `PageCache` downloads each URL once per run and topic-selects it per subquestion, which keeps the notes distinct while paying for one fetch.

A research run makes about 30 model calls. The SDK retries transient failures up to 5 times.
A source failure drops that source; a search failure drops that subquestion; a report failure returns the collected notes.
The SSE stream emits a 1-second `tick` to keep idle proxies open during long phases.

`PROMPTS` is the tuning surface and a request may override any key.
The finished payload is a workspace containing the report as a doc and per-subquestion notes as `q1`..`qN` cards. Cards enter the prompt when their trigger is active.

### Fetching (`backend/fetcher.py`, `backend/topic.py`)

Ported from [magpi](https://github.com/grainologic/magpi) (MIT). trafilatura extracts HTML and keeps fenced code blocks; a content-type branch handles JSON and plain text; a Wayback lookup retries 403/404/410/451.

`assert_public_target()` is the security boundary for caller-supplied URLs. It accepts HTTP(S) public targets and checks every redirect hop before following it.
DNS resolution and connection remain separate, permitting rebinding between them. A pinned-IP transport would close that gap.

### The provider registry (`backend/providers/`)

Providers are data, dialects are code.
Each first-class provider file exports a dict naming its `dialect` (`anthropic`, `responses`, or `chat_completions`), key env var, selectable models, and any dialect-specific data such as `base_url`, `search_tool`, or `reasoning_prefixes`.
`providers/registry.py` imports those modules explicitly. Keys, clients, `CONFIGURED`, and `BUILTIN_MODELS` derive from their entries.

The dialect is the wire protocol, and there are three: Anthropic messages, OpenAI Responses, and OpenAI chat.completions. `providers/dialects.py` contains one stream adapter per protocol and maps each provider's events onto conversa event dictionaries. `main.py` JSON-encodes those dictionaries as SSE.
A provider with its own protocol needs another adapter plus its `complete()` branch. A provider that implements an existing dialect needs only its file and registry import.

DeepSeek uses Responses because that endpoint carries its reasoning stream, hosted web search, and image input.
`compatible.py` configures one chat.completions endpoint from one key and base URL. `MODELS` supplies its `compatible/` model ids. It exchanges text plus optional `reasoning_content`; research uses Exa, Brave, or SearXNG.

### Model ids (`split_model`, `parse_models` in `backend/providers/registry.py`)

A model id carries its provider as a prefix: `openai/gpt-5.6-sol`. `split_model()` splits on the last `/`; bare ids belong to Anthropic for saved-conversation and environment compatibility.

Everything downstream of the dropdown treats the id as opaque. `/api/models` contains models from configured providers. Operator-supplied `MODELS` entries with incomplete configuration, plus unselectable default models, produce `config_errors` in `/api/settings`; `App.vue` shows them in a dismissible banner.

### Responses specifics (`_responses_stream` in `backend/providers/dialects.py`)

OpenAI and DeepSeek use the **Responses API** for hosted web search, reasoning, and text output.
The event mapping onto conversa's own SSE frames:

| conversa frame | Responses event |
|---|---|
| `text` | `response.output_text.delta` |
| `think` | `response.reasoning_summary_text.delta` (OpenAI) or `response.reasoning_text.delta` (DeepSeek) |
| `search` / `fetch` | `response.output_item.done` where the item is a `web_search_call` (`action.type` of `search` or `open_page`) |
| `results` | `response.output_text.annotation.added` with a `url_citation` |

`reasoning_prefixes` in `providers/openai.py` decides which OpenAI models take `reasoning.effort` and reject `temperature`; DeepSeek's missing list means every model in its file reasons.
`summary: "auto"` is what makes reasoning text stream.
Effort remains a hint: at `low` with a short system prompt these models often return no reasoning item, which reaches the UI as an empty trace.
`field()` reads SDK objects and plain dicts alike, so an annotation shape that changes between SDK versions costs one trace event and the stream continues.

### Usage and pricing (`backend/providers/registry.py`, `backend/providers/dialects.py`)

`cost()` in `registry.py` is the one pricing function: base input/output rate from the provider entry's `prices` dict, a cache write at 1.25x and a cache read at 0.1x that same input rate, and Anthropic's hosted `web_search` tool at $10 per 1,000 uses. An unpriced model falls back to `UNKNOWN_PRICE`, the top tier, and reports `unpriced: true`. Every first-class provider has a `prices` entry except `compatible`, which stays unpriced: it is an operator-configured endpoint this codebase has no rate for.
`Spend` (also in `registry.py`) accumulates calls through `cost()` and keeps a per-model breakdown in `as_dict()["models"]`, including that row's own `unpriced` count; research owns one `Spend` per run, and it is what backs the research pane and sidebar spend display and what the research fold hands to the client-side ledger.
DeepSeek's `PRICES` in `providers/deepseek.py` is the peak-hours cache-miss rate; `cost()` has no per-provider cache multiplier or time-of-day rate yet, so DeepSeek's cheaper cache-hit and off-peak pricing both currently read as full-rate spend.
Three pure functions extract token and cache counts from each dialect's usage shape, shared by the streaming adapters and by `complete()`'s utility-call path: `anthropic_usage()` reads `message.usage` directly; `responses_usage()`/`responses_usage_from()` split the streamed `response.completed` event from the usage object inside it; `chat_completion_usage()`/`chat_completion_usage_from()` do the same for the chunk `stream_options.include_usage` attaches.
`_chat_completions_stream` always sends `stream_options: {"include_usage": true}`; an OpenAI-compatible endpoint that rejects the parameter would 400 the whole stream, unverified without a key.

On the frontend, `usage.js` is the client-side ledger: day buckets, one row per model per kind (`chat`, `utility`, `research`), persisted to IndexedDB like `store.js`. `streamChat`'s `onUsage` callback feeds it from all four call sites (`ChatPane.vue`, `memory.js`, `titles.js`, `CardsPanel.vue`'s card builder); each also folds the same frame into `convo.usage`, a flat running total for that conversation. A finished research run folds its `Spend.as_dict().models` breakdown into the ledger once, guarded by `spendLedgered` on the persisted run record so a reconnect or reopen replaying the same `final` frame does not double it.
The ledger joins the full snapshot export/restore (see Workspaces above). `components/SpendBadge.vue` renders `{calls, input, output, usd, unpriced}` in the research pane, chat footer via `convo.usage`, and each Usage-pane table row. `views/UsagePane.vue` reads the ledger by model and kind over an optional native date range.

### chat.completions specifics (`_chat_completions_stream` in `backend/providers/dialects.py`)

The generic compatibility entry uses this dialect. `text` comes from `delta.content`; `reasoning_content` becomes `think` when a provider sends it.
The compatibility adapter maps text and optional `reasoning_content`. `join_system` places the system prompt first; research uses app finders.

### Thinking effort (`apply_thinking` in `backend/providers/dialects.py`)

The wire format for extended thinking split across model generations, so one branch translates the single `effort` lever (`""` / `low` / `medium` / `high`) per model:

| | Claude 4.6+ | Pre-4.6 (`LEGACY_MODELS`) |
|---|---|---|
| Thinking | `{type: adaptive, display: summarized}` | `{type: enabled, budget_tokens: N}` |
| Depth control | `output_config.effort` | `LEGACY_EFFORT_BUDGETS` (4000/10000/24000) |
| `temperature` | **never sent**, since Opus 4.7+ reject it outright | sent, unless thinking is on |
| `max_tokens` | floored at 32000 (thinking spends from it) | floored at `budget + DEFAULT_MAX_TOKENS` |

`display: summarized` supplies text for ChatPane's live thinking trace; Anthropic's `omitted` default yields empty thinking blocks.
Unknown model ids are treated as modern.
`LEGACY_MODELS` in `providers/anthropic.py` is a hand-maintained set of older ids, so adding a pre-4.6 model to `MODELS` means adding its id there too.
The three lever words (`low` / `medium` / `high`) are `EFFORT_VALUES`; Claude, OpenAI, and DeepSeek accept them verbatim. The generic compatibility path sends no effort parameter because chat.completions has no standard name for it.
Covered by `python -m providers`.

### How a request is assembled (`frontend/src/cards.js`)

`buildPayload(convo, settings, workspace, docs)` assembles the provider request; the two call sites (ChatPane, DebugPanel) resolve `workspace` with `workspaceOf(convo)` and `docs` with `attachedDocs(convo)`.

- **`system` param** gets the workspace's shared prompt (if `send_system_prompt`), then all system messages (same gate), the attached documents in full, the memory summary (if `use_memory`), and the content of any triggered cards.
  The card scan runs over workspace cards and convo cards together, workspace first (`effectiveCards`).
  `convo.cardOverrides[cardId]` = `'include'` / `'skip'` replaces a workspace card's force for that one conversation.
  Card triggers are comma-separated clauses (comma = OR, `&` inside a clause = AND).
  Each card is prefixed with the clause that triggered it (`phrase: content`); force-include cards with no matching clause send bare content.
- **`messages` array** gets pinned turns first (deduped), then the *send window* (the last `num_messages_to_send` turns; with memory on, everything past the summary's coverage, floored at `num_messages_to_send`).
  This array contains user and assistant turns; system content uses the separate `system` field.
- **recall** (if `use_recall`) also rides in `system`: the top `RECALL_COUNT` (3) *dropped* turns (neither pinned nor in the window), scored by stopword-filtered token overlap with the latest user message, normalized by sqrt(length), returned chronologically.
  Recall selects original turns on each request, so later edits and deletions affect its results.
- **model / temperature / max_tokens / effort** are passed through from the effective settings.

Pinned turns bypass the send-window limit; this does **not** enforce user/assistant alternation, so wildly mixed pins could be rejected by the API.

With `use_cache` on, `system` has `[stable, volatile]` form.
The stable half is everything above the memory summary: workspace prompt, system messages, attached documents.
`anthropic_system()` in `providers/dialects.py` marks the first block ephemeral, billing a large workspace once per cache window. Responses and chat.completions receive the halves joined as one string.
The order is what makes this work: prompt caching is prefix-match, and cards are assembled last, so a card firing mid-conversation rewrites only the uncached tail.
Messages stay uncached because the send window drops turns off the front as it slides, which changes the message prefix on most turns.

### Workspaces (`frontend/src/store.js`)

A workspace is `{ id, name, systemPrompt, cards, docIds }` in its own IndexedDB key, persisted through the same debounced save as conversations.
A conversation joins by setting `convo.workspaceId`; `workspaceOf(convo)` resolves it (null for a missing or deleted workspace, which degrades to plain-convo behavior everywhere).
The merge into the request happens at read time in `buildPayload`, so joining, leaving, and deleting a workspace touch only that pointer.
Full export is a versioned snapshot (`SNAPSHOT_VERSION` in `store.js`) carrying everything IndexedDB holds that is the user's rather than the deployment's: conversations, workspaces, docs, runs, saved settings, the usage ledger, and UI prefs. The models cache is excluded on purpose (server-owned, refetched after login) and the auth token never enters a snapshot at all. A snapshot from an older version still restores; a field that version never had (the usage ledger, before usage.md) is left untouched rather than wiped, since replace-all only replaces what the snapshot actually claims to hold, and pre-v3 snapshots that held docs inline on workspaces have them hoisted into the doc store on restore. Merge import also accepts the older bare-array format, keeps local workspaces and docs on id collision so existing links stay resolvable, and ignores snapshot-only settings, usage, and prefs. Restore replaces every collection after an explicit confirmation.

### Documents (`frontend/src/store.js`)

A doc is `{ id, name, text, createdAt, updatedAt, source, versions }` living once in its own IndexedDB key; workspaces and conversations reference it through `docIds`, so one doc serves several owners without copies.
`source` records provenance: `{ kind: 'upload' | 'research' | 'chat' | 'revise', runId?, convoId?, messageId? }`.
`docsOf(owner)` resolves refs at read time and drops dangling ones; `attachedDocs(convo)` merges workspace docs first, then the conversation's own, deduped by id, and the order is load-bearing because docs sit in the cached stable half of `system`.
Removing a ref (`removeDocRef`) deletes the doc once no workspace or conversation references it, and deleting a workspace or conversation releases its refs through the same GC; `deleteDoc` removes a doc outright and strips every ref.
Docs enter the store four ways: workspace upload (WorkspacePanel), a finished research run (`applyResearch`, report doc tagged with its `runId`), promoting an assistant reply (MessageBubble's save-as-document action), and revision (DocRow's utility-model revise, which pushes the prior text onto `versions`, capped at 10 because `flush()` snapshots the whole archive per write).
Docs are plain text sent whole per request; chunked retrieval (the recall scorer fits) is the upgrade path if attached docs outgrow the context window.
A single-conversation export carries the docs it references; importing merges them with the same keep-local collision rule.

### Memory / compression (`frontend/src/memory.js`)

When `use_memory` is on, `refreshMemory` runs in the background after each assistant reply (fire-and-forget, off the send path).
It summarizes the `summarize_n` turns just above the send window into `convo.memory` via the utility model, and records where coverage ends in `memoryCount`.
`buildPayload` sends everything after `memoryCount` verbatim, so an in-flight, failed, or lagging refresh only widens the verbatim window and every turn stays covered by one or the other.
The summary is stateless (the window is re-read in full each refresh), so message edits/deletes can't desync it; a per-convo sequence counter makes the last-started refresh win if two overlap.

Turns older than `summarize_n` + the send window drop out of context entirely; recall (above) retrieves them on demand.

### Frontend module map (`frontend/src/`)

| File | Responsibility |
|------|----------------|
| `store.js` | Reactive conversation, workspace, document and research-run state, IndexedDB persistence, versioned export/import, and replace-all snapshot restore. Also `applyResearch()`, which lands a finished run in a workspace, and `downloadText()`, the one way a doc leaves the browser as a file. IndexedDB is best-effort storage, so `initStore()` requests `navigator.storage.persist()`, and a failed write raises a notification with an export offer while the data is still intact in memory. |
| `settings.js` | The settings surface: `SETTING_KEYS` (what a conversation may override), `RESEARCH_KEYS` (what a run may override), and `EFFORT_LEVELS`, the single definition of the thinking-effort lever. `effectiveSettings(owner, keys)` resolves either list against the global defaults. |
| `api.js` | Auth (token in localStorage), `fetchSettings`/`fetchModels`, `fetchUrl`, and the research calls (`clarifyResearch`, `startResearch`, `streamResearch`, `discardResearch`). `streamChat` and the research stream share one `readSSE` reader, since both servers frame identically. Provider-blind. |
| `cards.js` | Pure card concerns: trigger matching, force overrides, `effectiveCards`, and the card builder's parsing half: `CARDGEN_SYSTEM` (the prompt that teaches the trigger syntax) and `parseGeneratedCards()` (fence- and prose-tolerant JSON parsing, strict on shape). Vue-free, so it runs in Node. |
| `payload.js` | Request assembly: `buildPayload`, the send window, and lexical recall. With `use_cache` on, `buildPayload` returns `system` as `[stable, volatile]`. Dependency direction is payload.js -> cards.js; both are Vue-free. |
| `memory.js` | Background sliding-window summarization. |
| `titles.js` | Auto-titling from recent turns via the utility model. |
| `usage.js` | Client-side usage ledger: day/model/kind buckets, `convo.usage`, IndexedDB-persisted; joins the full snapshot export/restore. |
| `composables/useStreamGuard.js` | Holds a screen wake lock while streaming and aborts a stream after `STALL_MS` (60s) of silence when the tab returns to the foreground. The abort uses the normal stop path. |
| `utils/md.js` | Markdown in, sanitized and highlighted HTML out. |
| `utils/format.js` | Timestamp formatting (native `Intl`). |
| `utils/theme.js` | Light/dark toggle. |
| `utils/prefs.js` | Frontend-only UI prefs (font scale, Enter-to-send), persisted to localStorage. |
| `utils/confirm.js` | Promise-based confirm: `await confirmDelete(msg)`, backed by one `ConfirmModal` at app root. |
| `utils/notify.js` | Reactive app-wide notification queue with keyed dedupe and dismissal; `notify.selfcheck.js` checks its contract. |
| `views/ChatPane.vue` | The chat window: message list, composer, toolbar (model + thinking-effort pickers), and the stream loop. Renders the last `PAGE_SIZE` (100) messages with "Load more" (display-only, and separate from what's sent), and marks the send-window start with a divider. |
| `components/MessageBubble.vue` | One message: view/edit bubble, pin/copy/delete/regenerate/save-as-document actions, and the live thinking/search trace while it streams (ephemeral, dropped on reload). List and stream mutations stay in ChatPane, behind events. |
| `components/ModelSelect.vue` | The one model dropdown, rendered in five places. Groups models by provider with native `<optgroup>`. |
| `views/Login.vue` | Password prompt shown until a token exists. |
| `components/ContextPanel.vue` | Edits system + pinned messages together. Also the URL fetch box: a fetched page lands as a system message, so it edits, deletes and sends like any other context. Also the document picker: attach any stored doc to the conversation, detach it, or delete it from the store. |
| `components/DocRow.vue` | One document row shared by WorkspacePanel and ContextPanel: rendered preview, download, remove, and the revise action (utility model rewrites the text, prior version kept for undo). |
| `components/CardsPanel.vue` | Card editor with live "active" indicators. For a convo in a workspace, lists the workspace's cards read-only above the convo's own. Also reused by WorkspacePanel as the shared-card editor (a workspace passes as `convo`; its missing messages/settings are guarded). The card builder lives here: pasted text goes to the utility model, and the parsed cards are appended to whichever owner the panel got, which is what makes it work in both scopes. |
| `components/WorkspacePanel.vue` | Workspace editor for the name, shared prompt, shared cards, and documents (uploaded here, rendered as DocRow rows). |
| `components/DebugPanel.vue` | Read-only live preview of the assembled `system` param (via `buildPayload`). |
| `components/SettingsPanel.vue` / `GlobalSettings.vue` | Per-conversation overrides / global defaults. |
| `components/Notifications.vue` | App-root renderer for sticky banners and transient Reka toasts. |
| `views/Sidebar.vue` | `PaneTabs`, then new-chat and new-research buttons, then template, research-run and conversation lists. Workspace rows head their member conversations (click to edit, RowActionsMenu to delete) and double as the management surface; unassigned conversations sit under a "Conversations" label. |
| `components/RowActionsMenu.vue` | Reka `DropdownMenu` behind one "..." trigger per sidebar row, replacing the hover icon strips run/template/workspace/convo rows each had. |
| `components/shell/PaneTabs.vue` | The Chat/Research/Usage `TabsList`, mounted in `Sidebar.vue` inside the `TabsRoot` App.vue wraps around Sidebar and the panes. Its `TabsTrigger`s and the panes' `TabsContent` share one Reka Tabs vocabulary. |
| `views/ResearchPane.vue` | Research view for `currentRun`, shown when `store.js`'s `activePane` is `'research'` (`selectRun` sets both it and `currentRunId`). Brief, clarifying questions, per-run model overrides, live progress and spend, then `applyResearch()` into a workspace. Reconnects from the last stored sequence after a dropped stream. No run selected renders an empty state with a "Start one" action. |
| `views/UsagePane.vue` | Usage ledger table by model and kind, optionally scoped by native From/To date inputs. The pane keeps its range while hidden, so returning from Chat or Research preserves it. |
| `components/Modal.vue` / `ConfirmModal.vue` | Reka `Dialog` shell (focus trap, aria wiring) / Reka `AlertDialog` shared delete-confirmation dialog. |
| `components/SpendBadge.vue` | One spend summary (calls, k tokens, `>$X.XX` with the unpriced tooltip), mounted in research, chat (`convo.usage`), and each Usage-pane row. |

### PWA (`frontend/vite.config.js`)

`vite-plugin-pwa` precaches the generated app shell and emits `manifest.json`; registration uses `registerType: 'prompt'`. It has no runtime cache and denies `/api` navigation fallback, because caching an unending chat or research SSE response would buffer it forever.

## Local development

Run the two halves separately with hot reload.
Vite proxies `/api` to `:8000`.

**Backend** (use a venv):

```sh
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows; .venv/bin on *nix
cp .env.example .env        # set APP_PASSWORD and at least one provider key
.venv/Scripts/python -m uvicorn main:app --reload --port 8000
```

**Frontend:**

```sh
cd frontend
pnpm install
pnpm dev
```

## Checks

Every module with non-trivial logic carries a directly runnable, assert-based self-check.

Card / payload logic, the confirm dialog, and export/import:

```sh
cd frontend
node src/cards.selfcheck.js
node src/payload.selfcheck.js
node src/utils/confirm.selfcheck.js
node src/utils/md.selfcheck.js
node src/store.selfcheck.js
node src/usage.selfcheck.js
```

The backend's live at the bottom of each module, behind `__main__`, so uvicorn (which imports `app`) skips them:

```sh
cd backend                          # .venv/Scripts on Windows, .venv/bin on *nix
.venv/Scripts/python -m providers  # registry, request builders, cache split, and all three event mappings
.venv/Scripts/python main.py        # SSE JSON framing
.venv/Scripts/python auth.py        # token mint/verify roundtrip, require_auth rejections
.venv/Scripts/python fetcher.py     # SSRF guard, URL canonicalization
.venv/Scripts/python topic.py       # section ranking, headingless fallback
.venv/Scripts/python research.py    # blocklist matching, finder parsing + precedence, list parsing, spend, page cache, source-failure isolation
.venv/Scripts/python runs.py        # payload numbering, failed-report recovery, forget and evict
```

The wake lock and stall watchdog in `composables/useStreamGuard.js` are verified on a real mobile browser: background a stream mid-reply for over a minute, then return.
Expect the partial reply, an idle composer, and no spinner.

Production build (also what the container runs):

```sh
cd frontend
pnpm build      # outputs dist/, copied to backend ./static in the image
```

## Container

A single image builds the SPA and serves it from the backend; see [`Containerfile`](Containerfile).
The Vite `public/` folder (including `logo.png`) is emitted into `dist/` and served as static files, so the favicon and in-app logo ship automatically.

The sidebar footer version comes from the `version` field in `frontend/package.json`.
Bump it when tagging a release.
