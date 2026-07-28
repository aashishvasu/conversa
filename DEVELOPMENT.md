# Development

Technical reference for working on conversa. For what the app does and how to run
the released container, see the [README](README.md).

## Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | **Vue 3 + Vite** | Small, reactive, no build ceremony. |
| Styling | **Tailwind CSS v4** | Semantic CSS-variable tokens that flip on `.dark`. |
| Icons | **lucide-vue-next** | Consistent outline set. |
| Markdown | **marked** + **DOMPurify** + **highlight.js** | Render → sanitize → highlight. Sanitizing is the security boundary. |
| Client storage | **IndexedDB** (via `idb-keyval`) | All conversation state; survives reloads, no size cliff like localStorage. |
| Backend | **FastAPI** + **uvicorn** | Thin async proxy to Anthropic. |
| Auth | **PyJWT** (HS256) | Password is exchanged once for a signed, expiring token. |
| LLM | **Anthropic Python SDK** | `messages.stream()` → SSE. |

## Architecture

Everything that *is* a conversation lives in the browser (IndexedDB): messages,
settings, cards, templates, memory. The backend is stateless — no database. It
exists only to keep the Anthropic key off the client and to gate access.

```
Browser (Vue SPA, IndexedDB)  ──HTTPS──>  FastAPI  ──>  Anthropic API
   all state here                         key + password      streaming
```

### Backend endpoints (`backend/main.py`)

- `POST /api/login` — exchanges `APP_PASSWORD` (constant-time compared) for a
  signed, expiring JWT.
- `POST /api/refresh` — trades a still-valid token for a fresh full-TTL one. The
  client calls it opportunistically once a token is past half-life (sliding session).
- `GET  /api/settings` — global setting defaults from env vars.
- `GET  /api/models` — selectable models with labels.
- `POST /api/chat` — streams a completion from Anthropic as SSE. The API key
  never leaves the server. Two things are assembled server-side: `effort` becomes
  thinking config via `apply_thinking()` (below), and `WEB_SEARCH_TOOL_VERSION` — if
  not empty — attaches the server-side `web_search` tool (`max_uses: 5`). Text,
  thinking, and search events are each JSON-encoded per SSE chunk so content can't
  break the framing.

### Thinking effort (`apply_thinking` in `backend/main.py`)

The wire format for extended thinking split across model generations, so one branch
translates the single `effort` lever (`""` / `low` / `medium` / `high`) per model:

| | Claude 4.6+ | Pre-4.6 (`LEGACY_MODELS`) |
|---|---|---|
| Thinking | `{type: adaptive, display: summarized}` | `{type: enabled, budget_tokens: N}` |
| Depth control | `output_config.effort` | `LEGACY_EFFORT_BUDGETS` (4000/10000/24000) |
| `temperature` | **never sent** — Opus 4.7+ reject it outright | sent, unless thinking is on |
| `max_tokens` | floored at 32000 (thinking spends from it) | floored at `budget + DEFAULT_MAX_TOKENS` |

`display: summarized` is deliberate: the API default is `omitted`, which streams
empty thinking blocks and would blank ChatPane's live trace. Unknown model ids are
treated as modern — `LEGACY_MODELS` is a hand-maintained set of older ids, so adding
a pre-4.6 model to `MODELS` means adding its id there too. Covered by the self-check
at the bottom of `main.py` (`python main.py`).

All endpoints except `/api/login` require `Authorization: Bearer <token>`. A 401
logs the client out automatically. In production the SPA is served from the same
origin (`StaticFiles` mount), so CORS is irrelevant; `CORS_ORIGINS` is dev-only.

### How a request is assembled (`frontend/src/cards.js`)

`buildPayload(convo, settings)` turns a conversation into the Anthropic
request:

- **`system` param** ← all system messages (if `send_system_prompt`), the memory
  summary (if `use_memory`), and the content of any triggered cards. Card triggers
  are comma-separated clauses (comma = OR, `&` inside a clause = AND). Each card is
  prefixed with the clause that triggered it (`phrase: content`); force-include
  cards with no matching clause send bare content.
