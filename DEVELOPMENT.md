# Development

Technical reference for working on conversa.
For what the app does and how to run the released container, see the [README](README.md).

## Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | **Vue 3 + Vite** | Small, reactive, no build ceremony. |
| Styling | **Tailwind CSS v4** | Semantic CSS-variable tokens that flip on `.dark`. |
| Icons | **@lucide/vue** | Consistent outline set. |
| Markdown | **marked** + **DOMPurify** + **highlight.js** | Render, sanitize, highlight. Sanitizing is the security boundary. |
| Client storage | **IndexedDB** (via `idb-keyval`) | All conversation state; survives reloads, with no size cliff like localStorage. |
| Backend | **FastAPI** + **uvicorn** | Async proxy to the model providers, plus the fetcher and the research run loop. |
| Fetching | **httpx** + **trafilatura** + **pypdf** | Manual redirect control for the SSRF guard, readable-text extraction that keeps fenced code blocks, and PDF text. |
| Auth | **PyJWT** (HS256) | Password is exchanged once for a signed, expiring token. |
| LLM | **Anthropic Python SDK** + **OpenAI Python SDK** | `messages.stream()` and `responses.create(stream=True)`, both mapped onto one SSE format. |

## Architecture

Everything that *is* a conversation lives in the browser (IndexedDB): messages, settings, cards, templates, memory.
The backend writes nothing to disk.
It exists to keep the provider keys off the client and to gate access.
The one thing it does hold is in-flight research runs, in memory, which die with the process.

```
Browser (Vue SPA, IndexedDB)  --HTTPS-->  FastAPI  -->  Anthropic API
   all state here                     keys + password    OpenAI API
                                                         streaming
```

### Backend endpoints (`backend/main.py`)

- `POST /api/login`: exchanges `APP_PASSWORD` (constant-time compared) for a signed, expiring JWT.
- `POST /api/refresh`: trades a still-valid token for a fresh full-TTL one.
  The client calls it opportunistically once a token is past half-life (sliding session).
- `GET  /api/settings`: global setting defaults from env vars, plus `config_errors` (see Providers below).
- `GET  /api/models`: selectable models as `{id, label, provider}`, filtered to the providers that have a key.
- `POST /api/chat`: streams a completion as SSE, from whichever provider owns the requested model.
  The API keys stay on the server.
  Assembled server-side: `effort` becomes thinking config via `apply_thinking()` or `reasoning.effort` (below), and the hosted search tools are attached when their env vars are non-empty.
  Text, thinking, and tool-trace events (`search`, `fetch`, `results`) are each JSON-encoded per SSE chunk so content can't break the framing.
  A list-valued `system` is `[stable, volatile]`: `system_param()` caches the first block (`use_cache`, off by default) and OpenAI rejoins it, since it caches prefixes itself.
- `POST /api/fetch`: a URL becomes readable markdown (`backend/fetcher.py`).
  Nothing is stored.
  With a `topic`, `backend/topic.py` returns the sections that answer it rather than the head of the page.
- `POST /api/research/clarify`: 3 to 5 questions about a brief, asked before any run starts.
  The answers go back in the brief, so the planner reads the scope rather than inferring it.
- `POST /api/research`: starts a run and returns its id.
  `GET /api/research/{id}` reads its state, `GET /api/research/{id}/stream` replays from `?after=<seq>` then tails live as SSE, `DELETE /api/research/{id}` cancels it.

### Provider layer (`backend/llm.py`)

Clients, the model registry, `split_model`, `apply_thinking`, and `complete()`.
Anything that knows an API key or a model id lives here.
`main.py` owns the web app and `research.py` owns the run loop, and both import this, which is what lets them avoid importing each other.

### Research runs (`backend/research.py`)

A run is an `asyncio.Task` plus an event list held in the `RUNS` dict.
That is enough to survive the client closing its tab, which is the only durability the feature needs: the brief lives in the browser, and a process restart means starting again.
Nothing touches disk.

Phases are plan, gather, gap, report.
Gather fans out one coroutine per subquestion under a semaphore; each searches, fetches, and writes notes, then drops the document.
Notes and source URLs are all that survive, so a run's memory is flat whether it reads 20 sources or 200.

Two measured findings shaped this.
Search prompt wording does not move source quality, because the hosted tool returns what its backend returns; `BLOCKED_DOMAINS` does, and blocking server-side makes the backend offer a replacement instead of a gap.
And subquestions overlap enough that one canonical source gets picked repeatedly, so `PageCache` downloads each URL once per run and topic-selects it per subquestion, which keeps the notes distinct while paying for one fetch.

