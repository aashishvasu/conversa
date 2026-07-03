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
  never leaves the server.

All endpoints except `/api/login` require `Authorization: Bearer <token>`. A 401
logs the client out automatically. In production the SPA is served from the same
origin (`StaticFiles` mount), so CORS is irrelevant; `CORS_ORIGINS` is dev-only.

### How a request is assembled (`frontend/src/cards.js`)

`buildPayload(convo, settings)` turns a conversation into the Anthropic
request:

- **`system` param** ← all system messages (if `send_system_prompt`), the memory
  summary (if `use_memory`), and the content of any triggered cards. Each card is
  prefixed with the phrase that triggered it (`phrase: content`); force-include
  cards with no matching phrase send bare content.
- **`messages` array** ← pinned turns first (deduped), then the *send window*
  (the last `num_messages_to_send` turns, or everything not yet folded into memory
  when memory is on). Only user/assistant turns go here — Anthropic keeps `system`
  separate.

Pinned turns bypass the send-window limit; this does **not** enforce
user/assistant alternation, so wildly mixed pins could be rejected by the API.

### Memory / compression (`frontend/src/memory.js`)

When `use_memory` is on, `compressIfNeeded` folds the oldest unsummarized turns
into a rolling `memory` string (via the utility model) until the verbatim tail is
under `compression_threshold` chars, advancing `memoryCount`. The summary is
cached on the conversation and only re-runs when enough new old turns accumulate.

> Known limitation: editing or deleting an already-summarized message desyncs the
> memory. **Clear** in Conversation settings rebuilds it.

### Frontend module map (`frontend/src/`)

| File | Responsibility |
|------|----------------|
| `store.js` | Reactive conversation state + IndexedDB persistence (debounced, with `persistNow()`). |
| `api.js` | Auth (token in localStorage), `fetchSettings`/`fetchModels`, `streamChat` SSE reader. |
| `cards.js` | Pure card-matching + `buildPayload`. No Vue — runnable in Node. |
| `memory.js` | Rolling-summary compression. |
| `titles.js` | Auto-titling from recent turns via the utility model. |
| `md.js` | Markdown → sanitized, highlighted HTML. |
| `format.js` | Timestamp formatting (native `Intl`). |
| `theme.js` | Light/dark toggle. |
| `prefs.js` | Frontend-only UI prefs (font scale, Enter-to-send), persisted to localStorage. |
| `confirm.js` | Promise-based confirm: `await confirmDelete(msg)`, backed by one `ConfirmModal` at app root. |
| `components/ChatPane.vue` | The chat window: messages, actions, composer, toolbar. |
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