- **`messages` array** ← pinned turns first (deduped), then the *send window*
  (the last `num_messages_to_send` turns; with memory on, everything past the
  summary's coverage — never fewer than `num_messages_to_send`). Only
  user/assistant turns go here — Anthropic keeps `system` separate.
- **recall** (if `use_recall`) also rides in `system`: the top `RECALL_COUNT` (3)
  *dropped* turns — not pinned, not in the window — scored by stopword-filtered
  token overlap with the latest user message, normalized by √length, returned
  chronologically. Non-destructive, so unlike memory it can't desync on edits.
- **model / temperature / max_tokens / effort** are passed through from the
  effective settings.

Pinned turns bypass the send-window limit; this does **not** enforce
user/assistant alternation, so wildly mixed pins could be rejected by the API.

### Memory / compression (`frontend/src/memory.js`)

When `use_memory` is on, `refreshMemory` runs in the background after each
assistant reply (fire-and-forget — the send path never waits on it). It
summarizes the `summarize_n` turns just above the send window into
`convo.memory` via the utility model, and records where coverage ends in
`memoryCount`. `buildPayload` sends everything after `memoryCount` verbatim, so
an in-flight, failed, or lagging refresh only widens the verbatim window —
nothing falls in a gap. The summary is stateless (the window is re-read in full
each refresh), so message edits/deletes can't desync it; a per-convo sequence
counter makes the last-started refresh win if two overlap.

Turns older than `summarize_n` + the send window drop out of context entirely;
recall (above) retrieves them on demand.

### Frontend module map (`frontend/src/`)

| File | Responsibility |
|------|----------------|
| `store.js` | Reactive conversation state + IndexedDB persistence (debounced, with `persistNow()`). Owns `SETTING_KEYS` (what a conversation may override) and `EFFORT_LEVELS` — the single definition of the thinking-effort lever, rendered by both settings panels and the composer toolbar. |
| `api.js` | Auth (token in localStorage), `fetchSettings`/`fetchModels`, `streamChat` SSE reader. |
| `cards.js` | Pure card-matching, lexical recall, + `buildPayload`. No Vue — runnable in Node. |
| `memory.js` | Background sliding-window summarization. |
| `titles.js` | Auto-titling from recent turns via the utility model. |
| `md.js` | Markdown → sanitized, highlighted HTML. |
| `format.js` | Timestamp formatting (native `Intl`). |
| `theme.js` | Light/dark toggle. |
| `prefs.js` | Frontend-only UI prefs (font scale, Enter-to-send), persisted to localStorage. |
| `confirm.js` | Promise-based confirm: `await confirmDelete(msg)`, backed by one `ConfirmModal` at app root. |
| `components/ChatPane.vue` | The chat window: messages, actions, composer, toolbar (model + thinking-effort pickers). Renders the last `PAGE_SIZE` (100) messages with "Load more" — display-only, unrelated to what's sent — marks the send-window start with a divider, and shows the live thinking/search trace (ephemeral, never persisted). |
| `components/Login.vue` | Password prompt shown until a token exists. |
| `components/ContextPanel.vue` | Edits system + pinned messages together. |
| `components/CardsPanel.vue` | Card editor with live "active" indicators. |
| `components/DebugPanel.vue` | Read-only live preview of the assembled `system` param (via `buildPayload`). |
| `components/SettingsPanel.vue` / `GlobalSettings.vue` | Per-conversation overrides / global defaults. |
| `components/Sidebar.vue` | Conversation + template list. |
| `components/Modal.vue` / `ConfirmModal.vue` | Generic modal shell / shared delete-confirmation dialog. |

## Local development

Run the two halves separately with hot reload. Vite proxies `/api` to `:8000`.

**Backend** (use a venv):

```sh
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows; .venv/bin on *nix
cp .env.example .env        # set ANTHROPIC_API_KEY and APP_PASSWORD
.venv/Scripts/python -m uvicorn main:app --reload --port 8000
```

**Frontend:**

```sh
cd frontend
pnpm install
pnpm dev
```

## Checks

Card / payload logic, the confirm dialog, and export/import each have a self-check:

```sh
cd frontend
node src/cards.selfcheck.js
node src/confirm.selfcheck.js
node src/store.selfcheck.js
```

Production build (also what the container runs):

```sh
cd frontend
pnpm build      # outputs dist/, copied to backend ./static in the image
```

## Container

A single image builds the SPA and serves it from the backend — see
[`Containerfile`](Containerfile). The Vite `public/` folder (including
`logo.png`) is emitted into `dist/` and served as static files, so the favicon
and in-app logo ship automatically.

The sidebar footer version comes from the `version` field in
`frontend/package.json` — bump it when tagging a release.