Failure handling is deliberate, because a run makes about 30 calls and a transient 429 or 529 during one of them should be expected.
The SDK retries are raised to 5.
One source failing costs that source.
A failed search costs one subquestion.
A failed report hands the notes back raw, since the notes are the expensive part.
The SSE stream emits a 1-second `tick`, without which a phase running for a minute looks to an idle proxy like a dead connection, and a client cannot tell that from a finished run.

`PROMPTS` is the tuning surface and a request may override any key.
The finished payload is a workspace: the report as a doc, per-subquestion notes as `q1`..`qN` cards, so the detail is one keystroke away and stays out of turns that do not ask for it.

### Fetching (`backend/fetcher.py`, `backend/topic.py`)

Ported from [magpi](https://github.com/grainologic/magpi) (MIT). trafilatura extracts HTML, chosen over readability-lxml because it keeps fenced code blocks; a content-type branch handles JSON and plain text; a Wayback lookup retries 403/404/410/451.

`assert_public_target()` is the security boundary: this endpoint opens a caller-supplied URL from inside the network, so it rejects non-http schemes, loopback names, literal private IPs, and names that resolve into a private range.
Redirects are followed by hand so the check runs on every hop.
The known gap is DNS rebinding between the resolve and the connect; closing it needs a custom transport that dials a pinned IP.

### Providers (`split_model`, `parse_models` in `backend/llm.py`)

A model id carries its provider as a prefix: `openai/gpt-5.6-sol`.
`split_model()` splits on the last `/` and treats a bare id as Anthropic, permanently: conversations persisted before OpenAI support hold bare ids in IndexedDB, and `.env` files still use them.
Bare keeps meaning Anthropic the way a bare Docker image name keeps meaning `docker.io`.

Everything downstream of the dropdown treats the id as opaque, so provider logic lives entirely in `llm.py`.

A provider with no key follows two rules:

- `/api/models` returns only the providers that have a key, because an offered but unusable option surfaces as a bare 503 on send, and surfaces *silently* when it's the utility model (`refreshMemory` and `generateTitle` both swallow their errors).
- What got dropped, and any `DEFAULT_MODEL` / `DEFAULT_UTILITY_MODEL` that isn't selectable, is logged and returned in `config_errors` on `/api/settings`.
  `App.vue` strips that key before merging the rest into `globalSettings` and shows it in a dismissible banner.
  Misconfiguration degrades the app and lets it start, so one missing key still leaves the other provider working.

### OpenAI specifics (`openai_stream` in `backend/main.py`)

Uses the **Responses API**, the surface that carries hosted web search and reasoning summaries.
Chat Completions offers neither.
The event mapping onto conversa's own SSE frames:

| conversa frame | Responses event |
|---|---|
| `text` | `response.output_text.delta` |
| `think` | `response.reasoning_summary_text.delta` |
| `search` / `fetch` | `response.output_item.done` where the item is a `web_search_call` (`action.type` of `search` or `open_page`) |
| `results` | `response.output_text.annotation.added` with a `url_citation` |

`OPENAI_REASONING_PREFIXES` decides which models take `reasoning.effort` and reject `temperature`, mirroring `LEGACY_MODELS` on the Anthropic side.
`summary: "auto"` is what makes reasoning text stream.
Effort remains a hint: at `low` with a short system prompt these models often return no reasoning item, which reaches the UI as an empty trace.
`field()` reads SDK objects and plain dicts alike, so an annotation shape that changes between SDK versions costs one trace event and the stream continues.

### Thinking effort (`apply_thinking` in `backend/llm.py`)

The wire format for extended thinking split across model generations, so one branch translates the single `effort` lever (`""` / `low` / `medium` / `high`) per model:

| | Claude 4.6+ | Pre-4.6 (`LEGACY_MODELS`) |
|---|---|---|
| Thinking | `{type: adaptive, display: summarized}` | `{type: enabled, budget_tokens: N}` |
| Depth control | `output_config.effort` | `LEGACY_EFFORT_BUDGETS` (4000/10000/24000) |
| `temperature` | **never sent**, since Opus 4.7+ reject it outright | sent, unless thinking is on |
| `max_tokens` | floored at 32000 (thinking spends from it) | floored at `budget + DEFAULT_MAX_TOKENS` |

`display: summarized` is deliberate: the API default is `omitted`, which streams empty thinking blocks and would blank ChatPane's live trace.
Unknown model ids are treated as modern.
`LEGACY_MODELS` is a hand-maintained set of older ids, so adding a pre-4.6 model to `MODELS` means adding its id there too.
The three lever words (`low` / `medium` / `high`) are `EFFORT_VALUES`, and both providers accept them verbatim, which is why one picker drives both.
Covered by the self-check at the bottom of `main.py` (`python main.py`).

All endpoints except `/api/login` require `Authorization: Bearer <token>`.
A 401 logs the client out automatically.
In production the SPA is served from the same origin (`StaticFiles` mount), so CORS is irrelevant; `CORS_ORIGINS` is dev-only.

### How a request is assembled (`frontend/src/cards.js`)

`buildPayload(convo, settings, workspace)` turns a conversation into the Anthropic request:

- **`system` param** gets the workspace's shared prompt (if `send_system_prompt`), then all system messages (same gate), the workspace's plain-text docs in full, the memory summary (if `use_memory`), and the content of any triggered cards.
  The card scan runs over workspace cards and convo cards together, workspace first (`effectiveCards`).
  `convo.cardOverrides[cardId]` = `'include'` / `'skip'` replaces a workspace card's force for that one conversation.
  Card triggers are comma-separated clauses (comma = OR, `&` inside a clause = AND).
  Each card is prefixed with the clause that triggered it (`phrase: content`); force-include cards with no matching clause send bare content.
- **`messages` array** gets pinned turns first (deduped), then the *send window* (the last `num_messages_to_send` turns; with memory on, everything past the summary's coverage, floored at `num_messages_to_send`).
  Only user/assistant turns go here, since both providers keep the system prompt in a separate field.
- **recall** (if `use_recall`) also rides in `system`: the top `RECALL_COUNT` (3) *dropped* turns (neither pinned nor in the window), scored by stopword-filtered token overlap with the latest user message, normalized by sqrt(length), returned chronologically.
  It reads the history without rewriting it, so unlike memory it survives edits and deletes.
- **model / temperature / max_tokens / effort** are passed through from the effective settings.

Pinned turns bypass the send-window limit; this does **not** enforce user/assistant alternation, so wildly mixed pins could be rejected by the API.

With `use_cache` on, `system` comes back as `[stable, volatile]` rather than a string.
The stable half is everything above the memory summary: workspace prompt, system messages, workspace docs.
`system_param()` in `main.py` marks the first block ephemeral, so a large workspace is billed once per cache window instead of per turn, and OpenAI rejoins the two since it caches prefixes itself.
The order is what makes this work: prompt caching is prefix-match, and cards are assembled last, so a card firing mid-conversation rewrites only the uncached tail.
Messages stay uncached because the send window drops turns off the front as it slides, which changes the message prefix on most turns.

### Workspaces (`frontend/src/store.js`)

A workspace is `{ id, name, systemPrompt, cards, docs }` in its own IndexedDB key, persisted through the same debounced save as conversations.
A conversation joins by setting `convo.workspaceId`; `workspaceOf(convo)` resolves it (null for a missing or deleted workspace, which degrades to plain-convo behavior everywhere).
The merge into the request happens at read time in `buildPayload`, so joining, leaving, and deleting a workspace touch only that pointer.
Docs are plain text, stored inline and sent whole per request; chunked retrieval (the recall scorer fits) is the upgrade path if docs outgrow the context window.
Full export carries workspaces (`{ conversations, workspaces }`); import also accepts the older bare-array format, and on a workspace id collision keeps the local copy so existing links stay resolvable.

### Memory / compression (`frontend/src/memory.js`)

When `use_memory` is on, `refreshMemory` runs in the background after each assistant reply (fire-and-forget, off the send path).
It summarizes the `summarize_n` turns just above the send window into `convo.memory` via the utility model, and records where coverage ends in `memoryCount`.
`buildPayload` sends everything after `memoryCount` verbatim, so an in-flight, failed, or lagging refresh only widens the verbatim window and every turn stays covered by one or the other.
The summary is stateless (the window is re-read in full each refresh), so message edits/deletes can't desync it; a per-convo sequence counter makes the last-started refresh win if two overlap.

Turns older than `summarize_n` + the send window drop out of context entirely; recall (above) retrieves them on demand.

### Frontend module map (`frontend/src/`)

| File | Responsibility |
|------|----------------|
| `store.js` | Reactive conversation, workspace and research-run state, IndexedDB persistence (debounced, with `persistNow()`). Owns `SETTING_KEYS` (what a conversation may override), `RESEARCH_KEYS` (what a run may override), and `EFFORT_LEVELS`, the single definition of the thinking-effort lever. `effectiveSettings(owner, keys)` resolves either list against the global defaults. Also `applyResearch()`, which lands a finished run in a workspace, and `downloadText()`, the one way a doc leaves the browser as a file. IndexedDB is best-effort storage, so `initStore()` requests `navigator.storage.persist()`, and a failed write sets `storageError`, which App.vue surfaces with an export offer while the data is still intact in memory. |
| `api.js` | Auth (token in localStorage), `fetchSettings`/`fetchModels`, `fetchUrl`, and the research calls (`clarifyResearch`, `startResearch`, `streamResearch`, `stopResearch`). `streamChat` and the research stream share one `readSSE` reader, since both servers frame identically. Provider-blind. |
| `cards.js` | Pure card-matching, lexical recall, + `buildPayload`. With `use_cache` on, `buildPayload` returns `system` as `[stable, volatile]` instead of a string. Also the card builder's halves that can run in Node: `CARDGEN_SYSTEM` (the prompt that teaches the trigger syntax) and `parseGeneratedCards()` (fence- and prose-tolerant JSON parsing, strict on shape). Vue-free, so it runs in Node. |
| `memory.js` | Background sliding-window summarization. |
| `titles.js` | Auto-titling from recent turns via the utility model. |
| `md.js` | Markdown in, sanitized and highlighted HTML out. |
| `format.js` | Timestamp formatting (native `Intl`). |
| `theme.js` | Light/dark toggle. |
| `prefs.js` | Frontend-only UI prefs (font scale, Enter-to-send), persisted to localStorage. |
| `confirm.js` | Promise-based confirm: `await confirmDelete(msg)`, backed by one `ConfirmModal` at app root. |
| `components/ChatPane.vue` | The chat window: messages, actions, composer, toolbar (model + thinking-effort pickers). Renders the last `PAGE_SIZE` (100) messages with "Load more" (display-only, and separate from what's sent), marks the send-window start with a divider, and shows the live thinking/search trace (ephemeral, dropped on reload). Also owns the backgrounded-tab defences: a screen wake lock held while streaming, and a `visibilitychange` watchdog that aborts a stream gone silent for `STALL_MS` (60s), so a frozen tab ends in the normal stop path instead of a stuck spinner. |
| `components/ModelSelect.vue` | The one model dropdown, rendered in five places. Groups models by provider with native `<optgroup>`. |
| `components/Login.vue` | Password prompt shown until a token exists. |
| `components/ContextPanel.vue` | Edits system + pinned messages together. Also the URL fetch box: a fetched page lands as a system message, so it edits, deletes and sends like any other context. |
| `components/CardsPanel.vue` | Card editor with live "active" indicators. For a convo in a workspace, lists the workspace's cards read-only above the convo's own. Also reused by WorkspacePanel as the shared-card editor (a workspace passes as `convo`; its missing messages/settings are guarded). The card builder lives here: pasted text goes to the utility model, and the parsed cards are appended to whichever owner the panel got, which is what makes it work in both scopes. |
| `components/WorkspacePanel.vue` | Workspace editor: name, shared prompt, shared cards (via CardsPanel), and documents. A doc expands to a rendered read view and carries a download button, because a research report arrives here and has to be readable and savable, not just deletable. |
| `components/DebugPanel.vue` | Read-only live preview of the assembled `system` param (via `buildPayload`). |
| `components/SettingsPanel.vue` / `GlobalSettings.vue` | Per-conversation overrides / global defaults. |
| `components/Sidebar.vue` | New-chat and new-research buttons, then template, research-run and conversation lists. Workspace rows head their member conversations (click to edit, X to delete) and double as the management surface; unassigned conversations sit under a "Conversations" label. |
| `components/ResearchPane.vue` | The research window, a sibling of ChatPane rather than a panel inside it. `currentRunId` being set is what swaps it in. Brief, clarifying questions, per-run model overrides, live progress and spend, then `applyResearch()` into a workspace. Reconnects a live run from the last stored seq, so a dropped stream resumes instead of reading as finished. |
| `components/Modal.vue` / `ConfirmModal.vue` | Generic modal shell / shared delete-confirmation dialog. |

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

Every module with non-trivial logic carries an assert-based self-check.
There is no test framework: a check is the module itself, run directly.

Card / payload logic, the confirm dialog, and export/import:

```sh
cd frontend
node src/cards.selfcheck.js
node src/confirm.selfcheck.js
node src/store.selfcheck.js
```

The backend's live at the bottom of each module, behind `__main__`, so uvicorn (which imports `app`) skips them:

```sh
cd backend                          # .venv/Scripts on Windows, .venv/bin on *nix
.venv/Scripts/python llm.py         # apply_thinking, split_model, parse_models, field
.venv/Scripts/python main.py        # system_param, the [stable, volatile] cache split
.venv/Scripts/python fetcher.py     # SSRF guard, URL canonicalization
.venv/Scripts/python topic.py       # section ranking, headingless fallback
.venv/Scripts/python research.py    # blocklist matching, list parsing, spend, payload numbering, page cache, failure isolation
```

The wake lock and stall watchdog in `ChatPane.vue` are verified on a real mobile browser: background a stream mid-reply for over a minute, then return.
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
